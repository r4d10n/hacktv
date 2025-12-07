/* color_decode.c - High-Quality PAL/NTSC Color Decoder                    */
/*=========================================================================*/
/* Based on LMP88959 PAL-CRT and NTSC-CRT reference implementations        */
/* https://github.com/LMP88959/PAL-CRT                                     */
/* https://github.com/LMP88959/NTSC-CRT                                    */
/*=========================================================================*/
/* Copyright 2025 - Licensed under GNU GPL v3                              */
/*=========================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "color_decode.h"

/*=========================================================================*/
/* Clamp macro                                                             */
/*=========================================================================*/

#define CLAMP(x, min, max) ((x) < (min) ? (min) : ((x) > (max) ? (max) : (x)))
#define POSMOD(x, n) (((x) % (n) + (n)) % (n))

/*=========================================================================*/
/* Sine lookup table (15-bit precision, 18 significant points)             */
/* Based on NTSC-CRT sigpsin15 table for efficient integer sine            */
/*=========================================================================*/

static const int16_t sine_table[18] = {
    0,     3211,  6392,  9512,  12539, 15446,
    18204, 20787, 23170, 25330, 27245, 28898,
    30273, 31357, 32138, 32610, 32767, 32610
};

/*=========================================================================*/
/* Integer sine/cosine using lookup table with interpolation               */
/*=========================================================================*/

int32_t sin_lookup(int32_t angle)
{
    /* Normalize angle to 0-16383 (T14_2PI range) */
    int a = POSMOD(angle, T14_2PI);
    int quadrant = a >> 12;  /* 0-3 */
    int idx = a & 0xFFF;

    /* Map to first quadrant */
    if (quadrant & 1) {
        idx = 0x1000 - idx;
    }

    /* Scale index to table size (0-16 maps to 0-17 entries) */
    int table_idx = (idx * 17) >> 12;
    int frac = ((idx * 17) & 0xFFF);

    /* Interpolate between table entries */
    int16_t v0 = sine_table[table_idx];
    int16_t v1 = sine_table[table_idx < 17 ? table_idx + 1 : 17];
    int32_t result = v0 + (((v1 - v0) * frac) >> 12);

    /* Apply sign for quadrants 2 and 3 */
    if (quadrant >= 2) {
        result = -result;
    }

    return result;
}

int32_t cos_lookup(int32_t angle)
{
    return sin_lookup(angle + T14_PI / 2);
}

/*=========================================================================*/
/* Normalize frequency to fixed-point representation                       */
/*=========================================================================*/

void normalize_freq(double freq_hz, int sample_rate, int32_t *normalized)
{
    /* Normalize to 0-1 range relative to sample rate */
    double norm = freq_hz / (double)sample_rate;
    *normalized = (int32_t)(norm * EQ_UNITY);
}

/*=========================================================================*/
/* Three-Band Equalizer Implementation                                     */
/* Based on PAL-CRT/NTSC-CRT three-band equalizer                         */
/*=========================================================================*/

int eq_band3_init(eq_band3_t *eq, int sample_rate,
                  double lo_freq, double hi_freq,
                  double lo_gain, double mid_gain, double hi_gain)
{
    memset(eq, 0, sizeof(eq_band3_t));

    /* Calculate normalized cutoff frequencies */
    /* Using bilinear transform approximation */
    double lo_norm = 2.0 * M_PI * lo_freq / sample_rate;
    double hi_norm = 2.0 * M_PI * hi_freq / sample_rate;

    /* Clamp to valid range */
    lo_norm = CLAMP(lo_norm, 0.001, 0.999);
    hi_norm = CLAMP(hi_norm, 0.001, 0.999);

    eq->lo_cutoff = (int32_t)(lo_norm * EQ_UNITY);
    eq->hi_cutoff = (int32_t)(hi_norm * EQ_UNITY);

    eq->lo_gain = (int32_t)(lo_gain * EQ_UNITY);
    eq->mid_gain = (int32_t)(mid_gain * EQ_UNITY);
    eq->hi_gain = (int32_t)(hi_gain * EQ_UNITY);

    return 0;
}

int16_t eq_band3_process(eq_band3_t *eq, int16_t sample)
{
    int32_t input = sample;
    int32_t lo, mid, hi;

    /* Low-pass filter for low frequency extraction */
    eq->lf += ((input - eq->lf) * eq->lo_cutoff) >> EQ_P;
    lo = eq->lf;

    /* High-pass filter for high frequency extraction */
    eq->hf += ((input - eq->hf) * eq->hi_cutoff) >> EQ_P;
    hi = input - eq->hf;

    /* Mid frequency is what's left */
    mid = input - lo - hi;

    /* Apply gains and sum */
    int32_t result = ((lo * eq->lo_gain) >> EQ_P) +
                     ((mid * eq->mid_gain) >> EQ_P) +
                     ((hi * eq->hi_gain) >> EQ_P);

    return (int16_t)CLAMP(result, INT16_MIN, INT16_MAX);
}

