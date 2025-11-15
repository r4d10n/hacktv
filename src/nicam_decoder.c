/* hackrx - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - NICAM 728 Decoder Implementation                     */
/*                                                                       */
/* NICAM-728 Digital Audio Decoder                                       */
/* Based on BBC RD document "NICAM 728 - DIGITAL TWO-CHANNEL STEREO     */
/* FOR TERRESTRIAL TELEVISION"                                           */
/* http://downloads.bbc.co.uk/rd/pubs/reports/1990-06.pdf               */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "nicam_decoder.h"

/* Pre-calculated J.17 de-emphasis filter taps (inverse of pre-emphasis) */
static const int32_t _j17_deemphasis_taps[_J17_NTAPS] = {
	0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1,
	1, 1, 2, 2, 3, 3, 4, 5, 6, 7, 9, 11, 14, 17, 23, 29, 40,
	54, 79, 112, 177, 275, 474, 802, 1523, 8630, 1523, 802, 474, 275,
	177, 112, 79, 54, 40, 29, 23, 17, 14, 11, 9, 7, 6, 5, 4,
	3, 3, 2, 2, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 0, 0, 0, 0, 0
};

/* NICAM scaling factors for decompanding */
typedef struct {
	int factor;
	int shift;
	int coding_range;
	int protection_range;
} _scale_factor_t;

static const _scale_factor_t _scale_factors[8] = {
	{ 0, 2, 5, 7 }, /* 0b000 */
	{ 1, 2, 5, 7 }, /* 0b001 */
	{ 2, 2, 5, 6 }, /* 0b010 */
	{ 4, 2, 5, 5 }, /* 0b100 */
	{ 3, 3, 4, 4 }, /* 0b011 */
	{ 5, 4, 3, 3 }, /* 0b101 */
	{ 6, 5, 2, 2 }, /* 0b110 */
	{ 7, 6, 1, 1 }, /* 0b111 */
};

/* Generate PRN sequence for descrambling */
static void _generate_prn(uint8_t prn[NICAM_FRAME_BYTES - 1])
{
	int poly = 0x1FF;
	int x, i;

	for(x = 0; x < NICAM_FRAME_BYTES - 1; x++)
	{
		prn[x] = 0x00;

		for(i = 0; i < 8; i++)
		{
			uint8_t b;

			b = poly & 1;
			b ^= (poly >> 4) & 1;

			poly >>= 1;
			poly |= b << 8;

			prn[x] <<= 1;
			prn[x] |= b;
		}
	}
}

/* Calculate parity bit */
static uint8_t _parity(unsigned int value)
{
	uint8_t p = 0;

	while(value)
	{
		p ^= value & 1;
		value >>= 1;
	}

	return(p);
}

/* DQPSK symbol mapping (differential decode) */
static const int _phase_changes[4] = { 0, 90, 270, 180 };  /* degrees */

/* Demodulate DQPSK symbol from IQ samples */
static int _demod_dqpsk_symbol(cint32_t curr, cint32_t prev)
{
	/* DQPSK: phase change between symbols encodes 2 bits */
	int64_t dot_product = ((int64_t)curr.i * prev.i + (int64_t)curr.q * prev.q);
	int64_t cross_product = ((int64_t)curr.q * prev.i - (int64_t)curr.i * prev.q);

	/* Calculate phase difference */
	double phase_diff = atan2((double)cross_product, (double)dot_product);
	phase_diff = phase_diff * 180.0 / M_PI;

	/* Normalize to 0-360 */
	while(phase_diff < 0) phase_diff += 360.0;
	while(phase_diff >= 360.0) phase_diff -= 360.0;

	/* Map to symbol (0-3) */
	/* 0° = 0, 90° = 1, 270° = 2, 180° = 3 */
	if(phase_diff < 45.0 || phase_diff >= 315.0)
		return 0;  /* ~0° */
	else if(phase_diff >= 45.0 && phase_diff < 135.0)
		return 1;  /* ~90° */
	else if(phase_diff >= 225.0 && phase_diff < 315.0)
		return 2;  /* ~270° */
	else
		return 3;  /* ~180° */
}

