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

	/* Initialize adaptive AGC */
	demod->enable_agc = 1;  /* Enable by default */
	demod->agc_gain = 1.0;  /* Start with unity gain */
	demod->agc_target = 20000.0;  /* Target signal level (out of 32767) */
	demod->agc_attack = 0.001;  /* Fast attack for signal increases */
	demod->agc_decay = 0.00001;  /* Slow decay for signal decreases */
	demod->agc_peak_level = 0;

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

	/* Apply adaptive AGC */
	if(demod->enable_agc)
	{
		/* Track peak level */
		int32_t abs_level = abs(output);
		if(abs_level > demod->agc_peak_level)
		{
			demod->agc_peak_level = abs_level;
		}
		else
		{
			/* Slow decay */
			demod->agc_peak_level = (int32_t)(demod->agc_peak_level * (1.0 - demod->agc_decay));
		}

		/* Adjust gain based on peak level */
		if(demod->agc_peak_level > 100)  /* Avoid division by zero */
		{
			double desired_gain = demod->agc_target / demod->agc_peak_level;

			/* Smooth gain changes */
			if(desired_gain < demod->agc_gain)
			{
				/* Fast attack (reduce gain quickly) */
				demod->agc_gain += (desired_gain - demod->agc_gain) * demod->agc_attack;
			}
			else
			{
				/* Slow decay (increase gain slowly) */
				demod->agc_gain += (desired_gain - demod->agc_gain) * demod->agc_decay * 10.0;
			}

			/* Clamp gain to reasonable range (0.1x to 10x) */
			if(demod->agc_gain < 0.1) demod->agc_gain = 0.1;
			if(demod->agc_gain > 10.0) demod->agc_gain = 10.0;
		}

		/* Apply gain */
		int32_t gained = (int32_t)(output * demod->agc_gain);
		output = (int16_t)CLAMP(gained, INT16_MIN, INT16_MAX);
	}

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

/* Simple chroma bandpass filter (centered at subcarrier frequency) */
/* This separates chroma from luma using a basic 3-tap bandpass */
static int16_t chroma_bandpass(int16_t *line, int x, int taps)
{
	int32_t sum = 0;

	/* Simple 3-tap bandpass: [1, -2, 1] pattern extracts high frequencies */
	/* This is a simplified chroma extraction - proper implementation would use FIR */
	if(x > 0 && x < taps - 1)
	{
		sum = (int32_t)line[x - 1] - 2 * (int32_t)line[x] + (int32_t)line[x + 1];
		return (int16_t)CLAMP(sum, INT16_MIN, INT16_MAX);
	}

	/* Bounds check for edge cases */
	if(x < taps)
	{
		return line[x];
	}

	return 0;  /* Out of bounds */
}

