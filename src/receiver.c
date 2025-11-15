/* receiver.c - Analog TV Receiver Implementation */
/*=======================================================================*/
/* Copyright 2025 - Analog TV Receiver Implementation                    */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "receiver.h"
#include "common.h"

/* Helper macros */
#define CLAMP(x, min, max) ((x) < (min) ? (min) : (x) > (max) ? (max) : (x))

/* =======================================================================*/
/* FM Demodulator Implementation                                         */
/* =======================================================================*/

int rx_fm_demod_init(rx_fm_demod_t *demod, int sample_rate, double deviation)
{
	memset(demod, 0, sizeof(rx_fm_demod_t));

	demod->sample_rate = sample_rate;
	demod->deviation = deviation;
	demod->prev_sample.i = 0;
	demod->prev_sample.q = 0;
	demod->prev_angle = 0;
	demod->filter = NULL;

	/* TODO: Implement FIR filtering properly */
	/* For now, we'll skip filtering to get a working prototype */

	return 0;
}

void rx_fm_demod_free(rx_fm_demod_t *demod)
{
	if(demod->filter)
	{
		fir_int16_free(demod->filter);
		demod->filter = NULL;
	}
}

int16_t rx_fm_demod_process(rx_fm_demod_t *demod, int16_t i, int16_t q)
{
	cint32_t sample;
	cint32_t conjugate_mult;
	int32_t angle;
	int32_t delta_angle;
	int16_t output;

	sample.i = i;
	sample.q = q;

	/* Conjugate multiplication: current * conj(previous) */
	/* This gives us the phase difference between samples */
	conjugate_mult.i = sample.i * demod->prev_sample.i + sample.q * demod->prev_sample.q;
	conjugate_mult.q = sample.q * demod->prev_sample.i - sample.i * demod->prev_sample.q;

	/* Calculate angle using atan2 */
	angle = atan2(conjugate_mult.q, conjugate_mult.i) * (INT16_MAX / M_PI);

	/* Calculate change in angle (frequency) */
	delta_angle = angle - demod->prev_angle;

	/* Wrap around */
	if(delta_angle > INT16_MAX) delta_angle -= 2 * INT16_MAX;
	if(delta_angle < -INT16_MAX) delta_angle += 2 * INT16_MAX;

	/* Scale by sample rate / deviation to get baseband signal */
	output = (int16_t)CLAMP(
		(delta_angle * demod->sample_rate) / (2 * M_PI * demod->deviation),
		INT16_MIN,
		INT16_MAX
	);

	/* Apply lowpass filter */
	/* TODO: Apply FIR filter when implemented */

	/* Store for next iteration */
	demod->prev_sample = sample;
	demod->prev_angle = angle;

	return output;
}

/* =======================================================================*/
/* AM Demodulator Implementation                                         */
/* =======================================================================*/

int rx_am_demod_init(rx_am_demod_t *demod, int sample_rate)
{
	memset(demod, 0, sizeof(rx_am_demod_t));

	demod->sample_rate = sample_rate;
	demod->filter = NULL;

	/* TODO: Create lowpass filter for envelope detection */

	return 0;
}

void rx_am_demod_free(rx_am_demod_t *demod)
{
	if(demod->filter)
	{
		fir_int16_free(demod->filter);
		demod->filter = NULL;
	}
}

int16_t rx_am_demod_process(rx_am_demod_t *demod, int16_t i, int16_t q)
{
	int32_t magnitude;
	int16_t output;

	/* Calculate envelope: sqrt(I^2 + Q^2) */
	/* Use approximation: max(|I|, |Q|) + 0.5 * min(|I|, |Q|) */
	int32_t abs_i = abs(i);
	int32_t abs_q = abs(q);

	/* IMPORTANT FIX: If Q is very small compared to I, treat as baseband */
	/* Baseband signals have Q=0, and we need to preserve sign for sync */
	if(abs_q < (abs_i / 20))
	{
		/* This is a baseband signal - return I directly to preserve sign */
		return i;
	}

	/* Standard AM envelope detection for modulated signals */
	if(abs_i > abs_q)
	{
		magnitude = abs_i + (abs_q >> 1);
	}
	else
	{
		magnitude = abs_q + (abs_i >> 1);
	}

	output = (int16_t)CLAMP(magnitude, INT16_MIN, INT16_MAX);

	/* Apply lowpass filter */
	/* TODO: Apply FIR filter when implemented */

	return output;
}