/* Decode companded audio sample */
static int16_t _decode_sample(int16_t companded, const _scale_factor_t *scale)
{
	int32_t sample;
	int sign = (companded & 0x0400) ? -1 : 1;  /* Bit 10 is sign */
	int magnitude = companded & 0x03FF;  /* Bits 0-9 */

	/* Extract protection and coding ranges */
	int protection = magnitude >> scale->coding_range;
	int coding = magnitude & ((1 << scale->coding_range) - 1);

	/* Expand sample */
	sample = (coding << scale->shift) | (protection << (scale->shift + scale->coding_range));
	sample *= sign;

	/* Scale to 16-bit */
	sample = (sample << 6);  /* 10-bit to 16-bit */

	return (int16_t)(sample > 32767 ? 32767 : (sample < -32768 ? -32768 : sample));
}

/* Apply J.17 de-emphasis filter */
static void _apply_deemphasis(nicam_decoder_t *dec, int16_t audio[NICAM_AUDIO_LEN * 2])
{
	int x, i;
	int32_t sum_l, sum_r;

	for(x = 0; x < NICAM_AUDIO_LEN; x++)
	{
		/* Store current samples */
		dec->fir_l[dec->fir_p] = audio[x * 2 + 0];
		dec->fir_r[dec->fir_p] = audio[x * 2 + 1];

		/* Apply FIR filter */
		sum_l = 0;
		sum_r = 0;

		for(i = 0; i < _J17_NTAPS; i++)
		{
			int idx = (dec->fir_p + _J17_NTAPS - i) % _J17_NTAPS;
			sum_l += (int32_t)dec->fir_l[idx] * _j17_deemphasis_taps[i];
			sum_r += (int32_t)dec->fir_r[idx] * _j17_deemphasis_taps[i];
		}

		audio[x * 2 + 0] = (int16_t)(sum_l / 32768);
		audio[x * 2 + 1] = (int16_t)(sum_r / 32768);

		dec->fir_p = (dec->fir_p + 1) % _J17_NTAPS;
	}
}

/* Decode NICAM frame */
static int _decode_frame(nicam_decoder_t *dec)
{
	uint8_t descrambled[NICAM_FRAME_BYTES];
	int i, sample_idx;
	const _scale_factor_t *scale_l, *scale_r;

	/* Check frame alignment word (FAW) */
	if(dec->frame[0] != NICAM_FAW)
	{
		dec->frames_errors++;
		return -1;
	}

	/* Descramble frame using PRN sequence */
	descrambled[0] = dec->frame[0];  /* FAW is not scrambled */
	for(i = 1; i < NICAM_FRAME_BYTES; i++)
	{
		descrambled[i] = dec->frame[i] ^ dec->prn[i - 1];
	}

	/* Extract control bits */
	dec->mode = (descrambled[1] >> 5) & 0x07;
	dec->reserve = (descrambled[1] >> 4) & 0x01;

	/* Extract scale factors */
	scale_l = &_scale_factors[(descrambled[2] >> 5) & 0x07];
	scale_r = &_scale_factors[(descrambled[2] >> 2) & 0x07];

	/* Decode audio samples (skip first 3 bytes: FAW, control, scale) */
	sample_idx = 0;
	for(i = 3; i < NICAM_FRAME_BYTES && sample_idx < NICAM_AUDIO_LEN; i += 3)
	{
		/* Each audio sample is 10 bits + 1 parity bit */
		/* 2 samples per 3 bytes (actually 2.75 bytes per 2 samples) */

		if(i + 2 < NICAM_FRAME_BYTES)
		{
			/* Extract left sample (11 bits including parity) */
			uint16_t left_bits = (descrambled[i] << 3) | (descrambled[i+1] >> 5);
			uint8_t left_parity = left_bits & 1;
			uint16_t left_sample = left_bits >> 1;

			/* Check parity */
			if(_parity(left_sample) != left_parity)
			{
				/* Parity error - mute sample */
				left_sample = 0;
			}

			/* Extract right sample */
			uint16_t right_bits = ((descrambled[i+1] & 0x1F) << 6) | (descrambled[i+2] >> 2);
			uint8_t right_parity = right_bits & 1;
			uint16_t right_sample = right_bits >> 1;

			if(_parity(right_sample) != right_parity)
			{
				right_sample = 0;
			}

			/* Decode and store samples */
			if(sample_idx < NICAM_AUDIO_LEN)
			{
				dec->audio_out[sample_idx * 2 + 0] = _decode_sample(left_sample, scale_l);
				dec->audio_out[sample_idx * 2 + 1] = _decode_sample(right_sample, scale_r);
				sample_idx++;
			}
		}
	}

	/* Apply J.17 de-emphasis filter */
	_apply_deemphasis(dec, dec->audio_out);

	dec->audio_available = 1;
	dec->frames_decoded++;

	return 0;
}