void eq_band3_reset(eq_band3_t *eq)
{
    eq->lf = 0;
    eq->hf = 0;
}

/*=========================================================================*/
/* Burst Detector Implementation                                           */
/*=========================================================================*/

int burst_detector_init(burst_detector_t *bd, int sample_rate,
                        double subcarrier_freq, int burst_start, int burst_length)
{
    memset(bd, 0, sizeof(burst_detector_t));

    bd->burst_start = burst_start;
    bd->burst_length = burst_length;

    /* Calculate phase increment per sample */
    /* Phase is in T14 units (0-16383 = 0-2π) */
    bd->phase_inc = (int32_t)((subcarrier_freq / sample_rate) * T14_2PI);

    /* PLL loop filter coefficients */
    /* These control the tracking speed and stability */
    bd->pll_alpha = 256;   /* Proportional gain (fast response) */
    bd->pll_beta = 8;      /* Integral gain (slow drift correction) */

    return 0;
}

void burst_detector_free(burst_detector_t *bd)
{
    /* Nothing to free */
}

void burst_detector_process(burst_detector_t *bd, const int16_t *line, int line_length)
{
    int i;
    int32_t burst_i = 0;
    int32_t burst_q = 0;
    int32_t phase;
    int burst_end = bd->burst_start + bd->burst_length;

    /* Ensure burst is within line */
    if (burst_end > line_length) {
        burst_end = line_length;
    }

    /* Correlate burst with local oscillator */
    phase = bd->phase_acc;
    for (i = bd->burst_start; i < burst_end; i++) {
        int16_t sample = line[i];

        /* Quadrature correlation */
        burst_i += (sample * cos_lookup(phase)) >> 15;
        burst_q += (sample * sin_lookup(phase)) >> 15;

        phase = (phase + bd->phase_inc) & T14_MASK;
    }

    /* Store correlation results */
    bd->corr_i = burst_i;
    bd->corr_q = burst_q;

    /* Calculate phase error from burst correlation */
    /* Phase error = atan2(Q, I) mapped to our 14-bit representation */
    double angle = atan2((double)burst_q, (double)burst_i);
    int32_t phase_error = (int32_t)((angle / (2.0 * M_PI)) * T14_2PI);

    /* For PAL, burst is at -135° (U axis), for NTSC at 180° (along -B-Y) */
    /* We'll adjust the reference phase based on system */

    /* PLL update with loop filter */
    bd->phase_acc = (bd->phase_acc + ((phase_error * bd->pll_alpha) >> 8)) & T14_MASK;
    bd->freq_error += (phase_error * bd->pll_beta) >> 8;
    bd->phase_inc += bd->freq_error >> 8;

    /* Determine lock state based on correlation amplitude */
    int32_t amplitude = (int32_t)sqrt((double)(burst_i * burst_i + burst_q * burst_q));

    if (amplitude > 1000) {  /* Threshold for burst detection */
        if (bd->lock_count < 100) {
            bd->lock_count++;
        }
        if (bd->lock_count > 10) {
            bd->locked = 1;
        }
    } else {
        bd->lock_count = 0;
        bd->locked = 0;
    }
}

int burst_detector_is_locked(burst_detector_t *bd)
{
    return bd->locked;
}

void burst_detector_get_phase(burst_detector_t *bd, int32_t *phase)
{
    *phase = bd->phase_acc;
}

/*=========================================================================*/
/* Color Carrier Generator Implementation                                  */
/*=========================================================================*/

int cc_generator_init(cc_generator_t *cc, int sample_rate,
                      double subcarrier_freq, int cc_period, int line_length)
{
    int i, line;
    double phase;

    memset(cc, 0, sizeof(cc_generator_t));

    cc->cc_samples = 4;  /* 4fsc sampling */
    cc->cc_period = cc_period;

    /* Calculate table size: samples per line × number of lines for phase coherence */
    cc->ccf_size = line_length * cc_period;
    cc->ccf = calloc(cc->ccf_size, sizeof(int16_t));

    if (!cc->ccf) {
        return -1;
    }

    /* Generate color carrier lookup table */
    /* Table contains one complete vertical period of color carrier */
    for (line = 0; line < cc_period; line++) {
        for (i = 0; i < line_length; i++) {
            int idx = line * line_length + i;
            /* Calculate phase at this position */
            phase = 2.0 * M_PI * subcarrier_freq * i / sample_rate;
            /* Add line-to-line phase offset for proper vertical period */
            phase += 2.0 * M_PI * subcarrier_freq * line * line_length / sample_rate;
            cc->ccf[idx] = (int16_t)(sin(phase) * 32767.0);
        }
    }

    return 0;
}

