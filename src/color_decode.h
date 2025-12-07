/* color_decode.h - High-Quality PAL/NTSC Color Decoder                    */
/*=========================================================================*/
/* Based on LMP88959 PAL-CRT and NTSC-CRT reference implementations        */
/* https://github.com/LMP88959/PAL-CRT                                     */
/* https://github.com/LMP88959/NTSC-CRT                                    */
/*                                                                         */
/* This implementation uses:                                               */
/* - 4fsc sampling rates (4 samples per color carrier cycle)               */
/* - Quadrature demodulation with 4-sample phase detection                 */
/* - Three-band equalizer for luma/chroma filtering                        */
/* - 1H comb filter for improved color separation                          */
/* - Proper burst phase detection and tracking                             */
/*=========================================================================*/
/* Copyright 2025 - Licensed under GNU GPL v3                              */
/*=========================================================================*/

#ifndef _COLOR_DECODE_H
#define _COLOR_DECODE_H

#include <stdint.h>
#include "common.h"

/*=========================================================================*/
/* Constants for PAL and NTSC                                              */
/*=========================================================================*/

/* PAL constants - 4fsc sampling at 17.734475 MHz */
#define PAL_FSC             4433618.75      /* PAL color subcarrier (Hz) */
#define PAL_4FSC            17734475        /* 4 * PAL_FSC (Hz) */
#define PAL_HRES            1135            /* Horizontal samples per line at 4fsc */
#define PAL_VRES            576             /* Active vertical lines */
#define PAL_LINES           625             /* Total lines per frame */
#define PAL_LINE_NS         64000           /* Line duration (ns) */
#define PAL_ACTIVE_NS       52000           /* Active video duration (ns) */
#define PAL_SYNC_NS         4700            /* Sync tip duration (ns) */
#define PAL_BURST_NS        2250            /* Color burst duration (ns) */
#define PAL_BURST_START_NS  5600            /* Burst start position (ns) */
#define PAL_CB_CYCLES       10              /* Color burst cycles */
#define PAL_CC_SAMPLES      4               /* Samples per color cycle */

/* NTSC constants - 4fsc sampling at 14.318180 MHz */
#define NTSC_FSC            3579545.45      /* NTSC color subcarrier (Hz) */
#define NTSC_4FSC           14318180        /* 4 * NTSC_FSC (Hz) */
#define NTSC_HRES           910             /* Horizontal samples per line at 4fsc */
#define NTSC_VRES           480             /* Active vertical lines */
#define NTSC_LINES          525             /* Total lines per frame */
#define NTSC_LINE_NS        63556           /* Line duration (ns) */
#define NTSC_ACTIVE_NS      52600           /* Active video duration (ns) */
#define NTSC_SYNC_NS        4700            /* Sync tip duration (ns) */
#define NTSC_BURST_NS       2500            /* Color burst duration (ns) */
#define NTSC_BURST_START_NS 5300            /* Burst start position (ns) */
#define NTSC_CB_CYCLES      9               /* Color burst cycles */
#define NTSC_CC_SAMPLES     4               /* Samples per color cycle */

/* Signal levels (IRE units mapped to 16-bit) */
#define SYNC_LEVEL          (-40 * 327)     /* -40 IRE */
#define BLANK_LEVEL         (0)             /* 0 IRE */
#define BLACK_LEVEL         (7.5 * 327)     /* 7.5 IRE (NTSC pedestal) */
#define WHITE_LEVEL         (100 * 327)     /* 100 IRE */
#define BURST_LEVEL         (20 * 327)      /* 20 IRE peak-to-peak */

/* Fixed-point math constants */
#define FP_BITS             16              /* Fixed-point fractional bits */
#define FP_ONE              (1 << FP_BITS)
#define FP_HALF             (1 << (FP_BITS - 1))

/* Trigonometry constants (14-bit angle representation) */
#define T14_2PI             16384
#define T14_PI              8192
#define T14_MASK            16383

/* Equalizer constants */
#define EQ_P                16              /* Equalizer precision bits */
#define EQ_UNITY            (1 << EQ_P)

/*=========================================================================*/
/* Color System Type                                                       */
/*=========================================================================*/

typedef enum {
    COLOR_SYS_NONE = 0,
    COLOR_SYS_PAL,
    COLOR_SYS_NTSC,
    COLOR_SYS_SECAM
} color_system_t;

/*=========================================================================*/
/* Three-Band Equalizer (based on PAL-CRT/NTSC-CRT)                        */
/* Provides separate control for low, mid, and high frequencies            */
/*=========================================================================*/