/* =======================================================================*/
/* VSB Demodulator Implementation                                        */
/* =======================================================================*/

int rx_vsb_demod_init(rx_vsb_demod_t *demod, int sample_rate, double carrier_freq)
{
	memset(demod, 0, sizeof(rx_vsb_demod_t));

	demod->sample_rate = sample_rate;
	demod->carrier_freq = carrier_freq;

	/* Initialize carrier oscillator */
	double phase_step = 2.0 * M_PI * carrier_freq / sample_rate;
	demod->carrier_step.i = (int32_t)(cos(phase_step) * INT32_MAX);
	demod->carrier_step.q = (int32_t)(sin(phase_step) * INT32_MAX);
	demod->carrier_phase.i = INT32_MAX;
	demod->carrier_phase.q = 0;
	demod->filter = NULL;

	/* TODO: Create lowpass filter for baseband */

	return 0;
}

void rx_vsb_demod_free(rx_vsb_demod_t *demod)
{
	if(demod->filter)
	{
		fir_int16_free(demod->filter);
		demod->filter = NULL;
	}
}

int16_t rx_vsb_demod_process(rx_vsb_demod_t *demod, int16_t i, int16_t q)
{
	cint32_t sample;
	cint32_t mixed;
	int16_t output;

	sample.i = i;
	sample.q = q;

	/* Mix down to baseband */
	cint32_mul(&mixed, &sample, &demod->carrier_phase);

	/* Advance carrier phase */
	cint32_mul(&demod->carrier_phase, &demod->carrier_phase, &demod->carrier_step);

	/* Take I component (real part) */
	output = (int16_t)(mixed.i >> 16);

	/* Apply lowpass filter */
	/* TODO: Apply FIR filter when implemented */

	return output;
}

/* =======================================================================*/
/* Sync Detection Implementation                                         */
/* =======================================================================*/

int rx_sync_init(rx_sync_t *sync, int sample_rate, int line_length, int frame_lines, int interlaced)
{
	memset(sync, 0, sizeof(rx_sync_t));

	sync->sample_rate = sample_rate;
	sync->line_length = line_length;
	sync->frame_lines = frame_lines;
	sync->interlaced = interlaced;

	/* Set default sync levels (16-bit) */
	sync->sync_level = -INT16_MAX;
	sync->blanking_level = -INT16_MAX / 3;
	sync->black_level = 0;
	sync->white_level = INT16_MAX;

	sync->samples_since_sync = 0;
	sync->current_line = 0;
	sync->current_field = 0;
	sync->in_sync = 0;

	/* AGC */
	sync->agc_level = INT16_MAX / 2;
	sync->agc_accumulator = 0;

	/* Initialize PLL for sync recovery */
	/* Calculate nominal line frequency from sample rate and line length */
	double line_freq = (double)sample_rate / (double)line_length;
	pll_hsync_init(&sync->pll, sample_rate, line_freq);
	sync->use_pll = 1;  /* Enable PLL mode by default */

	return 0;
}

int rx_sync_process(rx_sync_t *sync, int16_t sample, int *line_start, int *field)
{
	*line_start = 0;
	*field = sync->current_field;

	/* Improved AGC - accumulate absolute values */
	sync->agc_accumulator += abs(sample);

	/* Update AGC every 100 samples for faster adaptation */
	if(sync->samples_since_sync % 100 == 0 && sync->agc_accumulator > 0)
	{
		sync->agc_level = sync->agc_accumulator / 100;
		sync->agc_accumulator = 0;

		/* Update sync threshold - sync pulses are most negative */
		/* Set threshold at 60% of peak signal level */
		sync->sync_level = -(sync->agc_level * 6) / 10;
		sync->blanking_level = -sync->agc_level / 4;
	}

	/* Detect sync pulse (signal goes below threshold) */
	if(sample < sync->sync_level && sync->samples_since_sync > sync->line_length / 2)
	{
		*line_start = 1;

		/* Update PLL with detected sync pulse */
		if(sync->use_pll)
		{
			pll_hsync_update(&sync->pll, 1);
			/* Use PLL lock status to determine if we're in sync */
			sync->in_sync = pll_hsync_is_locked(&sync->pll);
		}
		else
		{
			sync->in_sync = 1;
		}

		/* Check if this is a vsync (long sync pulse) */
		/* For now, just count lines */
		sync->current_line++;

		if(sync->current_line >= sync->frame_lines)
		{
			sync->current_line = 0;
			if(sync->interlaced)
			{
				sync->current_field = !sync->current_field;
			}
		}

		sync->samples_since_sync = 0;
	}
	else
	{
		/* Update PLL with no sync pulse */
		if(sync->use_pll)
		{
			pll_hsync_update(&sync->pll, 0);
		}

		sync->samples_since_sync++;

		/* Check if we lost sync */
		if(sync->samples_since_sync > sync->line_length * 2)
		{
			sync->in_sync = 0;
		}
	}

	return sync->in_sync;
}