void cc_generator_free(cc_generator_t *cc)
{
    if (cc->ccf) {
        free(cc->ccf);
        cc->ccf = NULL;
    }
}

void cc_generator_get_ref(cc_generator_t *cc, int sample, int line,
                          int16_t *ref_i, int16_t *ref_q)
{
    int line_mod = line % cc->cc_period;
    int line_length = cc->ccf_size / cc->cc_period;
    int idx = line_mod * line_length + (sample % line_length);

    /* For 4fsc sampling, quadrature is simply 1 sample offset */
    int idx_q = line_mod * line_length + ((sample + 1) % line_length);

    *ref_i = cc->ccf[idx];
    *ref_q = cc->ccf[idx_q];
}

void cc_generator_sync_to_burst(cc_generator_t *cc, int32_t phase)
{
    /* Adjust index based on detected burst phase */
    cc->ccf_index = (phase * cc->ccf_size / T14_2PI) & (cc->ccf_size - 1);
}

/*=========================================================================*/
/* 1H Delay Line Implementation                                            */
/*=========================================================================*/

int delay_1h_init(delay_1h_t *dl, int line_length)
{
    memset(dl, 0, sizeof(delay_1h_t));

    dl->line_length = line_length;
    dl->line_buffer = calloc(line_length, sizeof(int16_t));

    if (!dl->line_buffer) {
        return -1;
    }

    return 0;
}

void delay_1h_free(delay_1h_t *dl)
{
    if (dl->line_buffer) {
        free(dl->line_buffer);
        dl->line_buffer = NULL;
    }
}

void delay_1h_store(delay_1h_t *dl, const int16_t *line)
{
    memcpy(dl->line_buffer, line, dl->line_length * sizeof(int16_t));
    dl->valid = 1;
}

int16_t delay_1h_get(delay_1h_t *dl, int sample)
{
    if (!dl->valid || sample < 0 || sample >= dl->line_length) {
        return 0;
    }
    return dl->line_buffer[sample];
}

int delay_1h_is_valid(delay_1h_t *dl)
{
    return dl->valid;
}

/*=========================================================================*/
/* YUV to RGB Conversion (BT.601)                                          */
/* Uses fixed-point arithmetic for efficiency                              */
/*=========================================================================*/

void yuv_to_rgb_bt601(int16_t y, int16_t u, int16_t v,
                      uint8_t *r, uint8_t *g, uint8_t *b)
{
    /*
     * BT.601 YUV to RGB conversion:
     * R = Y + 1.402 * V
     * G = Y - 0.344 * U - 0.714 * V
     * B = Y + 1.772 * U
     *
     * Using 12-bit fixed point coefficients:
     * 1.402 * 4096 = 5743
     * 0.344 * 4096 = 1409
     * 0.714 * 4096 = 2925
     * 1.772 * 4096 = 7258
     */

    int32_t r_tmp, g_tmp, b_tmp;

    /* Y input is assumed to be in range -32768 to +32767 */
    /* Map to 0-255 range for output */
    int32_t y_scaled = (y + 32768) >> 8;

    /* U and V are in signed 16-bit, scale appropriately */
    r_tmp = y_scaled + ((v * 5743) >> 20);
    g_tmp = y_scaled - ((u * 1409) >> 20) - ((v * 2925) >> 20);
    b_tmp = y_scaled + ((u * 7258) >> 20);

    *r = (uint8_t)CLAMP(r_tmp, 0, 255);
    *g = (uint8_t)CLAMP(g_tmp, 0, 255);
    *b = (uint8_t)CLAMP(b_tmp, 0, 255);
}

/*=========================================================================*/
/* IQ to RGB Conversion (NTSC)                                             */
/* I and Q axes are at 33° and 123° respectively                           */
/*=========================================================================*/