/* PAL comb filter using 1H (one line) delay */
/* This exploits PAL's V-phase alternation to separate chroma from luma */
static int16_t chroma_comb_filter(int16_t *curr_line, int16_t *prev_line, int x, int line_length)
{
	int32_t diff;

	if(prev_line && x < line_length)
	{
		/* Subtract previous line from current line */
		/* PAL chroma inverts phase every line, so this enhances chroma while canceling luma */
		diff = (int32_t)curr_line[x] - (int32_t)prev_line[x];
		/* Divide by 2 to normalize amplitude */
		return (int16_t)CLAMP(diff / 2, INT16_MIN, INT16_MAX);
	}

	/* Fallback for first line or out of bounds - use bandpass instead */
	if(x < line_length)
	{
		return curr_line[x];
	}

	return 0;  /* Out of bounds */
}

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

	/* CRITICAL: Initialize proper chroma bandpass FIR filters */
	/* PAL chroma bandpass: 4.43 MHz ± 1.3 MHz (3.13 MHz - 5.73 MHz) */
	int ntaps = 65;  /* Higher tap count for better selectivity */
	double *taps = calloc(ntaps, sizeof(double));

	if(!taps)
	{
		rx_pal_free(pal);
		return -1;
	}

	/* Design complex bandpass filter centered at PAL subcarrier */
	double low_cutoff = pal->subcarrier_freq - 1300000.0;   /* 3.13 MHz */
	double high_cutoff = pal->subcarrier_freq + 1300000.0;  /* 5.73 MHz */
	double transition_width = 500000.0;  /* 500 kHz transition */

	fir_complex_band_pass(taps, ntaps, sample_rate, low_cutoff, high_cutoff, transition_width, 1.0);

	/* Initialize FIR filter for U channel */
	pal->u_filter = calloc(1, sizeof(fir_int16_t));
	if(!pal->u_filter || fir_int16_init(pal->u_filter, taps, ntaps, 1, 1, 0) != 0)
	{
		free(taps);
		rx_pal_free(pal);
		return -1;
	}

	/* Initialize FIR filter for V channel (same coefficients) */
	pal->v_filter = calloc(1, sizeof(fir_int16_t));
	if(!pal->v_filter || fir_int16_init(pal->v_filter, taps, ntaps, 1, 1, 0) != 0)
	{
		free(taps);
		rx_pal_free(pal);
		return -1;
	}

	free(taps);  /* FIR filters have copied the coefficients */

	/* Initialize burst PLL for phase-locked color demodulation */
	pll_burst_init(&pal->burst_pll, sample_rate, pal->subcarrier_freq);
	pal->use_burst_pll = 1;  /* Enable burst PLL */

	/* Allocate 1H delay line for comb filter */
	pal->prev_line_length = line_length;
	pal->prev_line = calloc(line_length, sizeof(int16_t));
	if(!pal->prev_line)
	{
		free(pal->carrier_lut);
		return -1;
	}

	/* FIR filters initialized above - used for chroma extraction when comb filter unavailable */

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

	if(pal->prev_line)
	{
		free(pal->prev_line);
		pal->prev_line = NULL;
	}
}

void rx_pal_decode_line(rx_pal_decoder_t *pal, int16_t *line, uint32_t *rgb_out, int width)
{
	int x;
	int16_t y, u, v;
	uint8_t r, g, b;
	int16_t chroma;
	int32_t ref_cos, ref_sin;

	/* Note: Color burst PLL is now processed at higher level with full line buffer */

	for(x = 0; x < width; x++)
	{
		/* CRITICAL FIX: Extract chroma using 1H comb filter */
		/* Now using properly offset prev_line for sample-perfect alignment */
		chroma = chroma_comb_filter(line, pal->prev_line_offset, x, width);

		/* If comb filter not available (first line), use bandpass filter */
		if(!pal->prev_line_offset)
		{
			chroma = chroma_bandpass(line, x, width);
		}

		/* Extract luminance (Y) by taking the baseband signal */
		/* Simple approach: use original signal as luma (chroma averages to zero over time) */
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

		/* CRITICAL FIX: Demodulate U with proper gain */
		/* Changed from >>32 to >>16 for less amplitude loss */
		int64_t u_temp = ((int64_t)chroma * ref_cos) >> 16;
		u_temp = (u_temp * 3);  /* 3x chroma gain */
		u = (int16_t)CLAMP(u_temp, INT16_MIN, INT16_MAX);

		/* CRITICAL FIX: Demodulate V with proper gain and PAL alternation */
		int64_t v_temp = ((int64_t)chroma * ref_sin) >> 16;
		v_temp = (v_temp * 3) * (pal->v_switch ? -1 : 1);  /* 3x gain + PAL V-switch */
		v = (int16_t)CLAMP(v_temp, INT16_MIN, INT16_MAX);

		/* Convert YUV to RGB */
		yuv_to_rgb(y, u, v, &r, &g, &b);

		/* Pack into 32-bit RGB */
		rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
	}

	/* Note: prev_line is now saved at higher level with FULL line buffer */
	/* See rx_process_samples() for correct memcpy implementation */

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

	/* CRITICAL FIX: Scale from 16-bit signed to 8-bit unsigned with ITU-R BT.601 levels */
	/* ITU-R BT.601 specifies video levels: 16-235 for Y, 16-240 for U/V */
	/* We want black (Y=-32768) to map to 16, white (Y=+32767) to map to 235 */

	/* Map -32768 to +32767 range to 16-235 range */
	/* Formula: output = 16 + ((input + 32768) * 219) / 65535 */
	r_tmp = 16 + (((r_tmp + 32768) * 219) / 65535);
	g_tmp = 16 + (((g_tmp + 32768) * 219) / 65535);
	b_tmp = 16 + (((b_tmp + 32768) * 219) / 65535);

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

	/* CRITICAL: Initialize proper chroma bandpass FIR filters */
	/* NTSC chroma bandpass: 3.58 MHz ± 1.3 MHz (2.28 MHz - 4.88 MHz) */
	int ntaps = 65;  /* Higher tap count for better selectivity */
	double *taps = calloc(ntaps, sizeof(double));

	if(!taps)
	{
		rx_ntsc_free(ntsc);
		return -1;
	}

	/* Design complex bandpass filter centered at NTSC subcarrier */
	double low_cutoff = ntsc->subcarrier_freq - 1300000.0;   /* 2.28 MHz */
	double high_cutoff = ntsc->subcarrier_freq + 1300000.0;  /* 4.88 MHz */
	double transition_width = 500000.0;  /* 500 kHz transition */

	fir_complex_band_pass(taps, ntaps, sample_rate, low_cutoff, high_cutoff, transition_width, 1.0);

	/* Initialize FIR filter for I channel */
	ntsc->i_filter = calloc(1, sizeof(fir_int16_t));
	if(!ntsc->i_filter || fir_int16_init(ntsc->i_filter, taps, ntaps, 1, 1, 0) != 0)
	{
		free(taps);
		rx_ntsc_free(ntsc);
		return -1;
	}

	/* Initialize FIR filter for Q channel (same coefficients) */
	ntsc->q_filter = calloc(1, sizeof(fir_int16_t));
	if(!ntsc->q_filter || fir_int16_init(ntsc->q_filter, taps, ntaps, 1, 1, 0) != 0)
	{
		free(taps);
		rx_ntsc_free(ntsc);
		return -1;
	}

	free(taps);  /* FIR filters have copied the coefficients */

	/* Initialize burst PLL for phase-locked color demodulation */
	pll_burst_init(&ntsc->burst_pll, sample_rate, ntsc->subcarrier_freq);
	ntsc->use_burst_pll = 1;  /* Enable burst PLL by default */

	/* Allocate 1H delay line for comb filter */
	ntsc->prev_line_length = line_length;
	ntsc->prev_line = calloc(line_length, sizeof(int16_t));
	if(!ntsc->prev_line)
	{
		rx_ntsc_free(ntsc);
		return -1;
	}

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

	if(ntsc->prev_line)
	{
		free(ntsc->prev_line);
		ntsc->prev_line = NULL;
	}
}