/* =======================================================================*/
/* PAL Colour Decoder Implementation                                     */
/* =======================================================================*/

int rx_pal_init(rx_pal_decoder_t *pal, int sample_rate, int line_length)
{
	int i;
	double phase;

	memset(pal, 0, sizeof(rx_pal_decoder_t));

	pal->sample_rate = sample_rate;
	pal->line_length = line_length;
	pal->subcarrier_freq = 4433618.75;  /* PAL subcarrier */

	/* Colour burst is at the start of each line, after front porch */
	pal->burst_start = (int)(sample_rate * 5.6e-6);  /* ~5.6us after sync */
	pal->burst_length = (int)(sample_rate * 2.25e-6); /* ~2.25us duration */

	/* Generate subcarrier lookup table (one complete cycle) */
	pal->carrier_lut_size = (int)(sample_rate / pal->subcarrier_freq * 1000);
	pal->carrier_lut = calloc(pal->carrier_lut_size, sizeof(cint32_t));

	if(!pal->carrier_lut)
	{
		return -1;
	}

	for(i = 0; i < pal->carrier_lut_size; i++)
	{
		phase = 2.0 * M_PI * pal->subcarrier_freq * i / sample_rate;
		pal->carrier_lut[i].i = (int32_t)(cos(phase) * INT32_MAX);
		pal->carrier_lut[i].q = (int32_t)(sin(phase) * INT32_MAX);
	}

	pal->carrier_phase = 0;
	pal->v_switch = 0;
	pal->u_filter = NULL;
	pal->v_filter = NULL;

	/* Initialize burst PLL for phase-locked color demodulation */
	pll_burst_init(&pal->burst_pll, sample_rate, pal->subcarrier_freq);
	pal->use_burst_pll = 1;  /* Enable burst PLL by default */

	/* TODO: Create chroma bandpass filters */
	/* U and V are at ±1.3 MHz around the subcarrier */

	return 0;
}

void rx_pal_free(rx_pal_decoder_t *pal)
{
	if(pal->carrier_lut)
	{
		free(pal->carrier_lut);
		pal->carrier_lut = NULL;
	}

	if(pal->u_filter)
	{
		fir_int16_free(pal->u_filter);
		pal->u_filter = NULL;
	}

	if(pal->v_filter)
	{
		fir_int16_free(pal->v_filter);
		pal->v_filter = NULL;
	}
}