void iq_to_rgb_ntsc(int16_t y, int16_t i, int16_t q,
                    uint8_t *r, uint8_t *g, uint8_t *b)
{
    /*
     * NTSC IQ to RGB conversion:
     * R = Y + 0.956 * I + 0.621 * Q
     * G = Y - 0.272 * I - 0.647 * Q
     * B = Y - 1.105 * I + 1.702 * Q
     *
     * Using 12-bit fixed point:
     * 0.956 * 4096 = 3916
     * 0.621 * 4096 = 2543
     * 0.272 * 4096 = 1114
     * 0.647 * 4096 = 2650
     * 1.105 * 4096 = 4526
     * 1.702 * 4096 = 6972
     */

    int32_t r_tmp, g_tmp, b_tmp;

    /* Map Y to 0-255 range */
    int32_t y_scaled = (y + 32768) >> 8;

    r_tmp = y_scaled + ((i * 3916) >> 20) + ((q * 2543) >> 20);
    g_tmp = y_scaled - ((i * 1114) >> 20) - ((q * 2650) >> 20);
    b_tmp = y_scaled - ((i * 4526) >> 20) + ((q * 6972) >> 20);

    *r = (uint8_t)CLAMP(r_tmp, 0, 255);
    *g = (uint8_t)CLAMP(g_tmp, 0, 255);
    *b = (uint8_t)CLAMP(b_tmp, 0, 255);
}

/*=========================================================================*/
/* PAL Decoder Implementation                                              */
/*=========================================================================*/

int pal_decoder_init(pal_decoder_t *dec, int sample_rate)
{
    memset(dec, 0, sizeof(pal_decoder_t));

    dec->sample_rate = sample_rate;

    /* Calculate line parameters for this sample rate */
    /* PAL line is 64µs */
    dec->line_length = (int)((double)sample_rate * 64e-6);

    /* Active video starts after sync + back porch (~10.5µs) */
    dec->active_start = (int)((double)sample_rate * 10.5e-6);

    /* Active video is ~52µs */
    dec->active_length = (int)((double)sample_rate * 52e-6);

    /* Initialize color carrier generator */
    /* PAL has 4-frame (8-field) color sequence for phase coherence */
    /* Simplified to 4 lines for practical implementation */
    if (cc_generator_init(&dec->cc_gen, sample_rate, PAL_FSC, 4, dec->line_length) != 0) {
        return -1;
    }

    /* Initialize burst detector */
    int burst_start = (int)((double)sample_rate * 5.6e-6);
    int burst_length = (int)((double)sample_rate * 2.25e-6);
    if (burst_detector_init(&dec->burst, sample_rate, PAL_FSC, burst_start, burst_length) != 0) {
        cc_generator_free(&dec->cc_gen);
        return -1;
    }

    /* Initialize 1H delay line */
    if (delay_1h_init(&dec->delay_line, dec->line_length) != 0) {
        burst_detector_free(&dec->burst);
        cc_generator_free(&dec->cc_gen);
        return -1;
    }

    /* Initialize equalizers */
    /* Luminance: emphasize low frequencies, slightly boost high for sharpness */
    eq_band3_init(&dec->y_eq, sample_rate, 500000.0, 3000000.0, 1.0, 1.0, 0.8);

    /* Chrominance: band-limited around subcarrier */
    eq_band3_init(&dec->uv_eq, sample_rate, 3500000.0, 5500000.0, 0.0, 1.0, 0.0);

    /* Default adjustment parameters */
    dec->hue = 0;
    dec->saturation = 65536;  /* 1.0 in fixed point */
    dec->brightness = 0;
    dec->contrast = 65536;    /* 1.0 in fixed point */

    dec->use_comb = 1;  /* Enable comb filter by default */

    return 0;
}

void pal_decoder_free(pal_decoder_t *dec)
{
    cc_generator_free(&dec->cc_gen);
    burst_detector_free(&dec->burst);
    delay_1h_free(&dec->delay_line);
}

void pal_decoder_set_params(pal_decoder_t *dec,
                            double hue, double saturation,
                            double brightness, double contrast)
{
    /* Hue in degrees (0-360), convert to T14 units */
    dec->hue = (int32_t)((hue / 360.0) * T14_2PI);

    /* Saturation, brightness, contrast as multipliers */
    dec->saturation = (int32_t)(saturation * 65536.0);
    dec->brightness = (int32_t)(brightness * 256.0);
    dec->contrast = (int32_t)(contrast * 65536.0);
}