/* Initialize NICAM decoder */
int nicam_decoder_init(nicam_decoder_t *dec, int sample_rate, double subcarrier_freq)
{
	memset(dec, 0, sizeof(nicam_decoder_t));

	dec->sample_rate = sample_rate;
	dec->subcarrier_freq = subcarrier_freq;
	dec->symbol_rate = NICAM_SYMBOL_RATE;  /* 364 ksym/s */
	dec->samples_per_symbol = sample_rate / dec->symbol_rate;

	/* Generate PRN sequence */
	_generate_prn(dec->prn);

	dec->sync_state = 0;  /* Start in search mode */

	return 0;
}

/* Process IQ samples */
int nicam_decoder_process(nicam_decoder_t *dec, const int16_t *iq_samples, int num_samples)
{
	int i;
	cint32_t symbol;

	for(i = 0; i < num_samples; i += 2)
	{
		/* Extract IQ sample */
		symbol.i = iq_samples[i];
		symbol.q = iq_samples[i + 1];

		dec->symbol_counter++;

		/* Demodulate symbol at symbol rate */
		if(dec->symbol_counter >= dec->samples_per_symbol)
		{
			dec->symbol_counter = 0;

			/* Demodulate DQPSK symbol */
			int sym = _demod_dqpsk_symbol(symbol, dec->prev_symbol);
			dec->prev_symbol = symbol;

			/* Store symbol */
			if(dec->symbol_index < NICAM_FRAME_SYMS)
			{
				dec->symbols[dec->symbol_index++] = sym;

				/* Check if we have a complete frame */
				if(dec->symbol_index >= NICAM_FRAME_SYMS)
				{
					/* Convert symbols to bytes */
					int byte_idx, bit_idx;
					memset(dec->frame, 0, NICAM_FRAME_BYTES);

					for(byte_idx = 0; byte_idx < NICAM_FRAME_BYTES; byte_idx++)
					{
						for(bit_idx = 0; bit_idx < 4; bit_idx++)
						{
							int sym_idx = byte_idx * 4 + bit_idx;
							if(sym_idx < NICAM_FRAME_SYMS)
							{
								/* Each symbol is 2 bits */
								dec->frame[byte_idx] |= (dec->symbols[sym_idx] << (6 - bit_idx * 2));
							}
						}
					}

					/* Try to decode frame */
					if(_decode_frame(dec) == 0)
					{
						dec->sync_state = 1;
						dec->sync_errors = 0;
					}
					else
					{
						dec->sync_errors++;
						if(dec->sync_errors > 10)
						{
							dec->sync_state = 0;  /* Lost sync */
						}
					}

					/* Reset for next frame */
					dec->symbol_index = 0;
				}
			}
		}
	}

	return 0;
}

/* Get decoded audio */
int nicam_decoder_get_audio(nicam_decoder_t *dec, int16_t *audio_out)
{
	if(!dec->audio_available)
	{
		return 0;
	}

	memcpy(audio_out, dec->audio_out, NICAM_AUDIO_LEN * 2 * sizeof(int16_t));
	dec->audio_available = 0;

	return NICAM_AUDIO_LEN;  /* Number of stereo sample pairs */
}

/* Free resources */
void nicam_decoder_free(nicam_decoder_t *dec)
{
	/* Nothing to free currently */
	memset(dec, 0, sizeof(nicam_decoder_t));
}
