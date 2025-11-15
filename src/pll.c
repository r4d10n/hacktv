/* pll.c - Phase-Locked Loop Implementation */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "pll.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* =======================================================================*/
/* Horizontal Sync PLL Implementation                                    */
/* =======================================================================*/

int pll_hsync_init(pll_hsync_t *pll, double sample_rate, double line_freq)
{
	memset(pll, 0, sizeof(pll_hsync_t));

	pll->sample_rate = sample_rate;
	pll->line_frequency = line_freq;

	/* Initialize frequency to nominal */
	pll->frequency = line_freq;
	pll->phase = 0.0;

	/* Loop filter gains - tuned for stable lock */
	/* Higher bandwidth for faster acquisition */
	pll->kp = 0.01;  /* Proportional gain */
	pll->ki = 0.0001;  /* Integral gain */

	pll->locked = 0;
	pll->lock_indicator = 0.0;

	return 0;
}

void pll_hsync_update(pll_hsync_t *pll, int sync_pulse)
{
	double expected_phase = fmod(pll->cycles * 2.0 * M_PI, 2.0 * M_PI);

	/* If we detected a sync pulse, calculate phase error */
	if(sync_pulse)
	{
		/* Phase error is difference between expected and actual */
		double actual_phase = fmod(pll->phase, 2.0 * M_PI);
		double error = expected_phase - actual_phase;

		/* Wrap error to -π to +π */
		while(error > M_PI) error -= 2.0 * M_PI;
		while(error < -M_PI) error += 2.0 * M_PI;

		/* Update phase error accumulator */
		pll->phase_error = error;

		/* Loop filter - PI controller */
		double correction = pll->kp * error + pll->ki * pll->phase_error;

		/* Update frequency */
		pll->frequency += correction;

		/* Clamp frequency to reasonable range (±5%) */
		double min_freq = pll->line_frequency * 0.95;
		double max_freq = pll->line_frequency * 1.05;
		if(pll->frequency < min_freq) pll->frequency = min_freq;
		if(pll->frequency > max_freq) pll->frequency = max_freq;

		/* Update lock indicator - exponential average of error magnitude */
		double abs_error = fabs(error);
		pll->lock_indicator = 0.99 * pll->lock_indicator + 0.01 * abs_error;

		/* Consider locked if error is small and stable */
		if(pll->lock_indicator < 0.1)  /* Less than ~6° error */
		{
			pll->locked = 1;
		}
		else if(pll->lock_indicator > 0.3)
		{
			pll->locked = 0;
		}

		/* Reset phase for this line */
		pll->phase = 0.0;
		pll->cycles++;
	}

	/* Advance phase based on current frequency */
	double phase_inc = 2.0 * M_PI * pll->frequency / pll->sample_rate;
	pll->phase += phase_inc;
}

int pll_hsync_predict_sync(pll_hsync_t *pll)
{
	/* Predict if sync should occur now based on PLL phase */
	double normalized_phase = fmod(pll->phase, 2.0 * M_PI);

	/* Sync occurs near phase = 0 */
	/* Allow small window (±10°) */
	double tolerance = 0.174533;  /* 10 degrees in radians */

	if(normalized_phase < tolerance ||
	   normalized_phase > (2.0 * M_PI - tolerance))
	{
		return 1;
	}

	return 0;
}

double pll_hsync_get_phase_error(pll_hsync_t *pll)
{
	return pll->phase_error;
}

int pll_hsync_is_locked(pll_hsync_t *pll)
{
	return pll->locked;
}

/* =======================================================================*/
/* Color Burst PLL Implementation                                        */
/* =======================================================================*/

int pll_burst_init(pll_burst_t *pll, double sample_rate, double subcarrier_freq)
{
	memset(pll, 0, sizeof(pll_burst_t));

	pll->sample_rate = sample_rate;
	pll->nominal_frequency = subcarrier_freq;
	pll->frequency = subcarrier_freq;

	/* Loop filter gains - need tighter control for color */
	pll->kp = 0.02;
	pll->ki = 0.0005;

	/* Burst gate timing (PAL) - adjust for other standards */
	/* Burst is at ~5.6μs after sync */
	pll->burst_start = (int)(sample_rate * 5.6e-6);
	pll->burst_length = (int)(sample_rate * 2.25e-6);  /* ~10 cycles of burst */

	/* Generate lookup tables */
	for(int i = 0; i < 1024; i++)
	{
		double angle = 2.0 * M_PI * i / 1024.0;
		pll->cos_lut[i] = (int32_t)(cos(angle) * INT32_MAX);
		pll->sin_lut[i] = (int32_t)(sin(angle) * INT32_MAX);
	}

	pll->locked = 0;

	return 0;
}

