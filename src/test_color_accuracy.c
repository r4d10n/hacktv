/* test_color_accuracy.c - Comprehensive Color Accuracy Testing              */
/*=========================================================================*/
/* Measures deltaE color accuracy for PAL and NTSC encode/decode           */
/*=========================================================================*/
/* Copyright 2025 - Licensed under GNU GPL v3                              */
/*=========================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include "color_decode.h"

/*=========================================================================*/
/* Color Accuracy Metrics                                                  */
/*=========================================================================*/

/* sRGB to XYZ conversion */
static void srgb_to_xyz(double r, double g, double b, double *x, double *y, double *z)
{
    /* Linearize sRGB */
    r = r / 255.0;
    g = g / 255.0;
    b = b / 255.0;

    r = (r > 0.04045) ? pow((r + 0.055) / 1.055, 2.4) : r / 12.92;
    g = (g > 0.04045) ? pow((g + 0.055) / 1.055, 2.4) : g / 12.92;
    b = (b > 0.04045) ? pow((b + 0.055) / 1.055, 2.4) : b / 12.92;

    /* sRGB to XYZ (D65) */
    *x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375;
    *y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750;
    *z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041;
}

/* XYZ to L*a*b* conversion */
static void xyz_to_lab(double x, double y, double z, double *L, double *a, double *b_out)
{
    /* D65 white point */
    const double xn = 0.95047;
    const double yn = 1.00000;
    const double zn = 1.08883;

    double fx, fy, fz;
    double xr = x / xn;
    double yr = y / yn;
    double zr = z / zn;

    const double epsilon = 0.008856;
    const double kappa = 903.3;

    fx = (xr > epsilon) ? pow(xr, 1.0/3.0) : (kappa * xr + 16.0) / 116.0;
    fy = (yr > epsilon) ? pow(yr, 1.0/3.0) : (kappa * yr + 16.0) / 116.0;
    fz = (zr > epsilon) ? pow(zr, 1.0/3.0) : (kappa * zr + 16.0) / 116.0;

    *L = 116.0 * fy - 16.0;
    *a = 500.0 * (fx - fy);
    *b_out = 200.0 * (fy - fz);
}

/* Calculate Delta E (CIE76) */
static double delta_e(double r1, double g1, double b1,
                      double r2, double g2, double b2)
{
    double x1, y1, z1, L1, a1, b1_lab;
    double x2, y2, z2, L2, a2, b2_lab;

    srgb_to_xyz(r1, g1, b1, &x1, &y1, &z1);
    xyz_to_lab(x1, y1, z1, &L1, &a1, &b1_lab);

    srgb_to_xyz(r2, g2, b2, &x2, &y2, &z2);
    xyz_to_lab(x2, y2, z2, &L2, &a2, &b2_lab);

    double dL = L1 - L2;
    double da = a1 - a2;
    double db = b1_lab - b2_lab;

    return sqrt(dL * dL + da * da + db * db);
}

/*=========================================================================*/
/* Test Cases                                                              */
/*=========================================================================*/

/* 75% EBU color bars */
static const uint8_t colorbar_rgb[8][3] = {
    {191, 191, 191},  /* White */
    {191, 191,   0},  /* Yellow */
    {  0, 191, 191},  /* Cyan */
    {  0, 191,   0},  /* Green */
    {191,   0, 191},  /* Magenta */
    {191,   0,   0},  /* Red */
    {  0,   0, 191},  /* Blue */
    {  0,   0,   0}   /* Black */
};

static const char *colorbar_names[8] = {
    "White", "Yellow", "Cyan", "Green",
    "Magenta", "Red", "Blue", "Black"
};