void pal_decoder_decode_line(pal_decoder_t *dec, const int16_t *input,
                             uint32_t *rgb_out, int width)
{
    int x;
    int16_t y, u, v;
    uint8_t r, g, b;

    /* Process burst for this line */
    burst_detector_process(&dec->burst, input, dec->line_length);

    /* 4-sample quadrature demodulation (based on PAL-CRT approach) */
    /* At 4fsc sampling, samples are at 0°, 90°, 180°, 270° of carrier */

    for (x = 0; x < width; x++) {
        int sample_pos = dec->active_start + x;
        int16_t sample = input[sample_pos];
        int16_t prev_sample = 0;

        /* Get previous line sample for comb filter */
        if (dec->use_comb && delay_1h_is_valid(&dec->delay_line)) {
            prev_sample = delay_1h_get(&dec->delay_line, sample_pos);
        }

        /* === Comb Filter === */
        /* PAL: chroma phase inverts each line (V-switch) */
        /* Adding lines: Y+C + Y-C = 2Y (chroma cancels) */
        /* Subtracting: Y+C - (Y-C) = 2C (luma cancels) */
        int16_t luma_comb = 0;

        if (dec->use_comb && delay_1h_is_valid(&dec->delay_line)) {
            luma_comb = (sample + prev_sample) / 2;
        } else {
            luma_comb = sample;
        }

        /* === Extract Luminance === */
        y = eq_band3_process(&dec->y_eq, luma_comb);

        /* === Quadrature Demodulation (4-sample method) === */
        /* At 4fsc, phase alignment determines which samples are I and Q */
        int phase_align = POSMOD(dec->hsync + sample_pos, 4);

        /* Get 4 consecutive samples around this position */
        int16_t ccr[4];
        int i;
        for (i = 0; i < 4; i++) {
            int pos = sample_pos - 2 + i;
            if (pos >= 0 && pos < dec->line_length) {
                if (dec->use_comb && delay_1h_is_valid(&dec->delay_line)) {
                    int16_t curr = input[pos];
                    int16_t prev = delay_1h_get(&dec->delay_line, pos);
                    ccr[i] = (curr - prev) / 2;  /* Chroma only */
                } else {
                    ccr[i] = input[pos];
                }
            } else {
                ccr[i] = 0;
            }
        }

        /* Quadrature demodulation using 4-sample technique */
        /* I = sample[90°] - sample[270°] */
        /* Q = sample[180°] - sample[0°] */
        int32_t dcu = ccr[(phase_align + 1) & 3] - ccr[(phase_align + 3) & 3];
        int32_t dcv = ccr[(phase_align + 2) & 3] - ccr[(phase_align + 0) & 3];

        /* Apply PAL V-switch (alternating V phase) */
        if (!dec->v_switch) {
            dcv = -dcv;
        }

        /* Apply hue rotation */
        int32_t hue_sin = sin_lookup(dec->hue);
        int32_t hue_cos = cos_lookup(dec->hue);
        int32_t u_rot = (dcu * hue_cos - dcv * hue_sin) >> 15;
        int32_t v_rot = (dcv * hue_cos + dcu * hue_sin) >> 15;

        /* Apply saturation */
        u = (int16_t)((u_rot * dec->saturation) >> 16);
        v = (int16_t)((v_rot * dec->saturation) >> 16);

        /* Apply brightness and contrast to Y */
        int32_t y_adj = ((y * dec->contrast) >> 16) + dec->brightness;
        y = (int16_t)CLAMP(y_adj, INT16_MIN, INT16_MAX);

        /* Convert YUV to RGB */
        yuv_to_rgb_bt601(y, u, v, &r, &g, &b);

        /* Pack into 32-bit ARGB */
        rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
    }

    /* Store current line in delay buffer for next line's comb filter */
    delay_1h_store(&dec->delay_line, input);

    /* Toggle V-switch for next line */
    dec->v_switch = !dec->v_switch;

    /* Update line number */
    dec->line_number++;
}

void pal_decoder_new_field(pal_decoder_t *dec, int field)
{
    /* Reset line counter at start of field */
    dec->line_number = 0;

    /* V-switch phase depends on field */
    dec->v_switch = field;

    /* Clear delay line validity at field start */
    dec->delay_line.valid = 0;

    /* Reset equalizers */
    eq_band3_reset(&dec->y_eq);
    eq_band3_reset(&dec->uv_eq);
}

/*=========================================================================*/
/* NTSC Decoder Implementation                                             */
/*=========================================================================*/