void pll_burst_process(pll_burst_t *pll, int16_t *line, int line_length)
{
	/* Process color burst to lock PLL */
	if(pll->burst_start + pll->burst_length > line_length)
	{
		return;  /* Burst not in this line */
	}

	/* Extract burst samples */
	int burst_end = pll->burst_start + pll->burst_length;

	double i_sum = 0.0, q_sum = 0.0;
	double mag_sum = 0.0;
	int count = 0;

	/* Demodulate burst using current PLL reference */
	for(int n = pll->burst_start; n < burst_end; n++)
	{
		int16_t sample = line[n];

		/* Get reference from LUT */
		int lut_idx = pll->lut_phase % 1024;
		int32_t ref_cos = pll->cos_lut[lut_idx];
		int32_t ref_sin = pll->sin_lut[lut_idx];

		/* Multiply sample by reference (demodulate) */
		double i = (double)sample * ref_cos / INT32_MAX;
		double q = (double)sample * ref_sin / INT32_MAX;

		i_sum += i;
		q_sum += q;
		mag_sum += sqrt(i * i + q * q);

		/* Advance LUT phase */
		double phase_inc = 1024.0 * pll->frequency / pll->sample_rate;
		pll->lut_phase += (int)phase_inc;

		count++;
	}

	if(count == 0) return;

	/* Calculate average I and Q */
	double i_avg = i_sum / count;
	double q_avg = q_sum / count;

	/* Phase error is the angle of the burst */
	/* For a locked PLL, burst should be at a specific phase */
	double burst_phase = atan2(q_avg, i_avg);

	/* Sync LUT phase to match burst phase */
	/* This ensures our reference signals are aligned with the carrier */
	double current_lut_angle = 2.0 * M_PI * (pll->lut_phase % 1024) / 1024.0;
	double phase_error = burst_phase - current_lut_angle;

	/* Normalize phase error to [-π, π] */
	while(phase_error > M_PI) phase_error -= 2.0 * M_PI;
	while(phase_error < -M_PI) phase_error += 2.0 * M_PI;

	/* Update PLL based on phase error */
	double error = phase_error;

	/* Loop filter */
	pll->phase_error += error * pll->ki;
	double correction = error * pll->kp + pll->phase_error;

	/* Update frequency */
	pll->frequency += correction;

	/* Clamp frequency */
	double min_freq = pll->nominal_frequency * 0.999;
	double max_freq = pll->nominal_frequency * 1.001;
	if(pll->frequency < min_freq) pll->frequency = min_freq;
	if(pll->frequency > max_freq) pll->frequency = max_freq;

	/* Apply phase correction to sync LUT phase with burst */
	double phase_correction_samples = (error / (2.0 * M_PI)) * (1024.0 / (pll->frequency / pll->sample_rate));
	pll->lut_phase += (int)phase_correction_samples;

	/* Estimate SNR from burst magnitude */
	double avg_mag = mag_sum / count;
	pll->snr_estimate = 0.9 * pll->snr_estimate + 0.1 * avg_mag;

	/* Lock detection */
	if(pll->snr_estimate > 1000.0 && fabs(error) < 0.2)
	{
		pll->locked = 1;
	}
	else if(pll->snr_estimate < 500.0 || fabs(error) > 0.5)
	{
		pll->locked = 0;
	}
}

void pll_burst_get_reference(pll_burst_t *pll, int32_t *cos_out, int32_t *sin_out)
{
	/* Return reference signals directly (burst at 0° aligns with U-axis) */
	int lut_idx = pll->lut_phase % 1024;

	*cos_out = pll->cos_lut[lut_idx];
	*sin_out = pll->sin_lut[lut_idx];

	/* Advance phase for next sample */
	double phase_inc = 1024.0 * pll->frequency / pll->sample_rate;
	pll->lut_phase += (int)phase_inc;
}

int pll_burst_is_locked(pll_burst_t *pll)
{
	return pll->locked;
}

void pll_burst_reset(pll_burst_t *pll)
{
	pll->phase = 0.0;
	pll->lut_phase = 0;
	pll->phase_error = 0.0;
	pll->locked = 0;
}