void rx_pal_decode_line(rx_pal_decoder_t *pal, int16_t *line, uint32_t *rgb_out, int width)
{
	int x;
	int16_t y, u, v;
	uint8_t r, g, b;
	cint32_t chroma_sample;
	int32_t ref_cos, ref_sin;

	/* Process color burst to lock PLL */
	if(pal->use_burst_pll)
	{
		pll_burst_process(&pal->burst_pll, line, pal->line_length);
	}

	for(x = 0; x < width; x++)
	{
		/* Extract luminance (Y) - this is the baseband video */
		y = line[x];

		/* Get reference from PLL or LUT */
		if(pal->use_burst_pll && pll_burst_is_locked(&pal->burst_pll))
		{
			/* Use PLL-generated reference for better phase accuracy */
			pll_burst_get_reference(&pal->burst_pll, &ref_cos, &ref_sin);
		}
		else
		{
			/* Fall back to LUT */
			ref_cos = pal->carrier_lut[pal->carrier_phase].i;
			ref_sin = pal->carrier_lut[pal->carrier_phase].q;
			pal->carrier_phase = (pal->carrier_phase + 1) % pal->carrier_lut_size;
		}

		/* Extract chrominance by multiplying with subcarrier */
		chroma_sample.i = line[x];
		chroma_sample.q = 0;

		/* Demodulate U (multiply by cos) */
		int64_t u_temp = ((int64_t)chroma_sample.i * ref_cos) >> 32;
		u = (int16_t)CLAMP(u_temp, INT16_MIN, INT16_MAX);

		/* Demodulate V (multiply by sin, with PAL alternation) */
		int64_t v_temp = ((int64_t)chroma_sample.i * ref_sin) >> 32;
		v = (int16_t)(CLAMP(v_temp, INT16_MIN, INT16_MAX) * (pal->v_switch ? -1 : 1));

		/* Convert YUV to RGB */
		yuv_to_rgb(y, u, v, &r, &g, &b);

		/* Pack into 32-bit RGB */
		rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
	}

	/* Toggle V switch for next line (PAL alternation) */
	pal->v_switch = !pal->v_switch;
}

/* =======================================================================*/
/* YUV to RGB Conversion                                                 */
/* =======================================================================*/

void yuv_to_rgb(int16_t y, int16_t u, int16_t v, uint8_t *r, uint8_t *g, uint8_t *b)
{
	int32_t r_tmp, g_tmp, b_tmp;

	/* BT.601 conversion matrix (scaled for 16-bit values) */
	/* R = Y + 1.140 * V */
	/* G = Y - 0.395 * U - 0.581 * V */
	/* B = Y + 2.032 * U */

	r_tmp = y + ((v * 37232) >> 15);  /* 1.140 * 32768 */
	g_tmp = y - ((u * 12943) >> 15) - ((v * 19071) >> 15);
	b_tmp = y + ((u * 66607) >> 15);  /* 2.032 * 32768 */

	/* Scale from 16-bit signed to 8-bit unsigned */
	r_tmp = (r_tmp + INT16_MAX) >> 8;
	g_tmp = (g_tmp + INT16_MAX) >> 8;
	b_tmp = (b_tmp + INT16_MAX) >> 8;

	*r = (uint8_t)CLAMP(r_tmp, 0, 255);
	*g = (uint8_t)CLAMP(g_tmp, 0, 255);
	*b = (uint8_t)CLAMP(b_tmp, 0, 255);
}

/* =======================================================================*/
/* NTSC Colour Decoder Implementation                                    */
/* =======================================================================*/

int rx_ntsc_init(rx_ntsc_decoder_t *ntsc, int sample_rate, int line_length)
{
	int i;
	double phase;

	memset(ntsc, 0, sizeof(rx_ntsc_decoder_t));

	ntsc->sample_rate = sample_rate;
	ntsc->line_length = line_length;
	ntsc->subcarrier_freq = 3579545.0;  /* NTSC subcarrier */

	/* Colour burst parameters */
	ntsc->burst_start = (int)(sample_rate * 5.6e-6);
	ntsc->burst_length = (int)(sample_rate * 2.5e-6);

	/* Generate subcarrier lookup table */
	ntsc->carrier_lut_size = (int)(sample_rate / ntsc->subcarrier_freq * 1000);
	ntsc->carrier_lut = calloc(ntsc->carrier_lut_size, sizeof(cint32_t));

	if(!ntsc->carrier_lut)
	{
		return -1;
	}

	for(i = 0; i < ntsc->carrier_lut_size; i++)
	{
		phase = 2.0 * M_PI * ntsc->subcarrier_freq * i / sample_rate;
		ntsc->carrier_lut[i].i = (int32_t)(cos(phase) * INT32_MAX);
		ntsc->carrier_lut[i].q = (int32_t)(sin(phase) * INT32_MAX);
	}

	ntsc->carrier_phase = 0;
	ntsc->i_filter = NULL;
	ntsc->q_filter = NULL;

	/* Initialize burst PLL for phase-locked color demodulation */
	pll_burst_init(&ntsc->burst_pll, sample_rate, ntsc->subcarrier_freq);
	ntsc->use_burst_pll = 1;  /* Enable burst PLL by default */

	/* TODO: Create chroma filters for I and Q */

	return 0;
}