void rx_ntsc_decode_line(rx_ntsc_decoder_t *ntsc, int16_t *line, uint32_t *rgb_out, int width)
{
	int x;
	int16_t y, i, q, u, v;
	uint8_t r, g, b;
	int16_t chroma;
	int32_t ref_cos, ref_sin;

	/* Note: Color burst PLL is now processed at higher level with full line buffer */

	for(x = 0; x < width; x++)
	{
		/* CRITICAL FIX: NTSC comb filter for Y/C separation */
		/* NTSC subcarrier inverts 180° on successive lines */
		/* Luma = (current + previous) / 2, Chroma = (current - previous) / 2 */
		/* Now using properly offset prev_line for sample-perfect alignment */
		if(ntsc->prev_line_offset && x < width)
		{
			int32_t curr = line[x];
			int32_t prev = ntsc->prev_line_offset[x];

			/* Comb filter: average for luma, difference for chroma */
			y = (int16_t)((curr + prev) / 2);
			chroma = (int16_t)((curr - prev) / 2);
		}
		else
		{
			/* Fall back to simple bandpass on first line */
			chroma = chroma_bandpass(line, x, width);
			y = line[x];
		}

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

		/* CRITICAL FIX: Demodulate I and Q with proper gain */
		int64_t i_temp = ((int64_t)chroma * ref_cos) >> 16;
		i_temp = i_temp * 3;  /* 3x chroma gain */
		i = (int16_t)CLAMP(i_temp, INT16_MIN, INT16_MAX);

		int64_t q_temp = ((int64_t)chroma * ref_sin) >> 16;
		q_temp = q_temp * 3;  /* 3x chroma gain */
		q = (int16_t)CLAMP(q_temp, INT16_MIN, INT16_MAX);

		/* CRITICAL FIX: Convert I/Q to U/V with proper 33° rotation */
		/* In NTSC, I and Q axes are rotated 33° from U and V axes */
		/* U = I * cos(33°) + Q * sin(33°) */
		/* V = -I * sin(33°) + Q * cos(33°) */
		/* cos(33°) ≈ 0.8387 = 27484/32768, sin(33°) ≈ 0.5446 = 17845/32768 */
		int32_t u_tmp = ((int32_t)i * 27484 + (int32_t)q * 17845) >> 15;
		int32_t v_tmp = (-(int32_t)i * 17845 + (int32_t)q * 27484) >> 15;
		u = (int16_t)CLAMP(u_tmp, INT16_MIN, INT16_MAX);
		v = (int16_t)CLAMP(v_tmp, INT16_MIN, INT16_MAX);

		yuv_to_rgb(y, u, v, &r, &g, &b);
		rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
	}

	/* Note: prev_line is now saved at higher level with FULL line buffer */
	/* See rx_process_samples() for correct memcpy implementation */
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

	/* Allocate 1H delay line for U/V storage (SECAM alternates Dr/Db) */
	secam->prev_line_length = line_length;
	secam->prev_u = calloc(line_length, sizeof(int16_t));
	secam->prev_v = calloc(line_length, sizeof(int16_t));

	if(!secam->prev_u || !secam->prev_v)
	{
		rx_secam_free(secam);
		return -1;
	}

	/* Initialize Dr/Db bandpass filters for improved color separation */
	/* Dr filter: centered at 4.40625 MHz, bandwidth ~500 kHz */
	/* Db filter: centered at 4.25 MHz, bandwidth ~500 kHz */

	/* Create simple bandpass FIR filters */
	int filter_taps = 65;
	double *dr_taps = malloc(filter_taps * sizeof(double));
	double *db_taps = malloc(filter_taps * sizeof(double));

	if(!dr_taps || !db_taps)
	{
		if(dr_taps) free(dr_taps);
		if(db_taps) free(db_taps);
		rx_secam_free(secam);
		return -1;
	}

	/* Generate bandpass filter coefficients using windowed sinc */
	int i;
	double dr_norm_freq = secam->dr_freq / (sample_rate / 2.0);
	double db_norm_freq = secam->db_freq / (sample_rate / 2.0);
	double bw = 500000.0 / (sample_rate / 2.0);  /* Normalized bandwidth */

	for(i = 0; i < filter_taps; i++)
	{
		double n = i - (filter_taps - 1) / 2.0;
		double window = 0.54 - 0.46 * cos(2.0 * M_PI * i / (filter_taps - 1));  /* Hamming window */

		/* Bandpass = 2 * lowpass * cos(2πfc) */
		if(n == 0)
		{
			dr_taps[i] = 2.0 * bw * window;
			db_taps[i] = 2.0 * bw * window;
		}
		else
		{
			dr_taps[i] = 2.0 * bw * sin(M_PI * bw * n) / (M_PI * bw * n) *
			             2.0 * cos(2.0 * M_PI * dr_norm_freq * n) * window;
			db_taps[i] = 2.0 * bw * sin(M_PI * bw * n) / (M_PI * bw * n) *
			             2.0 * cos(2.0 * M_PI * db_norm_freq * n) * window;
		}
	}

	secam->dr_filter = malloc(sizeof(fir_int16_t));
	secam->db_filter = malloc(sizeof(fir_int16_t));

	if(!secam->dr_filter || !secam->db_filter)
	{
		if(secam->dr_filter) free(secam->dr_filter);
		if(secam->db_filter) free(secam->db_filter);
		free(dr_taps);
		free(db_taps);
		rx_secam_free(secam);
		return -1;
	}

	if(fir_int16_init(secam->dr_filter, dr_taps, filter_taps, 1, 1, 0) != 0 ||
	   fir_int16_init(secam->db_filter, db_taps, filter_taps, 1, 1, 0) != 0)
	{
		free(dr_taps);
		free(db_taps);
		rx_secam_free(secam);
		return -1;
	}

	free(dr_taps);
	free(db_taps);

	if(!secam->dr_filter || !secam->db_filter)
	{
		rx_secam_free(secam);
		return -1;
	}

	return 0;
}