int ntsc_decoder_init(ntsc_decoder_t *dec, int sample_rate)
{
    memset(dec, 0, sizeof(ntsc_decoder_t));

    dec->sample_rate = sample_rate;

    /* Calculate line parameters for this sample rate */
    /* NTSC line is 63.556µs */
    dec->line_length = (int)((double)sample_rate * 63.556e-6);

    /* Active video starts after sync + back porch (~9.5µs) */
    dec->active_start = (int)((double)sample_rate * 9.5e-6);

    /* Active video is ~52.6µs */
    dec->active_length = (int)((double)sample_rate * 52.6e-6);

    /* Initialize color carrier generator */
    /* NTSC has 2-line color sequence (525 lines alternating) */
    if (cc_generator_init(&dec->cc_gen, sample_rate, NTSC_FSC, 2, dec->line_length) != 0) {
        return -1;
    }

    /* Initialize burst detector */
    int burst_start = (int)((double)sample_rate * 5.3e-6);
    int burst_length = (int)((double)sample_rate * 2.5e-6);
    if (burst_detector_init(&dec->burst, sample_rate, NTSC_FSC, burst_start, burst_length) != 0) {
        cc_generator_free(&dec->cc_gen);
        return -1;
    }

    /* Initialize 1H delay line */
    if (delay_1h_init(&dec->delay_line, dec->line_length) != 0) {
        burst_detector_free(&dec->burst);
        cc_generator_free(&dec->cc_gen);
        return -1;
    }

    /* Initialize equalizers */
    /* Luminance: standard profile */
    eq_band3_init(&dec->y_eq, sample_rate, 400000.0, 2500000.0, 1.0, 1.0, 0.8);

    /* Chrominance: band-limited around subcarrier */
    eq_band3_init(&dec->iq_eq, sample_rate, 2500000.0, 4500000.0, 0.0, 1.0, 0.0);

    /* Default adjustment parameters */
    dec->hue = 0;
    dec->saturation = 65536;
    dec->brightness = 0;
    dec->contrast = 65536;

    dec->use_comb = 1;

    return 0;
}

void ntsc_decoder_free(ntsc_decoder_t *dec)
{
    cc_generator_free(&dec->cc_gen);
    burst_detector_free(&dec->burst);
    delay_1h_free(&dec->delay_line);
}

void ntsc_decoder_set_params(ntsc_decoder_t *dec,
                             double hue, double saturation,
                             double brightness, double contrast)
{
    dec->hue = (int32_t)((hue / 360.0) * T14_2PI);
    dec->saturation = (int32_t)(saturation * 65536.0);
    dec->brightness = (int32_t)(brightness * 256.0);
    dec->contrast = (int32_t)(contrast * 65536.0);
}

void ntsc_decoder_decode_line(ntsc_decoder_t *dec, const int16_t *input,
                              uint32_t *rgb_out, int width)
{
    int x;
    int16_t y, i_val, q_val;
    uint8_t r, g, b;

    /* Process burst for this line */
    burst_detector_process(&dec->burst, input, dec->line_length);

    for (x = 0; x < width; x++) {
        int sample_pos = dec->active_start + x;
        int16_t sample = input[sample_pos];
        int16_t prev_sample = 0;

        /* Get previous line sample for comb filter */
        if (dec->use_comb && delay_1h_is_valid(&dec->delay_line)) {
            prev_sample = delay_1h_get(&dec->delay_line, sample_pos);
        }

        /* === Comb Filter === */
        /* NTSC: chroma phase is consistent between lines at same H position */
        /* This allows simple comb filtering */
        int16_t luma_comb = 0;

        if (dec->use_comb && delay_1h_is_valid(&dec->delay_line)) {
            /* For NTSC, add lines to cancel chroma (180° phase shift line-to-line) */
            luma_comb = (sample + prev_sample) / 2;
        } else {
            luma_comb = sample;
        }

        /* === Extract Luminance === */
        y = eq_band3_process(&dec->y_eq, luma_comb);

        /* === Quadrature Demodulation (4-sample method) === */
        int phase_align = POSMOD(dec->hsync + sample_pos, 4);

        /* Get 4 consecutive samples for quadrature detection */
        int16_t ccr[4];
        int idx;
        for (idx = 0; idx < 4; idx++) {
            int pos = sample_pos - 2 + idx;
            if (pos >= 0 && pos < dec->line_length) {
                if (dec->use_comb && delay_1h_is_valid(&dec->delay_line)) {
                    int16_t curr = input[pos];
                    int16_t prev = delay_1h_get(&dec->delay_line, pos);
                    ccr[idx] = (curr - prev) / 2;
                } else {
                    ccr[idx] = input[pos];
                }
            } else {
                ccr[idx] = 0;
            }
        }

        /* I/Q demodulation using 4-sample technique */
        int32_t dci = ccr[(phase_align + 1) & 3] - ccr[(phase_align + 3) & 3];
        int32_t dcq = ccr[(phase_align + 2) & 3] - ccr[(phase_align + 0) & 3];

        /* Apply hue rotation */
        int32_t hue_sin = sin_lookup(dec->hue);
        int32_t hue_cos = cos_lookup(dec->hue);
        int32_t i_rot = (dci * hue_cos - dcq * hue_sin) >> 15;
        int32_t q_rot = (dcq * hue_cos + dci * hue_sin) >> 15;

        /* Apply saturation */
        i_val = (int16_t)((i_rot * dec->saturation) >> 16);
        q_val = (int16_t)((q_rot * dec->saturation) >> 16);

        /* Apply brightness and contrast to Y */
        int32_t y_adj = ((y * dec->contrast) >> 16) + dec->brightness;
        y = (int16_t)CLAMP(y_adj, INT16_MIN, INT16_MAX);

        /* Convert IQ to RGB using NTSC matrix */
        iq_to_rgb_ntsc(y, i_val, q_val, &r, &g, &b);

        /* Pack into 32-bit ARGB */
        rgb_out[x] = (0xFF << 24) | (r << 16) | (g << 8) | b;
    }

    /* Store current line for next line's comb filter */
    delay_1h_store(&dec->delay_line, input);

    /* Update line number */
    dec->line_number++;
}