void rx_ntsc_free(rx_ntsc_decoder_t *ntsc)
{
	if(ntsc->carrier_lut)
	{
		free(ntsc->carrier_lut);
		ntsc->carrier_lut = NULL;
	}

	if(ntsc->i_filter)
	{
		fir_int16_free(ntsc->i_filter);
		ntsc->i_filter = NULL;
	}

	if(ntsc->q_filter)
	{
		fir_int16_free(ntsc->q_filter);
		ntsc->q_filter = NULL;
	}
}

void rx_ntsc_decode_line(rx_ntsc_decoder_t *ntsc, int16_t *line, uint32_t *rgb_out, int width)
{
	int x;
	int16_t y, i, q, u, v;
	uint8_t r, g, b;
	cint32_t chroma_sample;
	int32_t ref_cos, ref_sin;

	/* Process color burst to lock PLL */
	if(ntsc->use_burst_pll)
	{
		pll_burst_process(&ntsc->burst_pll, line, ntsc->line_length);
	}

	for(x = 0; x < width; x++)
	{
		y = line[x];

		/* Get reference from PLL or LUT */
		if(ntsc->use_burst_pll && pll_burst_is_locked(&ntsc->burst_pll))
		{
			/* Use PLL-generated reference for better phase accuracy */
			pll_burst_get_reference(&ntsc->burst_pll, &ref_cos, &ref_sin);
		}
		else
		{
			/* Fall back to LUT */
			ref_cos = ntsc->carrier_lut[ntsc->carrier_phase].i;
			ref_sin = ntsc->carrier_lut[ntsc->carrier_phase].q;
			ntsc->carrier_phase = (ntsc->carrier_phase + 1) % ntsc->carrier_lut_size;
		}

		chroma_sample.i = line[x];
		chroma_sample.q = 0;

		/* Demodulate I and Q components using PLL reference */
		int64_t i_temp = ((int64_t)chroma_sample.i * ref_cos) >> 32;
		int64_t q_temp = ((int64_t)chroma_sample.i * ref_sin) >> 32;
		i = (int16_t)CLAMP(i_temp, INT16_MIN, INT16_MAX);
		q = (int16_t)CLAMP(q_temp, INT16_MIN, INT16_MAX);

		/* Convert I/Q to U/V (simplified) */
		u = (i + q) / 2;
		v = (i - q) / 2;

		yuv_to_rgb(y, u, v, &r, &g, &b);
		rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
	}
}

/* =======================================================================*/
/* SECAM Colour Decoder Implementation                                   */
/* =======================================================================*/

int rx_secam_init(rx_secam_decoder_t *secam, int sample_rate, int line_length)
{
	memset(secam, 0, sizeof(rx_secam_decoder_t));

	secam->sample_rate = sample_rate;
	secam->line_length = line_length;
	secam->dr_freq = 4406250.0;  /* SECAM R-Y */
	secam->db_freq = 4250000.0;  /* SECAM B-Y */
	secam->use_dr = 0;

	/* Initialize FM demodulators for colour subcarriers */
	if(rx_fm_demod_init(&secam->dr_demod, sample_rate, 280000.0) != 0)
	{
		return -1;
	}

	if(rx_fm_demod_init(&secam->db_demod, sample_rate, 230000.0) != 0)
	{
		rx_fm_demod_free(&secam->dr_demod);
		return -1;
	}

	return 0;
}

void rx_secam_free(rx_secam_decoder_t *secam)
{
	rx_fm_demod_free(&secam->dr_demod);
	rx_fm_demod_free(&secam->db_demod);
}

