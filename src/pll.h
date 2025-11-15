/* pll.h - Phase-Locked Loop Implementation */
/*=======================================================================*/
/* Copyright 2025 - PLL for Sync and Color Burst Recovery                */
/*=======================================================================*/

#ifndef _PLL_H
#define _PLL_H

#include <stdint.h>

/* PLL for horizontal sync recovery */
typedef struct {
	/* Configuration */
	double sample_rate;      /* Sample rate in Hz */
	double line_frequency;   /* Expected line frequency (15625 Hz for PAL) */

	/* PLL state */
	double phase;            /* Current phase (0 to 2π) */
	double frequency;        /* Current frequency */
	double phase_error;      /* Phase error accumulator */

	/* Loop filter parameters */
	double kp;               /* Proportional gain */
	double ki;               /* Integral gain */

	/* Statistics */
	int locked;
	double lock_indicator;
	uint64_t cycles;

} pll_hsync_t;

/* PLL for color burst (subcarrier) recovery */
typedef struct {
	/* Configuration */
	double sample_rate;
	double nominal_frequency; /* Nominal subcarrier frequency */

	/* PLL state */
	double phase;
	double frequency;
	double phase_error;

	/* Loop filter */
	double kp;
	double ki;

	/* Burst gate */
	int burst_start;         /* Sample offset for burst */
	int burst_length;        /* Burst duration in samples */
	int in_burst;

	/* Output */
	int32_t cos_lut[1024];   /* Cosine lookup table */
	int32_t sin_lut[1024];   /* Sine lookup table */
	int lut_phase;           /* Current LUT phase */

	/* Statistics */
	int locked;
	double snr_estimate;

} pll_burst_t;

/* Hsync PLL functions */
int pll_hsync_init(pll_hsync_t *pll, double sample_rate, double line_freq);
void pll_hsync_update(pll_hsync_t *pll, int sync_pulse);
int pll_hsync_predict_sync(pll_hsync_t *pll);
double pll_hsync_get_phase_error(pll_hsync_t *pll);
int pll_hsync_is_locked(pll_hsync_t *pll);

/* Color burst PLL functions */
int pll_burst_init(pll_burst_t *pll, double sample_rate, double subcarrier_freq);
void pll_burst_process(pll_burst_t *pll, int16_t *line, int line_length);
void pll_burst_get_reference(pll_burst_t *pll, int32_t *cos_out, int32_t *sin_out);
int pll_burst_is_locked(pll_burst_t *pll);
void pll_burst_reset(pll_burst_t *pll);

#endif /* _PLL_H */