/* Additional test colors for more comprehensive testing */
static const uint8_t test_colors[][3] = {
    /* Flesh tones */
    {255, 224, 189},  /* Light skin */
    {198, 134, 66},   /* Dark skin */

    /* Primaries at various levels */
    {255, 0, 0},      /* Pure red */
    {0, 255, 0},      /* Pure green */
    {0, 0, 255},      /* Pure blue */

    /* Saturated colors */
    {255, 255, 0},    /* Yellow 100% */
    {0, 255, 255},    /* Cyan 100% */
    {255, 0, 255},    /* Magenta 100% */

    /* Grayscale ramp */
    {32, 32, 32},     /* Dark gray */
    {64, 64, 64},     /* Gray 25% */
    {128, 128, 128},  /* Gray 50% */
    {192, 192, 192},  /* Gray 75% */
    {224, 224, 224},  /* Light gray */

    /* Muted colors */
    {128, 96, 64},    /* Brown */
    {64, 96, 128},    /* Steel blue */
    {96, 128, 64},    /* Olive */
    {128, 64, 96},    /* Mauve */
};

#define NUM_TEST_COLORS (sizeof(test_colors) / sizeof(test_colors[0]))

/*=========================================================================*/
/* PAL Color Bar Accuracy Test                                             */
/*=========================================================================*/