void rx_secam_decode_line(rx_secam_decoder_t *secam, int16_t *line, uint32_t *rgb_out, int width)
{
	int x;
	int16_t y, u, v;
	uint8_t r, g, b;
	int16_t chroma;

	for(x = 0; x < width; x++)
	{
		y = line[x];

		/* SECAM uses FM modulation for colour on alternating lines */
		if(secam->use_dr)
		{
			/* Demodulate Dr (R-Y) */
			chroma = rx_fm_demod_process(&secam->dr_demod, line[x], 0);
			v = chroma;
			u = 0;  /* No U on this line */
		}
		else
		{
			/* Demodulate Db (B-Y) */
			chroma = rx_fm_demod_process(&secam->db_demod, line[x], 0);
			u = chroma;
			v = 0;  /* No V on this line */
		}

		yuv_to_rgb(y, u, v, &r, &g, &b);
		rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
	}

	/* Alternate between Dr and Db for next line */
	secam->use_dr = !secam->use_dr;
}

/* =======================================================================*/
/* Audio Demodulator Implementation                                      */
/* =======================================================================*/

int rx_audio_init(rx_audio_demod_t *audio, int sample_rate, double carrier_freq, int output_rate)
{
	memset(audio, 0, sizeof(rx_audio_demod_t));

	audio->sample_rate = sample_rate;
	audio->carrier_freq = carrier_freq;
	audio->output_rate = output_rate;

	/* Initialize FM demodulator for audio (typically 50kHz deviation) */
	if(rx_fm_demod_init(&audio->fm_demod, sample_rate, 50000.0) != 0)
	{
		return -1;
	}

	audio->deemph_filter = NULL;
	audio->resampler = NULL;

	/* TODO: Create de-emphasis filter and resampler */

	return 0;
}

void rx_audio_free(rx_audio_demod_t *audio)
{
	rx_fm_demod_free(&audio->fm_demod);

	if(audio->deemph_filter)
	{
		fir_int16_free(audio->deemph_filter);
		audio->deemph_filter = NULL;
	}

	if(audio->resampler)
	{
		fir_int16_free(audio->resampler);
		audio->resampler = NULL;
	}
}

int16_t rx_audio_process(rx_audio_demod_t *audio, int16_t i, int16_t q)
{
	int16_t demod;

	/* FM demodulate */
	demod = rx_fm_demod_process(&audio->fm_demod, i, q);

	/* TODO: Apply de-emphasis and resampling */

	return demod;
}

/* =======================================================================*/
/* Main Receiver Initialization                                          */
/* =======================================================================*/