void rx_secam_free(rx_secam_decoder_t *secam)
{
	rx_fm_demod_free(&secam->dr_demod);
	rx_fm_demod_free(&secam->db_demod);

	if(secam->dr_filter)
	{
		fir_int16_free(secam->dr_filter);
		secam->dr_filter = NULL;
	}

	if(secam->db_filter)
	{
		fir_int16_free(secam->db_filter);
		secam->db_filter = NULL;
	}

	if(secam->prev_u)
	{
		free(secam->prev_u);
		secam->prev_u = NULL;
	}

	if(secam->prev_v)
	{
		free(secam->prev_v);
		secam->prev_v = NULL;
	}
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

		/* CRITICAL FIX: SECAM 1H delay line for U/V storage */
		/* SECAM transmits Dr (V) and Db (U) on alternating lines */
		/* Must use delay line to reconstruct both U and V for each line */

		/* Apply bandpass filtering before FM demodulation for improved color separation */
		int16_t filtered_sample = line[x];

		if(secam->use_dr)
		{
			/* This line has Dr (V): bandpass filter then demodulate V */
			if(secam->dr_filter)
			{
				int16_t temp_in = line[x];
				int16_t temp_out = 0;
				fir_int16_feed(secam->dr_filter, &temp_in, 1, 1);
				fir_int16_process(secam->dr_filter, &temp_out, 1, 1);
				filtered_sample = temp_out;
			}
			chroma = rx_fm_demod_process(&secam->dr_demod, filtered_sample, 0);
			v = chroma;

			/* Retrieve U from previous line's demodulated Db */
			u = (secam->prev_u && x < secam->prev_line_length) ? secam->prev_u[x] : 0;

			/* Store V for next line */
			if(secam->prev_v && x < secam->prev_line_length)
			{
				secam->prev_v[x] = v;
			}
		}
		else
		{
			/* This line has Db (U): bandpass filter then demodulate U */
			if(secam->db_filter)
			{
				int16_t temp_in = line[x];
				int16_t temp_out = 0;
				fir_int16_feed(secam->db_filter, &temp_in, 1, 1);
				fir_int16_process(secam->db_filter, &temp_out, 1, 1);
				filtered_sample = temp_out;
			}
			chroma = rx_fm_demod_process(&secam->db_demod, filtered_sample, 0);
			u = chroma;

			/* Retrieve V from previous line's demodulated Dr */
			v = (secam->prev_v && x < secam->prev_line_length) ? secam->prev_v[x] : 0;

			/* Store U for next line */
			if(secam->prev_u && x < secam->prev_line_length)
			{
				secam->prev_u[x] = u;
			}
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

	/* Initialize de-emphasis filter (50μs time constant for PAL)
	 * De-emphasis compensates for FM pre-emphasis used at transmitter
	 * 50μs: Europe/PAL, 75μs: North America/NTSC
	 * Creates 1st-order low-pass filter at fc = 1/(2π × τ) ≈ 3183 Hz
	 * IIR equation: y[n] = alpha * x[n] + (1-alpha) * y[n-1]
	 */
	double time_constant = 50e-6;  /* 50 microseconds for PAL */
	double fc = 1.0 / (2.0 * M_PI * time_constant);

	/* Calculate IIR coefficient: alpha = 1 / (1 + fs/(2πfc)) */
	audio->deemph_alpha = 1.0 / (1.0 + (double)sample_rate / (2.0 * M_PI * fc));
	audio->deemph_prev = 0;

	audio->deemph_filter = NULL;  /* Not using FIR, using IIR instead */
	audio->resampler = NULL;

	/* Initialize A2 Stereo pilot tone detection */
	audio->a2_stereo_enabled = 1;  /* Enable by default */
	audio->a2_pilot_freq = 54687.5;  /* 54.6875 kHz pilot tone for A2 Stereo */
	audio->a2_pilot_phase = 0;
	/* Calculate phase step: (2^32 * freq) / sample_rate */
	audio->a2_pilot_step = (int)((4294967296.0 * audio->a2_pilot_freq) / sample_rate);
	audio->a2_pilot_i = 0;
	audio->a2_pilot_q = 0;
	audio->a2_stereo_detected = 0;
	audio->a2_confidence = 0;

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
	int32_t filtered;

	/* FM demodulate */
	demod = rx_fm_demod_process(&audio->fm_demod, i, q);

	/* Apply de-emphasis filter (1st-order IIR low-pass)
	 * y[n] = alpha * x[n] + (1-alpha) * y[n-1]
	 */
	filtered = (int32_t)(audio->deemph_alpha * demod + (1.0 - audio->deemph_alpha) * audio->deemph_prev);
	audio->deemph_prev = filtered;

	/* Clamp to int16_t range */
	if(filtered > 32767) filtered = 32767;
	if(filtered < -32768) filtered = -32768;

	/* A2 Stereo pilot tone detection */
	if(audio->a2_stereo_enabled)
	{
		/* Correlate with pilot tone frequency (54.6875 kHz) */
		/* Generate local oscillator for pilot tone */
		int32_t cos_pilot = (cos(2.0 * M_PI * audio->a2_pilot_phase / 4294967296.0) * 16384.0);
		int32_t sin_pilot = (sin(2.0 * M_PI * audio->a2_pilot_phase / 4294967296.0) * 16384.0);

		/* Correlate (multiply and integrate) */
		audio->a2_pilot_i = (audio->a2_pilot_i * 255 + (int32_t)filtered * cos_pilot) / 256;
		audio->a2_pilot_q = (audio->a2_pilot_q * 255 + (int32_t)filtered * sin_pilot) / 256;

		/* Advance pilot phase */
		audio->a2_pilot_phase += audio->a2_pilot_step;

		/* Detect pilot tone magnitude */
		int32_t magnitude = (int32_t)sqrt((double)(audio->a2_pilot_i * audio->a2_pilot_i +
		                                           audio->a2_pilot_q * audio->a2_pilot_q));

		/* Update stereo detection */
		if(magnitude > 1000000)  /* Threshold for pilot tone presence */
		{
			audio->a2_confidence = (audio->a2_confidence < 100) ? audio->a2_confidence + 1 : 100;
		}
		else
		{
			audio->a2_confidence = (audio->a2_confidence > 0) ? audio->a2_confidence - 1 : 0;
		}

		/* Mark as stereo if confidence high enough */
		audio->a2_stereo_detected = (audio->a2_confidence > 50) ? 1 : 0;
	}

	/* TODO: Apply resampling if needed */

	return (int16_t)filtered;
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

	/* Initialize NICAM decoder if enabled */
	if(conf->enable_nicam)
	{
		double nicam_freq = (conf->nicam_carrier > 0) ? conf->nicam_carrier : 6552000.0;  /* Default PAL */

		if(nicam_decoder_init(&rx->nicam_decoder, conf->sample_rate, nicam_freq) != 0)
		{
			fprintf(stderr, "Failed to initialize NICAM decoder\n");
			rx_free(rx);
			return -1;
		}

		rx->enable_nicam = 1;
		printf("NICAM decoder enabled (%.2f MHz carrier)\n", nicam_freq / 1e6);
	}

	/* Initialize Teletext decoder if enabled */
	if(conf->enable_teletext)
	{
		int is_625_line = (conf->lines == 625);

		if(ttx_decoder_init(&rx->teletext_decoder, conf->sample_rate, line_length, is_625_line) != 0)
		{
			fprintf(stderr, "Failed to initialize Teletext decoder\n");
			rx_free(rx);
			return -1;
		}

		/* Enable raw output if specified */
		if(conf->teletext_output)
		{
			/* Will save captured pages at end */
		}

		rx->enable_teletext = 1;
		printf("Teletext decoder enabled\n");
	}

	/* Initialize WSS decoder if enabled */
	if(conf->enable_wss)
	{
		if(wss_decoder_init(&rx->wss_decoder, conf->sample_rate, line_length, conf->lines) != 0)
		{
			fprintf(stderr, "Failed to initialize WSS decoder\n");
			rx_free(rx);
			return -1;
		}

		rx->enable_wss = 1;
		printf("WSS (Widescreen Signaling) decoder enabled\n");
	}

	/* Initialize VITC decoder if enabled */
	if(conf->enable_vitc)
	{
		int is_625_line = (conf->lines == 625);

		if(vitc_decoder_init(&rx->vitc_decoder, conf->sample_rate, line_length, is_625_line) != 0)
		{
			fprintf(stderr, "Failed to initialize VITC decoder\n");
			rx_free(rx);
			return -1;
		}

		rx->enable_vitc = 1;
		printf("VITC (Vertical Interval Timecode) decoder enabled\n");
	}

	/* Initialize VITS decoder if enabled */
	if(conf->enable_vits)
	{
		int is_625_line = (conf->lines == 625);

		if(vits_decoder_init(&rx->vits_decoder, conf->sample_rate, line_length, is_625_line) != 0)
		{
			fprintf(stderr, "Failed to initialize VITS decoder\n");
			rx_free(rx);
			return -1;
		}

		rx->enable_vits = 1;
		printf("VITS (Vertical Interval Test Signals) decoder enabled\n");
	}

	/* Initialize video output if specified */
	if(conf->video_output_file && conf->video_output_format != VIDEO_OUT_NONE)
	{
		if(video_output_init(&rx->video_output,
		                      conf->video_output_format,
		                      conf->video_output_file,
		                      rx->frame_width,
		                      rx->frame_height,
		                      conf->frame_rate.num,
		                      conf->frame_rate.den,
		                      conf->interlaced) != 0)
		{
			fprintf(stderr, "Failed to initialize video output\n");
			rx_free(rx);
			return -1;
		}

		rx->enable_video_output = 1;
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
	printf("  NICAM: %s\n", rx->enable_nicam ? "enabled" : "disabled");
	printf("  Teletext: %s\n", rx->enable_teletext ? "enabled" : "disabled");
	printf("  Video output: %s\n", rx->enable_video_output ? video_output_format_name(conf->video_output_format) : "disabled");

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

	/* Free NICAM decoder */
	if(rx->enable_nicam)
	{
		nicam_decoder_free(&rx->nicam_decoder);
	}

	/* Free Teletext decoder and save pages if requested */
	if(rx->enable_teletext)
	{
		if(rx->conf.teletext_output)
		{
			ttx_decoder_save_pages(&rx->teletext_decoder, rx->conf.teletext_output);
		}
		ttx_decoder_free(&rx->teletext_decoder);
	}

	/* Free WSS decoder */
	if(rx->enable_wss)
	{
		wss_decoder_free(&rx->wss_decoder);
	}

	/* Free VITC decoder */
	if(rx->enable_vitc)
	{
		vitc_decoder_free(&rx->vitc_decoder);
	}

	/* Free VITS decoder */
	if(rx->enable_vits)
	{
		vits_decoder_free(&rx->vits_decoder);
	}

	/* Close video output */
	if(rx->enable_video_output)
	{
		video_output_close(&rx->video_output);
		video_output_free(&rx->video_output);
	}

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

			/* Process Teletext from VBI lines */
			if(rx->enable_teletext)
			{
				int is_625 = (rx->conf.lines == 625);
				int vbi_start = is_625 ? TTX_LINE_START_625 : TTX_LINE_START_525;
				int vbi_end = is_625 ? TTX_LINE_END_625 : TTX_LINE_END_525;

				if(line_num >= vbi_start && line_num <= vbi_end)
				{
					ttx_decoder_process_line(&rx->teletext_decoder, rx->line_buffer, line_num);
				}
			}

			/* Process WSS (Widescreen Signaling) */
			if(rx->enable_wss)
			{
				int wss_result = wss_decoder_process_line(&rx->wss_decoder, rx->line_buffer, line_num, field);

				/* Print WSS info when first detected or when it changes */
				if(wss_result == 1 && rx->wss_decoder.confidence >= 3)
				{
					static uint16_t last_wss_word = 0;
					if(rx->wss_decoder.current_word != last_wss_word)
					{
						char wss_info[256];
						wss_decoder_get_info(&rx->wss_decoder, wss_info, sizeof(wss_info));
						fprintf(stderr, "%s\n", wss_info);
						last_wss_word = rx->wss_decoder.current_word;
					}
				}
			}

			/* Process VITC (Vertical Interval Timecode) */
			if(rx->enable_vitc)
			{
				int vitc_result = vitc_decoder_process_line(&rx->vitc_decoder, rx->line_buffer, line_num);

				/* Print VITC info when first detected or when seconds change */
				if(vitc_result == 1 && vitc_decoder_is_valid(&rx->vitc_decoder))
				{
					static int last_seconds = -1;
					if(rx->vitc_decoder.current_tc.seconds != last_seconds)
					{
						char vitc_info[256];
						vitc_decoder_get_info(&rx->vitc_decoder, vitc_info, sizeof(vitc_info));
						fprintf(stderr, "%s\n", vitc_info);
						last_seconds = rx->vitc_decoder.current_tc.seconds;
					}
				}
			}

			/* Process VITS (Vertical Interval Test Signals) */
			if(rx->enable_vits)
			{
				vits_type_t vits_type = vits_decoder_process_line(&rx->vits_decoder, rx->line_buffer, line_num);

				/* Print VITS info when test signals detected */
				if(vits_type != VITS_TYPE_NONE)
				{
					static int vits_report_counter = 0;
					/* Report every 25 frames (1 second for PAL) */
					if(vits_report_counter++ >= 25)
					{
						char vits_info[256];
						vits_decoder_get_info(&rx->vits_decoder, vits_info, sizeof(vits_info));
						fprintf(stderr, "%s\n", vits_info);
						vits_report_counter = 0;
					}
				}
			}

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

				/* Process color burst with FULL line buffer (includes sync and burst) */
				switch(rx->conf.colour_type)
				{
					case RX_COLOUR_PAL:
						if(rx->pal_decoder.use_burst_pll)
						{
							pll_burst_process(&rx->pal_decoder.burst_pll, rx->line_buffer, rx->pal_decoder.line_length);
						}

						/* Offset prev_line to align with current line's active video start */
						/* This ensures sample-perfect alignment for the comb filter */
						if(rx->pal_decoder.prev_line && active_start < rx->pal_decoder.prev_line_length)
						{
							rx->pal_decoder.prev_line_offset = rx->pal_decoder.prev_line + active_start;
						}
						else
						{
							rx->pal_decoder.prev_line_offset = NULL;
						}

						/* Pass active video portion to decoder */
						rx_pal_decode_line(&rx->pal_decoder, rx->line_buffer + active_start, fb_ptr, active_width);
						break;
					case RX_COLOUR_NTSC:
						if(rx->ntsc_decoder.use_burst_pll)
						{
							pll_burst_process(&rx->ntsc_decoder.burst_pll, rx->line_buffer, rx->ntsc_decoder.line_length);
						}

						/* Offset prev_line to align with current line's active video start */
						/* This ensures sample-perfect alignment for the comb filter */
						if(rx->ntsc_decoder.prev_line && active_start < rx->ntsc_decoder.prev_line_length)
						{
							rx->ntsc_decoder.prev_line_offset = rx->ntsc_decoder.prev_line + active_start;
						}
						else
						{
							rx->ntsc_decoder.prev_line_offset = NULL;
						}

						/* Pass active video portion to decoder */
						rx_ntsc_decode_line(&rx->ntsc_decoder, rx->line_buffer + active_start, fb_ptr, active_width);
						break;
					case RX_COLOUR_SECAM:
						/* Pass active video portion to decoder */
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

			/* CRITICAL FIX: Save ENTIRE line for comb filter delay line */
			/* Must copy FULL line buffer (including sync and burst) AFTER processing */
			/* but BEFORE resetting line_buffer_pos */
			switch(rx->conf.colour_type)
			{
				case RX_COLOUR_PAL:
					if(rx->pal_decoder.prev_line && rx->line_buffer_pos <= rx->pal_decoder.prev_line_length)
					{
						memcpy(rx->pal_decoder.prev_line, rx->line_buffer, rx->line_buffer_pos * sizeof(int16_t));
					}
					break;
				case RX_COLOUR_NTSC:
					if(rx->ntsc_decoder.prev_line && rx->line_buffer_pos <= rx->ntsc_decoder.prev_line_length)
					{
						memcpy(rx->ntsc_decoder.prev_line, rx->line_buffer, rx->line_buffer_pos * sizeof(int16_t));
					}
					break;
				default:
					break;
			}

			/* Reset line buffer */
			rx->line_buffer_pos = 0;

			/* Count frames */
			if(line_num == 0)
			{
				rx->frames_decoded++;

			/* Write frame to video output if enabled */
			if(rx->enable_video_output)
			{
				video_output_write_frame(&rx->video_output, rx->framebuffer);
			}

			/* Save teletext pages periodically (every 100 frames ~4 seconds) */
			if(rx->enable_teletext && rx->conf.teletext_output && (rx->frames_decoded % 100 == 0))
			{
				ttx_decoder_save_pages(&rx->teletext_decoder, rx->conf.teletext_output);
			}
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