void ntsc_decoder_new_field(ntsc_decoder_t *dec, int field)
{
    dec->line_number = 0;
    dec->delay_line.valid = 0;
    eq_band3_reset(&dec->y_eq);
    eq_band3_reset(&dec->iq_eq);
}

/*=========================================================================*/
/* Color Bars Generator Implementation                                     */
/* Generates EBU 75% or SMPTE color bars with proper modulated signal     */
/*=========================================================================*/

/* Standard EBU 75% color bar values (Y, U, V) */
static const int16_t pal_colorbars_yuv[8][3] = {
    { 16384,      0,      0},   /* White */
    { 12529, -11076,  10565},   /* Yellow */
    {  9830,  10565,  -4535},   /* Cyan */
    {  5975,   -511,   6030},   /* Green */
    {  2024,    511,  -6030},   /* Magenta */
    { -1681, -10565,   4535},   /* Red */
    { -5536,  11076, -10565},   /* Blue */
    {-16384,      0,      0}    /* Black */
};

/* NTSC SMPTE color bars (Y, I, Q) */
static const int16_t ntsc_colorbars_iq[8][3] = {
    { 16384,      0,      0},   /* White */
    { 12877,   6030,   8773},   /* Yellow */
    {  8474,  -8257,   3714},   /* Cyan */
    {  4967,  -2227,  12487},   /* Green */
    { -4967,   2227, -12487},   /* Magenta */
    { -8474,   8257,  -3714},   /* Red */
    {-12877,  -6030,  -8773},   /* Blue */
    {-16384,      0,      0}    /* Black */
};

int colorbars_gen_init(colorbars_gen_t *gen, color_system_t system, int sample_rate)
{
    memset(gen, 0, sizeof(colorbars_gen_t));

    gen->system = system;
    gen->sample_rate = sample_rate;

    if (system == COLOR_SYS_PAL) {
        gen->line_length = (int)((double)sample_rate * 64e-6);
        gen->active_start = (int)((double)sample_rate * 10.5e-6);
        gen->active_length = (int)((double)sample_rate * 52e-6);
        gen->phase_inc = (int32_t)((PAL_FSC / sample_rate) * T14_2PI);
    } else if (system == COLOR_SYS_NTSC) {
        gen->line_length = (int)((double)sample_rate * 63.556e-6);
        gen->active_start = (int)((double)sample_rate * 9.5e-6);
        gen->active_length = (int)((double)sample_rate * 52.6e-6);
        gen->phase_inc = (int32_t)((NTSC_FSC / sample_rate) * T14_2PI);
    } else {
        return -1;
    }

    gen->line_buffer = calloc(gen->line_length, sizeof(int16_t));
    if (!gen->line_buffer) {
        return -1;
    }

    return 0;
}

void colorbars_gen_free(colorbars_gen_t *gen)
{
    if (gen->line_buffer) {
        free(gen->line_buffer);
        gen->line_buffer = NULL;
    }
}