int rx_init(rx_t *rx, rx_config_t *conf)
{
	memset(rx, 0, sizeof(rx_t));
	memcpy(&rx->conf, conf, sizeof(rx_config_t));

	/* Calculate line length in samples */
	int line_length = (int)(conf->sample_rate / (conf->frame_rate.num * conf->lines / conf->frame_rate.den));

	/* Initialize appropriate demodulator */
	switch(conf->demod_type)
	{
		case RX_DEMOD_FM:
			if(rx_fm_demod_init(&rx->fm_demod, conf->sample_rate, 10000000.0) != 0)
			{
				fprintf(stderr, "Failed to initialize FM demodulator\n");
				return -1;
			}
			break;

		case RX_DEMOD_AM:
			if(rx_am_demod_init(&rx->am_demod, conf->sample_rate) != 0)
			{
				fprintf(stderr, "Failed to initialize AM demodulator\n");
				return -1;
			}
			break;

		case RX_DEMOD_VSB:
			if(rx_vsb_demod_init(&rx->vsb_demod, conf->sample_rate, conf->if_frequency) != 0)
			{
				fprintf(stderr, "Failed to initialize VSB demodulator\n");
				return -1;
			}
			break;
	}

	/* Initialize sync detector */
	if(rx_sync_init(&rx->sync, conf->sample_rate, line_length, conf->lines, conf->interlaced) != 0)
	{
		fprintf(stderr, "Failed to initialize sync detector\n");
		rx_free(rx);
		return -1;
	}

	/* Initialize colour decoder */
	switch(conf->colour_type)
	{
		case RX_COLOUR_PAL:
			if(rx_pal_init(&rx->pal_decoder, conf->sample_rate, line_length) != 0)
			{
				fprintf(stderr, "Failed to initialize PAL decoder\n");
				rx_free(rx);
				return -1;
			}
			break;

		case RX_COLOUR_NTSC:
			if(rx_ntsc_init(&rx->ntsc_decoder, conf->sample_rate, line_length) != 0)
			{
				fprintf(stderr, "Failed to initialize NTSC decoder\n");
				rx_free(rx);
				return -1;
			}
			break;

		case RX_COLOUR_SECAM:
			if(rx_secam_init(&rx->secam_decoder, conf->sample_rate, line_length) != 0)
			{
				fprintf(stderr, "Failed to initialize SECAM decoder\n");
				rx_free(rx);
				return -1;
			}
			break;

		case RX_COLOUR_NONE:
		default:
			break;
	}

	/* Initialize audio decoder if enabled */
	if(conf->enable_audio && conf->audio_carrier > 0)
	{
		if(rx_audio_init(&rx->audio_demod, conf->sample_rate, conf->audio_carrier, conf->audio_output_rate) != 0)
		{
			fprintf(stderr, "Failed to initialize audio decoder\n");
			rx_free(rx);
			return -1;
		}
	}

	/* Allocate line buffer */
	rx->line_buffer_size = line_length * 2;  /* Safety margin */
	rx->line_buffer = calloc(rx->line_buffer_size, sizeof(int16_t));
	if(!rx->line_buffer)
	{
		fprintf(stderr, "Failed to allocate line buffer\n");
		rx_free(rx);
		return -1;
	}

	/* Allocate framebuffer */
	/* Assume active video is about 52us per line at PAL timing */
	rx->frame_width = 720;  /* Standard definition */
	rx->frame_height = (conf->interlaced ? conf->lines / 2 : conf->lines);

	rx->framebuffer = calloc(rx->frame_width * rx->frame_height, sizeof(uint32_t));
	if(!rx->framebuffer)
	{
		fprintf(stderr, "Failed to allocate framebuffer\n");
		rx_free(rx);
		return -1;
	}

	/* Allocate audio buffer */
	if(conf->enable_audio)
	{
		rx->audio_buffer_size = conf->audio_output_rate;  /* 1 second */
		rx->audio_buffer = calloc(rx->audio_buffer_size, sizeof(int16_t));
		if(!rx->audio_buffer)
		{
			fprintf(stderr, "Failed to allocate audio buffer\n");
			rx_free(rx);
			return -1;
		}
	}

	printf("Receiver initialized:\n");
	printf("  Sample rate: %d Hz\n", conf->sample_rate);
	printf("  Video standard: %d lines, %s\n", conf->lines, conf->interlaced ? "interlaced" : "progressive");
	printf("  Colour system: %s\n",
		conf->colour_type == RX_COLOUR_PAL ? "PAL" :
		conf->colour_type == RX_COLOUR_NTSC ? "NTSC" :
		conf->colour_type == RX_COLOUR_SECAM ? "SECAM" : "Monochrome");
	printf("  Demodulator: %s\n",
		conf->demod_type == RX_DEMOD_FM ? "FM" :
		conf->demod_type == RX_DEMOD_AM ? "AM" : "VSB");

	return 0;
}

void rx_free(rx_t *rx)
{
	rx_fm_demod_free(&rx->fm_demod);
	rx_am_demod_free(&rx->am_demod);
	rx_vsb_demod_free(&rx->vsb_demod);

	rx_pal_free(&rx->pal_decoder);
	rx_ntsc_free(&rx->ntsc_decoder);
	rx_secam_free(&rx->secam_decoder);

	rx_audio_free(&rx->audio_demod);

	if(rx->line_buffer)
	{
		free(rx->line_buffer);
		rx->line_buffer = NULL;
	}

	if(rx->framebuffer)
	{
		free(rx->framebuffer);
		rx->framebuffer = NULL;
	}

	if(rx->audio_buffer)
	{
		free(rx->audio_buffer);
		rx->audio_buffer = NULL;
	}
}

/* =======================================================================*/
/* Main Processing Function                                              */
/* =======================================================================*/