typedef struct {
    /* Filter state for low-pass section */
    int32_t lf;                 /* Low-pass filter state */
    int32_t hf;                 /* High-pass filter state */

    /* Cutoff frequencies (normalized) */
    int32_t lo_cutoff;          /* Low/mid crossover */
    int32_t hi_cutoff;          /* Mid/high crossover */

    /* Gains for each band */
    int32_t lo_gain;            /* Low frequency gain */
    int32_t mid_gain;           /* Mid frequency gain */
    int32_t hi_gain;            /* High frequency gain */
} eq_band3_t;

/*=========================================================================*/
/* Color Burst Detector                                                    */
/* Detects and locks to the color burst phase                              */
/*=========================================================================*/

typedef struct {
    /* Burst position (in samples) */
    int burst_start;
    int burst_length;

    /* Phase accumulator and lock state */
    int32_t phase_acc;          /* Phase accumulator (14-bit) */
    int32_t phase_inc;          /* Phase increment per sample */
    int locked;                 /* Lock indicator */
    int lock_count;             /* Samples since lock acquired */

    /* Correlation accumulators for phase detection */
    int32_t corr_i;             /* In-phase correlation */
    int32_t corr_q;             /* Quadrature correlation */

    /* PLL parameters */
    int32_t pll_alpha;          /* PLL loop gain (proportional) */
    int32_t pll_beta;           /* PLL loop gain (integral) */
    int32_t freq_error;         /* Frequency error accumulator */
} burst_detector_t;

/*=========================================================================*/
/* Color Carrier Generator                                                 */
/* Generates quadrature reference for demodulation                         */
/*=========================================================================*/

typedef struct {
    /* Color carrier frequency lookup table */
    /* CCF stores 4 samples per cycle at 4fsc sampling */
    int16_t *ccf;               /* Color carrier table */
    int ccf_size;               /* Table size (line samples × periods) */
    int cc_period;              /* Vertical period (lines for phase coherence) */

    /* Current position in table */
    int ccf_index;

    /* Samples per color cycle (always 4 at 4fsc) */
    int cc_samples;
} cc_generator_t;

/*=========================================================================*/
/* 1H Delay Line (Comb Filter)                                             */
/* Stores previous line for PAL V-switch and comb filtering                */
/*=========================================================================*/

typedef struct {
    int16_t *line_buffer;       /* Previous line storage */
    int line_length;            /* Line length in samples */
    int valid;                  /* Buffer contains valid data */
} delay_1h_t;

/*=========================================================================*/
/* PAL Color Decoder                                                       */
/*=========================================================================*/

typedef struct {
    /* Configuration */
    int sample_rate;            /* Input sample rate */
    int line_length;            /* Samples per line */
    int active_start;           /* Active video start sample */
    int active_length;          /* Active video samples */

    /* Color carrier generator */
    cc_generator_t cc_gen;

    /* Burst detector */
    burst_detector_t burst;

    /* 1H delay line for comb filter */
    delay_1h_t delay_line;

    /* Three-band equalizers */
    eq_band3_t y_eq;            /* Luminance equalizer */
    eq_band3_t uv_eq;           /* Chrominance equalizer */

    /* PAL V-switch state */
    int v_switch;               /* Alternates each line */

    /* Current line number (for phase calculation) */
    int line_number;

    /* Horizontal sync position (samples) */
    int hsync;

    /* Adjustment parameters */
    int32_t hue;                /* Hue adjustment (0-360 degrees) */
    int32_t saturation;         /* Saturation (1.0 = 65536) */
    int32_t brightness;         /* Brightness offset */
    int32_t contrast;           /* Contrast (1.0 = 65536) */

    /* Enable comb filter */
    int use_comb;

    /* Decode statistics */
    int burst_lock_count;
    int frames_decoded;
} pal_decoder_t;

/*=========================================================================*/
/* NTSC Color Decoder                                                      */
/*=========================================================================*/

typedef struct {
    /* Configuration */
    int sample_rate;            /* Input sample rate */
    int line_length;            /* Samples per line */
    int active_start;           /* Active video start sample */
    int active_length;          /* Active video samples */

    /* Color carrier generator */
    cc_generator_t cc_gen;

    /* Burst detector */
    burst_detector_t burst;

    /* 1H delay line for comb filter */
    delay_1h_t delay_line;

    /* Three-band equalizers */
    eq_band3_t y_eq;            /* Luminance equalizer */
    eq_band3_t iq_eq;           /* Chrominance equalizer */

    /* Current line number */
    int line_number;

    /* Horizontal sync position (samples) */
    int hsync;

    /* Adjustment parameters */
    int32_t hue;                /* Hue adjustment (degrees × 256) */
    int32_t saturation;         /* Saturation (1.0 = 65536) */
    int32_t brightness;         /* Brightness offset */
    int32_t contrast;           /* Contrast (1.0 = 65536) */

    /* Enable comb filter */
    int use_comb;

    /* Decode statistics */
    int burst_lock_count;
    int frames_decoded;
} ntsc_decoder_t;