void colorbars_gen_line(colorbars_gen_t *gen, int16_t *output, int line_number)
{
    int x;
    int bar_width = gen->active_length / 8;

    /* Generate sync and blanking */
    int sync_end = (int)((double)gen->sample_rate * 4.7e-6);
    int burst_start, burst_end;

    if (gen->system == COLOR_SYS_PAL) {
        burst_start = (int)((double)gen->sample_rate * 5.6e-6);
        burst_end = burst_start + (int)((double)gen->sample_rate * 2.25e-6);
    } else {
        burst_start = (int)((double)gen->sample_rate * 5.3e-6);
        burst_end = burst_start + (int)((double)gen->sample_rate * 2.5e-6);
    }

    /* Initialize phase for this line */
    int32_t phase = gen->phase_acc;

    for (x = 0; x < gen->line_length; x++) {
        int16_t sample = 0;

        if (x < sync_end) {
            /* Sync tip */
            sample = SYNC_LEVEL >> 1;
        } else if (x < gen->active_start) {
            /* Blanking level */
            sample = 0;

            /* Add color burst */
            if (x >= burst_start && x < burst_end) {
                int32_t burst_phase = phase;
                if (gen->system == COLOR_SYS_PAL) {
                    /* PAL burst is at +/-135° from U axis */
                    burst_phase += T14_PI * 3 / 4;  /* 135° */
                } else {
                    /* NTSC burst is at 180° (along -B-Y) */
                    burst_phase += T14_PI;
                }
                sample = (sin_lookup(burst_phase) * BURST_LEVEL) >> 16;
            }
        } else if (x < gen->active_start + gen->active_length) {
            /* Active video - color bars */
            int active_x = x - gen->active_start;
            int bar_index = active_x / bar_width;
            if (bar_index > 7) bar_index = 7;

            int16_t y_level, u_level, v_level;
            int32_t chroma;

            if (gen->system == COLOR_SYS_PAL) {
                y_level = pal_colorbars_yuv[bar_index][0];
                u_level = pal_colorbars_yuv[bar_index][1];
                v_level = pal_colorbars_yuv[bar_index][2];

                /* PAL modulation: chroma = U*sin + V*cos (with V-switch) */
                int32_t sin_phase = sin_lookup(phase);
                int32_t cos_phase = cos_lookup(phase);

                /* Apply PAL V-switch */
                if (gen->v_switch) {
                    v_level = -v_level;
                }

                chroma = ((u_level * sin_phase) >> 15) + ((v_level * cos_phase) >> 15);
            } else {
                y_level = ntsc_colorbars_iq[bar_index][0];
                int16_t i_level = ntsc_colorbars_iq[bar_index][1];
                int16_t q_level = ntsc_colorbars_iq[bar_index][2];

                /* NTSC modulation: chroma = I*cos(33°)*sin + Q*sin(33°)*sin + ... */
                /* Simplified: use I on sin, Q on cos (with 33° offset baked in) */
                int32_t sin_phase = sin_lookup(phase);
                int32_t cos_phase = cos_lookup(phase);

                chroma = ((i_level * sin_phase) >> 15) + ((q_level * cos_phase) >> 15);
            }

            /* Combine luma and chroma */
            sample = (y_level >> 1) + (int16_t)(chroma >> 1);
        } else {
            /* Front porch */
            sample = 0;
        }

        output[x] = sample;

        /* Advance phase */
        phase = (phase + gen->phase_inc) & T14_MASK;
    }

    /* Store phase for next line */
    gen->phase_acc = phase;

    /* Toggle PAL V-switch */
    if (gen->system == COLOR_SYS_PAL) {
        gen->v_switch = !gen->v_switch;
    }

    gen->current_line++;
}

void colorbars_gen_reset(colorbars_gen_t *gen)
{
    gen->current_line = 0;
    gen->current_frame = 0;
    gen->phase_acc = 0;
    gen->v_switch = 0;
}

/*=========================================================================*/
/* High-Level Frame Decode Function                                        */
/*=========================================================================*/

int color_decode_frame(color_system_t system, void *decoder,
                       const int16_t *input, int input_stride,
                       uint32_t *rgb_out, int width, int height)
{
    int line;

    if (system == COLOR_SYS_PAL) {
        pal_decoder_t *dec = (pal_decoder_t *)decoder;

        for (line = 0; line < height; line++) {
            const int16_t *line_in = input + (line * input_stride);
            uint32_t *line_out = rgb_out + (line * width);

            pal_decoder_decode_line(dec, line_in, line_out, width);
        }

    } else if (system == COLOR_SYS_NTSC) {
        ntsc_decoder_t *dec = (ntsc_decoder_t *)decoder;

        for (line = 0; line < height; line++) {
            const int16_t *line_in = input + (line * input_stride);
            uint32_t *line_out = rgb_out + (line * width);

            ntsc_decoder_decode_line(dec, line_in, line_out, width);
        }
    } else {
        return -1;
    }

    return 0;
}