int rx_process_samples(rx_t *rx, int16_t *samples, int count)
{
	int i;
	int16_t baseband;
	int line_start;
	int field;

	for(i = 0; i < count; i += 2)
	{
		int16_t iq_i = samples[i];
		int16_t iq_q = samples[i + 1];

		/* Demodulate to baseband */
		switch(rx->conf.demod_type)
		{
			case RX_DEMOD_FM:
				baseband = rx_fm_demod_process(&rx->fm_demod, iq_i, iq_q);
				break;
			case RX_DEMOD_AM:
				baseband = rx_am_demod_process(&rx->am_demod, iq_i, iq_q);
				break;
			case RX_DEMOD_VSB:
				baseband = rx_vsb_demod_process(&rx->vsb_demod, iq_i, iq_q);
				break;
			default:
				baseband = iq_i;
		}

		/* Detect sync and line timing */
		rx_sync_process(&rx->sync, baseband, &line_start, &field);

		/* Add sample to line buffer */
		if(rx->line_buffer_pos < rx->line_buffer_size)
		{
			rx->line_buffer[rx->line_buffer_pos++] = baseband;
		}

		/* When we detect a new line, process the previous line */
		if(line_start && rx->line_buffer_pos > 0)
		{
			int line_num = rx->sync.current_line;

			/* Only process active video lines */
			if(line_num >= 23 && line_num < rx->frame_height + 23)
			{
				int fb_line = line_num - 23;
				uint32_t *fb_ptr = &rx->framebuffer[fb_line * rx->frame_width];

				/* Calculate where active video starts in line buffer */
				/* Skip sync pulse (~75 samples) and back porch (~82 samples) */
				int active_start = 157;  /* ~10% of 1024-sample line */
				int active_width = rx->frame_width;

				/* Make sure we don't go past the line buffer */
				if(active_start + active_width > rx->line_buffer_pos)
				{
					active_width = rx->line_buffer_pos - active_start;
				}

				/* Decode colour from active video portion only */
				switch(rx->conf.colour_type)
				{
					case RX_COLOUR_PAL:
						rx_pal_decode_line(&rx->pal_decoder, rx->line_buffer + active_start, fb_ptr, active_width);
						break;
					case RX_COLOUR_NTSC:
						rx_ntsc_decode_line(&rx->ntsc_decoder, rx->line_buffer + active_start, fb_ptr, active_width);
						break;
					case RX_COLOUR_SECAM:
						rx_secam_decode_line(&rx->secam_decoder, rx->line_buffer + active_start, fb_ptr, active_width);
						break;
					case RX_COLOUR_NONE:
					default:
						/* Monochrome - convert active video portion only */
						for(int x = 0; x < active_width && x < rx->frame_width; x++)
						{
							int16_t y = rx->line_buffer[active_start + x];

							/* Map video levels to grayscale (ITU-R BT.601) */
							/* Sync level (-32000) should be black (16) */
							/* Black level (0) should be dark (16) */
							/* White level (+32000) should be white (235) */
							/* Map the range -32768..+32767 to 16..235 for proper video levels */

							/* First, clamp to active video range */
							int32_t clamped = CLAMP(y, -32768, 32767);

							/* Map to 16-235 range (video levels) */
							/* Formula: output = 16 + (input + 32768) * (235 - 16) / 65535 */
							int32_t scaled = 16 + ((clamped + 32768) * 219) / 65535;
							uint8_t gray = (uint8_t)CLAMP(scaled, 0, 255);

							fb_ptr[x] = (0xFF << 24) | (gray << 16) | (gray << 8) | gray;
						}
						break;
				}
			}

			/* Reset line buffer */
			rx->line_buffer_pos = 0;

			/* Count frames */
			if(line_num == 0)
			{
				rx->frames_decoded++;
			}
		}

		/* Process audio if enabled */
		if(rx->conf.enable_audio && rx->audio_buffer_pos < rx->audio_buffer_size)
		{
			int16_t audio_sample = rx_audio_process(&rx->audio_demod, iq_i, iq_q);
			rx->audio_buffer[rx->audio_buffer_pos++] = audio_sample;
		}

		rx->samples_processed++;
	}

	return 0;
}

int rx_get_frame(rx_t *rx, uint32_t **framebuffer, int *width, int *height)
{
	*framebuffer = rx->framebuffer;
	*width = rx->frame_width;
	*height = rx->frame_height;

	return rx->frames_decoded > 0 ? 1 : 0;
}

int rx_get_audio(rx_t *rx, int16_t **audio, int *count)
{
	*audio = rx->audio_buffer;
	*count = rx->audio_buffer_pos;

	/* Reset buffer position after retrieval */
	rx->audio_buffer_pos = 0;

	return *count;
}