/*=========================================================================*/
/* Color Bars Test Pattern Generator                                       */
/*=========================================================================*/

typedef struct {
    color_system_t system;
    int sample_rate;
    int line_length;
    int active_start;
    int active_length;

    /* Current position */
    int current_line;
    int current_frame;

    /* Output buffer */
    int16_t *line_buffer;

    /* Color carrier phase */
    int32_t phase_acc;
    int32_t phase_inc;

    /* PAL V-switch */
    int v_switch;
} colorbars_gen_t;

/*=========================================================================*/
/* Function Prototypes                                                     */
/*=========================================================================*/

/* Utility functions */
int32_t sin_lookup(int32_t angle);
int32_t cos_lookup(int32_t angle);
void normalize_freq(double freq_hz, int sample_rate, int32_t *normalized);

/* Three-band equalizer */
int eq_band3_init(eq_band3_t *eq, int sample_rate,
                  double lo_freq, double hi_freq,
                  double lo_gain, double mid_gain, double hi_gain);
int16_t eq_band3_process(eq_band3_t *eq, int16_t sample);
void eq_band3_reset(eq_band3_t *eq);

/* Burst detector */
int burst_detector_init(burst_detector_t *bd, int sample_rate,
                        double subcarrier_freq, int burst_start, int burst_length);
void burst_detector_free(burst_detector_t *bd);
void burst_detector_process(burst_detector_t *bd, const int16_t *line, int line_length);
int burst_detector_is_locked(burst_detector_t *bd);
void burst_detector_get_phase(burst_detector_t *bd, int32_t *phase);

/* Color carrier generator */
int cc_generator_init(cc_generator_t *cc, int sample_rate,
                      double subcarrier_freq, int cc_period, int line_length);
void cc_generator_free(cc_generator_t *cc);
void cc_generator_get_ref(cc_generator_t *cc, int sample, int line,
                          int16_t *ref_i, int16_t *ref_q);
void cc_generator_sync_to_burst(cc_generator_t *cc, int32_t phase);

/* 1H delay line */
int delay_1h_init(delay_1h_t *dl, int line_length);
void delay_1h_free(delay_1h_t *dl);
void delay_1h_store(delay_1h_t *dl, const int16_t *line);
int16_t delay_1h_get(delay_1h_t *dl, int sample);
int delay_1h_is_valid(delay_1h_t *dl);

/* PAL decoder */
int pal_decoder_init(pal_decoder_t *dec, int sample_rate);
void pal_decoder_free(pal_decoder_t *dec);
void pal_decoder_set_params(pal_decoder_t *dec,
                            double hue, double saturation,
                            double brightness, double contrast);
void pal_decoder_decode_line(pal_decoder_t *dec, const int16_t *input,
                             uint32_t *rgb_out, int width);
void pal_decoder_new_field(pal_decoder_t *dec, int field);

/* NTSC decoder */
int ntsc_decoder_init(ntsc_decoder_t *dec, int sample_rate);
void ntsc_decoder_free(ntsc_decoder_t *dec);
void ntsc_decoder_set_params(ntsc_decoder_t *dec,
                             double hue, double saturation,
                             double brightness, double contrast);
void ntsc_decoder_decode_line(ntsc_decoder_t *dec, const int16_t *input,
                              uint32_t *rgb_out, int width);
void ntsc_decoder_new_field(ntsc_decoder_t *dec, int field);

/* Color bars generator */
int colorbars_gen_init(colorbars_gen_t *gen, color_system_t system, int sample_rate);
void colorbars_gen_free(colorbars_gen_t *gen);
void colorbars_gen_line(colorbars_gen_t *gen, int16_t *output, int line_number);
void colorbars_gen_reset(colorbars_gen_t *gen);

/* YUV to RGB conversion (BT.601) */
void yuv_to_rgb_bt601(int16_t y, int16_t u, int16_t v,
                      uint8_t *r, uint8_t *g, uint8_t *b);

/* IQ to RGB conversion (for NTSC) */
void iq_to_rgb_ntsc(int16_t y, int16_t i, int16_t q,
                    uint8_t *r, uint8_t *g, uint8_t *b);

/* High-level decode function */
int color_decode_frame(color_system_t system, void *decoder,
                       const int16_t *input, int input_stride,
                       uint32_t *rgb_out, int width, int height);

#endif /* _COLOR_DECODE_H */