int test_pal_colorbar_accuracy(void)
{
    colorbars_gen_t gen;
    pal_decoder_t dec;
    int bar, line;
    int height = 288;  /* Full field - match visual test */
    double max_de = 0.0, avg_de = 0.0, total_de = 0.0;
    int count = 0;

    printf("\n=== PAL Color Bar Accuracy Test ===\n\n");

    if (colorbars_gen_init(&gen, COLOR_SYS_PAL, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init PAL generator\n");
        return -1;
    }

    if (pal_decoder_init(&dec, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init PAL decoder\n");
        colorbars_gen_free(&gen);
        return -1;
    }

    int width = gen.active_length;
    int bar_width = width / 8;

    int16_t *encoded_line = calloc(gen.line_length, sizeof(int16_t));
    uint32_t *framebuffer = calloc(width * height, sizeof(uint32_t));
    uint32_t *decoded_line = calloc(width, sizeof(uint32_t));

    if (!encoded_line || !framebuffer || !decoded_line) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    colorbars_gen_reset(&gen);
    pal_decoder_new_field(&dec, 0);

    /* Decode all lines into framebuffer (like visual test) */
    for (line = 0; line < height; line++) {
        colorbars_gen_line(&gen, encoded_line, line);
        pal_decoder_decode_line(&dec, encoded_line, decoded_line, width);
        memcpy(&framebuffer[line * width], decoded_line, width * sizeof(uint32_t));
    }

    /* Sample center of each bar from middle line (like visual test) */
    int sample_y = height / 2;
    int bar_samples[8][3] = {{0}};
    int sample_counts[8] = {0};

    for (bar = 0; bar < 8; bar++) {
        int sample_x = bar * bar_width + bar_width / 2;
        if (sample_x >= 0 && sample_x < width) {
            uint32_t pixel = framebuffer[sample_y * width + sample_x];
            bar_samples[bar][0] = (pixel >> 16) & 0xFF;
            bar_samples[bar][1] = (pixel >> 8) & 0xFF;
            bar_samples[bar][2] = pixel & 0xFF;
            sample_counts[bar] = 1;
        }
    }

    /* Calculate and print results */
    printf("%-10s  Expected     Decoded      Delta     DeltaE\n", "Color");
    printf("----------  -----------  -----------  --------  ------\n");

    for (bar = 0; bar < 8; bar++) {
        int avg_r = bar_samples[bar][0] / sample_counts[bar];
        int avg_g = bar_samples[bar][1] / sample_counts[bar];
        int avg_b = bar_samples[bar][2] / sample_counts[bar];

        int exp_r = colorbar_rgb[bar][0];
        int exp_g = colorbar_rgb[bar][1];
        int exp_b = colorbar_rgb[bar][2];

        int dr = avg_r - exp_r;
        int dg = avg_g - exp_g;
        int db = avg_b - exp_b;

        double de = delta_e(exp_r, exp_g, exp_b, avg_r, avg_g, avg_b);

        printf("%-10s  %3d,%3d,%3d  %3d,%3d,%3d  %+3d,%+3d,%+3d   %5.2f\n",
               colorbar_names[bar],
               exp_r, exp_g, exp_b,
               avg_r, avg_g, avg_b,
               dr, dg, db, de);

        if (de > max_de) max_de = de;
        total_de += de;
        count++;
    }

    avg_de = total_de / count;
    printf("\nPAL Summary: Avg DeltaE = %.2f, Max DeltaE = %.2f\n", avg_de, max_de);

    /* Quality assessment */
    if (max_de < 1.0) {
        printf("Quality: EXCELLENT (perceptually identical)\n");
    } else if (max_de < 2.5) {
        printf("Quality: VERY GOOD (imperceptible difference)\n");
    } else if (max_de < 5.0) {
        printf("Quality: GOOD (subtle difference)\n");
    } else if (max_de < 10.0) {
        printf("Quality: ACCEPTABLE (noticeable difference)\n");
    } else {
        printf("Quality: POOR (obvious difference)\n");
    }

    free(encoded_line);
    free(decoded_line);
    free(framebuffer);
    colorbars_gen_free(&gen);
    pal_decoder_free(&dec);

    return (max_de < 10.0) ? 0 : -1;
}

/*=========================================================================*/
/* NTSC Color Bar Accuracy Test                                            */
/*=========================================================================*/

int test_ntsc_colorbar_accuracy(void)
{
    colorbars_gen_t gen;
    ntsc_decoder_t dec;
    int bar, line;
    int height = 240;  /* Full field - match visual test */
    double max_de = 0.0, avg_de = 0.0, total_de = 0.0;
    int count = 0;

    printf("\n=== NTSC Color Bar Accuracy Test ===\n\n");

    if (colorbars_gen_init(&gen, COLOR_SYS_NTSC, NTSC_4FSC) != 0) {
        fprintf(stderr, "Failed to init NTSC generator\n");
        return -1;
    }

    if (ntsc_decoder_init(&dec, NTSC_4FSC) != 0) {
        fprintf(stderr, "Failed to init NTSC decoder\n");
        colorbars_gen_free(&gen);
        return -1;
    }

    int width = gen.active_length;
    int bar_width = width / 8;

    int16_t *encoded_line = calloc(gen.line_length, sizeof(int16_t));
    uint32_t *framebuffer = calloc(width * height, sizeof(uint32_t));
    uint32_t *decoded_line = calloc(width, sizeof(uint32_t));

    if (!encoded_line || !framebuffer || !decoded_line) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    colorbars_gen_reset(&gen);
    ntsc_decoder_new_field(&dec, 0);

    /* Decode all lines into framebuffer (like visual test) */
    for (line = 0; line < height; line++) {
        colorbars_gen_line(&gen, encoded_line, line);
        ntsc_decoder_decode_line(&dec, encoded_line, decoded_line, width);
        memcpy(&framebuffer[line * width], decoded_line, width * sizeof(uint32_t));
    }

    /* Sample center of each bar from middle line (like visual test) */
    int sample_y = height / 2;
    int bar_samples[8][3] = {{0}};
    int sample_counts[8] = {0};

    for (bar = 0; bar < 8; bar++) {
        int sample_x = bar * bar_width + bar_width / 2;
        if (sample_x >= 0 && sample_x < width) {
            uint32_t pixel = framebuffer[sample_y * width + sample_x];
            bar_samples[bar][0] = (pixel >> 16) & 0xFF;
            bar_samples[bar][1] = (pixel >> 8) & 0xFF;
            bar_samples[bar][2] = pixel & 0xFF;
            sample_counts[bar] = 1;
        }
    }

    printf("%-10s  Expected     Decoded      Delta     DeltaE\n", "Color");
    printf("----------  -----------  -----------  --------  ------\n");

    for (bar = 0; bar < 8; bar++) {
        int avg_r = bar_samples[bar][0] / sample_counts[bar];
        int avg_g = bar_samples[bar][1] / sample_counts[bar];
        int avg_b = bar_samples[bar][2] / sample_counts[bar];

        int exp_r = colorbar_rgb[bar][0];
        int exp_g = colorbar_rgb[bar][1];
        int exp_b = colorbar_rgb[bar][2];

        int dr = avg_r - exp_r;
        int dg = avg_g - exp_g;
        int db = avg_b - exp_b;

        double de = delta_e(exp_r, exp_g, exp_b, avg_r, avg_g, avg_b);

        printf("%-10s  %3d,%3d,%3d  %3d,%3d,%3d  %+3d,%+3d,%+3d   %5.2f\n",
               colorbar_names[bar],
               exp_r, exp_g, exp_b,
               avg_r, avg_g, avg_b,
               dr, dg, db, de);

        if (de > max_de) max_de = de;
        total_de += de;
        count++;
    }

    avg_de = total_de / count;
    printf("\nNTSC Summary: Avg DeltaE = %.2f, Max DeltaE = %.2f\n", avg_de, max_de);

    if (max_de < 1.0) {
        printf("Quality: EXCELLENT (perceptually identical)\n");
    } else if (max_de < 2.5) {
        printf("Quality: VERY GOOD (imperceptible difference)\n");
    } else if (max_de < 5.0) {
        printf("Quality: GOOD (subtle difference)\n");
    } else if (max_de < 10.0) {
        printf("Quality: ACCEPTABLE (noticeable difference)\n");
    } else {
        printf("Quality: POOR (obvious difference)\n");
    }

    free(encoded_line);
    free(decoded_line);
    free(framebuffer);
    colorbars_gen_free(&gen);
    ntsc_decoder_free(&dec);

    return (max_de < 10.0) ? 0 : -1;
}

/*=========================================================================*/
/* Multi-Line Stability Test                                               */
/*=========================================================================*/

int test_line_stability(void)
{
    colorbars_gen_t pal_gen, ntsc_gen;
    pal_decoder_t pal_dec;
    ntsc_decoder_t ntsc_dec;
    int line;
    int height = 288;  /* Full field */

    printf("\n=== Line-to-Line Stability Test ===\n\n");

    /* Initialize PAL */
    if (colorbars_gen_init(&pal_gen, COLOR_SYS_PAL, PAL_4FSC) != 0 ||
        pal_decoder_init(&pal_dec, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init PAL\n");
        return -1;
    }

    /* Initialize NTSC */
    if (colorbars_gen_init(&ntsc_gen, COLOR_SYS_NTSC, NTSC_4FSC) != 0 ||
        ntsc_decoder_init(&ntsc_dec, NTSC_4FSC) != 0) {
        fprintf(stderr, "Failed to init NTSC\n");
        return -1;
    }

    int pal_width = pal_gen.active_length;
    int ntsc_width = ntsc_gen.active_length;

    int16_t *pal_encoded = calloc(pal_gen.line_length, sizeof(int16_t));
    uint32_t *pal_decoded = calloc(pal_width, sizeof(uint32_t));
    int16_t *ntsc_encoded = calloc(ntsc_gen.line_length, sizeof(int16_t));
    uint32_t *ntsc_decoded = calloc(ntsc_width, sizeof(uint32_t));

    if (!pal_encoded || !pal_decoded || !ntsc_encoded || !ntsc_decoded) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    colorbars_gen_reset(&pal_gen);
    colorbars_gen_reset(&ntsc_gen);
    pal_decoder_new_field(&pal_dec, 0);
    ntsc_decoder_new_field(&ntsc_dec, 0);

    /* Track min/max values for white bar */
    int pal_r_min = 255, pal_r_max = 0;
    int pal_g_min = 255, pal_g_max = 0;
    int pal_b_min = 255, pal_b_max = 0;

    int ntsc_r_min = 255, ntsc_r_max = 0;
    int ntsc_g_min = 255, ntsc_g_max = 0;
    int ntsc_b_min = 255, ntsc_b_max = 0;

    int pal_bar_center = pal_width / 16;  /* Center of white bar */
    int ntsc_bar_center = ntsc_width / 16;

    for (line = 0; line < height; line++) {
        /* PAL */
        colorbars_gen_line(&pal_gen, pal_encoded, line);
        pal_decoder_decode_line(&pal_dec, pal_encoded, pal_decoded, pal_width);

        uint32_t pal_pixel = pal_decoded[pal_bar_center];
        int pal_r = (pal_pixel >> 16) & 0xFF;
        int pal_g = (pal_pixel >> 8) & 0xFF;
        int pal_b = pal_pixel & 0xFF;

        if (pal_r < pal_r_min) pal_r_min = pal_r;
        if (pal_r > pal_r_max) pal_r_max = pal_r;
        if (pal_g < pal_g_min) pal_g_min = pal_g;
        if (pal_g > pal_g_max) pal_g_max = pal_g;
        if (pal_b < pal_b_min) pal_b_min = pal_b;
        if (pal_b > pal_b_max) pal_b_max = pal_b;

        /* NTSC */
        if (line < 240) {
            colorbars_gen_line(&ntsc_gen, ntsc_encoded, line);
            ntsc_decoder_decode_line(&ntsc_dec, ntsc_encoded, ntsc_decoded, ntsc_width);

            uint32_t ntsc_pixel = ntsc_decoded[ntsc_bar_center];
            int ntsc_r = (ntsc_pixel >> 16) & 0xFF;
            int ntsc_g = (ntsc_pixel >> 8) & 0xFF;
            int ntsc_b = ntsc_pixel & 0xFF;

            if (ntsc_r < ntsc_r_min) ntsc_r_min = ntsc_r;
            if (ntsc_r > ntsc_r_max) ntsc_r_max = ntsc_r;
            if (ntsc_g < ntsc_g_min) ntsc_g_min = ntsc_g;
            if (ntsc_g > ntsc_g_max) ntsc_g_max = ntsc_g;
            if (ntsc_b < ntsc_b_min) ntsc_b_min = ntsc_b;
            if (ntsc_b > ntsc_b_max) ntsc_b_max = ntsc_b;
        }
    }

    printf("White bar (expected 191,191,191) stability over %d lines:\n\n", height);

    printf("PAL:\n");
    printf("  R: min=%3d max=%3d range=%d\n", pal_r_min, pal_r_max, pal_r_max - pal_r_min);
    printf("  G: min=%3d max=%3d range=%d\n", pal_g_min, pal_g_max, pal_g_max - pal_g_min);
    printf("  B: min=%3d max=%3d range=%d\n", pal_b_min, pal_b_max, pal_b_max - pal_b_min);

    int pal_stable = (pal_r_max - pal_r_min <= 5) &&
                     (pal_g_max - pal_g_min <= 5) &&
                     (pal_b_max - pal_b_min <= 5);
    printf("  Stability: %s\n\n", pal_stable ? "PASS" : "FAIL");

    printf("NTSC:\n");
    printf("  R: min=%3d max=%3d range=%d\n", ntsc_r_min, ntsc_r_max, ntsc_r_max - ntsc_r_min);
    printf("  G: min=%3d max=%3d range=%d\n", ntsc_g_min, ntsc_g_max, ntsc_g_max - ntsc_g_min);
    printf("  B: min=%3d max=%3d range=%d\n", ntsc_b_min, ntsc_b_max, ntsc_b_max - ntsc_b_min);

    int ntsc_stable = (ntsc_r_max - ntsc_r_min <= 5) &&
                      (ntsc_g_max - ntsc_g_min <= 5) &&
                      (ntsc_b_max - ntsc_b_min <= 5);
    printf("  Stability: %s\n", ntsc_stable ? "PASS" : "FAIL");

    free(pal_encoded);
    free(pal_decoded);
    free(ntsc_encoded);
    free(ntsc_decoded);
    colorbars_gen_free(&pal_gen);
    colorbars_gen_free(&ntsc_gen);
    pal_decoder_free(&pal_dec);
    ntsc_decoder_free(&ntsc_dec);

    return (pal_stable && ntsc_stable) ? 0 : -1;
}

/*=========================================================================*/
/* Edge Transition Test                                                    */
/*=========================================================================*/

int test_edge_transitions(void)
{
    colorbars_gen_t gen;
    pal_decoder_t dec;
    int x;

    printf("\n=== Edge Transition Test (PAL) ===\n\n");

    if (colorbars_gen_init(&gen, COLOR_SYS_PAL, PAL_4FSC) != 0 ||
        pal_decoder_init(&dec, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init\n");
        return -1;
    }

    int width = gen.active_length;
    int bar_width = width / 8;

    int16_t *encoded_line = calloc(gen.line_length, sizeof(int16_t));
    uint32_t *decoded_line = calloc(width, sizeof(uint32_t));

    if (!encoded_line || !decoded_line) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    colorbars_gen_reset(&gen);
    pal_decoder_new_field(&dec, 0);

    /* Generate a few lines to let the decoder stabilize */
    int line;
    for (line = 0; line < 10; line++) {
        colorbars_gen_line(&gen, encoded_line, line);
        pal_decoder_decode_line(&dec, encoded_line, decoded_line, width);
    }

    /* Check transition from white to yellow */
    int transition_x = bar_width;  /* Edge between bar 0 and bar 1 */

    printf("White->Yellow transition at x=%d:\n", transition_x);
    printf("Position   R    G    B   Expected\n");
    printf("--------   ---  ---  ---  --------\n");

    for (x = transition_x - 5; x <= transition_x + 5; x++) {
        if (x >= 0 && x < width) {
            uint32_t pixel = decoded_line[x];
            int r = (pixel >> 16) & 0xFF;
            int g = (pixel >> 8) & 0xFF;
            int b = pixel & 0xFF;

            const char *expected = (x < transition_x) ? "White" : "Yellow";
            printf("x=%4d     %3d  %3d  %3d  %s\n", x, r, g, b, expected);
        }
    }

    /* Check for ringing (>10% overshoot) */
    int overshoot_detected = 0;
    for (x = transition_x - 10; x <= transition_x + 10; x++) {
        if (x >= 0 && x < width) {
            uint32_t pixel = decoded_line[x];
            int r = (pixel >> 16) & 0xFF;
            int g = (pixel >> 8) & 0xFF;
            int b = pixel & 0xFF;

            if (r > 210 || g > 210 || b > 25 ||
                r < -20 || g < -20 || b < -20) {
                overshoot_detected = 1;
            }
        }
    }

    printf("\nRinging/overshoot: %s\n", overshoot_detected ? "DETECTED" : "MINIMAL");

    free(encoded_line);
    free(decoded_line);
    colorbars_gen_free(&gen);
    pal_decoder_free(&dec);

    return 0;
}

/*=========================================================================*/
/* Main                                                                    */
/*=========================================================================*/

int main(int argc, char *argv[])
{
    int result = 0;

    printf("================================================\n");
    printf("Comprehensive Color Accuracy Test Suite\n");
    printf("Based on PAL-CRT/NTSC-CRT Reference\n");
    printf("================================================\n");

    if (test_pal_colorbar_accuracy() != 0) {
        result = -1;
    }

    if (test_ntsc_colorbar_accuracy() != 0) {
        result = -1;
    }

    if (test_line_stability() != 0) {
        result = -1;
    }

    test_edge_transitions();

    printf("\n================================================\n");
    if (result == 0) {
        printf("All tests PASSED!\n");
    } else {
        printf("Some tests FAILED!\n");
    }
    printf("================================================\n");

    return result;
}
