/* test_colorbars_visual.c - Visual Test for Color Bars                    */
/*=========================================================================*/
/* Generates PPM image files to visually verify color decoding quality     */
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
/* Write PPM Image File                                                    */
/*=========================================================================*/

int write_ppm(const char *filename, uint32_t *pixels, int width, int height)
{
    FILE *f = fopen(filename, "wb");
    if (!f) {
        fprintf(stderr, "Failed to open %s for writing\n", filename);
        return -1;
    }

    /* Write PPM header */
    fprintf(f, "P6\n%d %d\n255\n", width, height);

    /* Write pixel data (RGB) */
    int x, y;
    for (y = 0; y < height; y++) {
        for (x = 0; x < width; x++) {
            uint32_t pixel = pixels[y * width + x];
            uint8_t r = (pixel >> 16) & 0xFF;
            uint8_t g = (pixel >> 8) & 0xFF;
            uint8_t b = pixel & 0xFF;
            fputc(r, f);
            fputc(g, f);
            fputc(b, f);
        }
    }

    fclose(f);
    printf("Wrote %s (%dx%d)\n", filename, width, height);
    return 0;
}

/*=========================================================================*/
/* Direct YUV to RGB Test (No Encoding)                                    */
/*=========================================================================*/

extern void yuv_to_rgb_bt601(int16_t y, int16_t u, int16_t v,
                             uint8_t *r, uint8_t *g, uint8_t *b);

/* PAL colorbar values - copy from color_decode.c (scale 56) */
static const int16_t test_pal_yuv[8][3] = {
    { 16128,      0,      0},   /* White  (191,191,191) Y=191 */
    { 10547,  -5337,    879},   /* Yellow (191,191,  0) Y=169 */
    {  1510,   1799,  -5347},   /* Cyan   (  0,191,191) Y=134 */
    { -4070,  -3539,  -4475},   /* Green  (  0,191,  0) Y=112 */
    {-12570,   3539,   4475},   /* Magenta(191,  0,191) Y= 79 */
    {-18150,  -1799,   5347},   /* Red    (191,  0,  0) Y= 57 */
    {-27187,   5337,   -879},   /* Blue   (  0,  0,191) Y= 22 */
    {-32768,      0,      0}    /* Black  (  0,  0,  0) Y=  0 */
};

void test_direct_yuv_to_rgb(void)
{
    const char *names[8] = {"White", "Yellow", "Cyan", "Green",
                           "Magenta", "Red", "Blue", "Black"};
    printf("\n=== Direct YUV to RGB Test (no encoding) ===\n");
    printf("Testing colorbar table values directly:\n\n");

    for (int i = 0; i < 8; i++) {
        int16_t y = test_pal_yuv[i][0];
        int16_t u = test_pal_yuv[i][1];
        int16_t v = test_pal_yuv[i][2];
        uint8_t r, g, b;

        yuv_to_rgb_bt601(y, u, v, &r, &g, &b);

        printf("  %8s: Y=%6d U=%6d V=%6d -> R=%3d G=%3d B=%3d\n",
               names[i], y, u, v, r, g, b);
    }
    printf("\n");
}

/*=========================================================================*/
/* Debug: Test single line encode/decode                                    */
/*=========================================================================*/

void test_single_line_debug(void)
{
    colorbars_gen_t gen;
    int16_t *encoded_line;
    int bar_width;

    printf("\n=== Single Line Encode Debug (Line 0) ===\n");

    if (colorbars_gen_init(&gen, COLOR_SYS_PAL, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init generator\n");
        return;
    }

    encoded_line = calloc(gen.line_length, sizeof(int16_t));
    if (!encoded_line) {
        colorbars_gen_free(&gen);
        return;
    }

    colorbars_gen_reset(&gen);
    colorbars_gen_line(&gen, encoded_line, 0);  /* Generate line 0 (first after reset) */

    bar_width = gen.active_length / 8;
    printf("Line length: %d, Active start: %d, Active length: %d, Bar width: %d\n",
           gen.line_length, gen.active_start, gen.active_length, bar_width);

    /* Test theoretical values for Yellow at position 186 (start of active area) */
    /* At x=186, phase should be 186 * phase_inc = 186 * 4096 = 761856 mod 16384 = 8192 = π */
    printf("\nFor Yellow (bar 1):\n");
    printf("  Table values (scale 56): Y=%d, U=%d, V=%d\n", 10547, -5337, 879);

    /* At phase π: sin=0, cos=-1 */
    /* chroma = U*0 + V*(-1) = -879 */
    /* expected sample = Y + chroma = 10547 - 879 = 9668 */
    printf("  At phase π (180°): sin=0, cos=-1, expected sample = 10547 - 879 = 9668\n");

    /* Sample 4 consecutive positions in bar 1 */
    int bar1_start = gen.active_start + bar_width;  /* Start of bar 1 */
    printf("  Samples at bar 1 start (x=%d): %d, %d, %d, %d\n",
           bar1_start,
           encoded_line[bar1_start],
           encoded_line[bar1_start + 1],
           encoded_line[bar1_start + 2],
           encoded_line[bar1_start + 3]);

    /* Manual Y extraction */
    int32_t s0 = encoded_line[bar1_start];
    int32_t s1 = encoded_line[bar1_start + 1];
    int32_t s2 = encoded_line[bar1_start + 2];
    int32_t s3 = encoded_line[bar1_start + 3];
    int32_t y_ext = (s0 + s1 + s2 + s3) >> 2;
    printf("  Y_extracted = (%d + %d + %d + %d)/4 = %d (expected ~10547)\n",
           (int)s0, (int)s1, (int)s2, (int)s3, (int)y_ext);

    /* Sample composite signal at center of each bar */
    printf("\nComposite signal samples at bar centers:\n");
    for (int bar = 0; bar < 8; bar++) {
        int center_x = gen.active_start + bar * bar_width + bar_width / 2;
        s0 = encoded_line[center_x];
        s1 = encoded_line[center_x + 1];
        s2 = encoded_line[center_x + 2];
        s3 = encoded_line[center_x + 3];
        y_ext = (s0 + s1 + s2 + s3) >> 2;
        printf("  Bar %d at x=%d: s[0..3] = %6d, %6d, %6d, %6d | Y_ext=%6d\n",
               bar, center_x, (int)s0, (int)s1, (int)s2, (int)s3, (int)y_ext);
    }

    free(encoded_line);
    colorbars_gen_free(&gen);
}

/*=========================================================================*/
/* Generate and Decode PAL Color Bars                                      */
/*=========================================================================*/

int test_pal_visual(void)
{
    colorbars_gen_t gen;
    pal_decoder_t dec;
    int line;
    int height = 288;  /* Half-height (one field) */
    int width;

    printf("\n=== PAL Color Bars Visual Test ===\n");

    /* Initialize generator and decoder at 4fsc */
    if (colorbars_gen_init(&gen, COLOR_SYS_PAL, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init PAL generator\n");
        return -1;
    }

    if (pal_decoder_init(&dec, PAL_4FSC) != 0) {
        fprintf(stderr, "Failed to init PAL decoder\n");
        colorbars_gen_free(&gen);
        return -1;
    }

    width = gen.active_length;
    printf("PAL: %d x %d at %d Hz sample rate\n", width, height, PAL_4FSC);

    /* Allocate buffers */
    int16_t *encoded_line = calloc(gen.line_length, sizeof(int16_t));
    uint32_t *framebuffer = calloc(width * height, sizeof(uint32_t));
    uint32_t *decoded_line = calloc(width, sizeof(uint32_t));

    if (!encoded_line || !framebuffer || !decoded_line) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    /* Reset generator and decoder */
    colorbars_gen_reset(&gen);
    pal_decoder_new_field(&dec, 0);

    /* Generate and decode frame */
    for (line = 0; line < height; line++) {
        /* Generate encoded color bars line */
        colorbars_gen_line(&gen, encoded_line, line);

        /* Decode line */
        pal_decoder_decode_line(&dec, encoded_line, decoded_line, width);

        /* Copy to framebuffer */
        memcpy(&framebuffer[line * width], decoded_line, width * sizeof(uint32_t));
    }

    /* Write output image */
    write_ppm("pal_colorbars.ppm", framebuffer, width, height);

    /* Analyze color bar values */
    printf("\nPAL Color Bar Analysis (center of each bar):\n");
    int bar_width = width / 8;
    int sample_y = height / 2;  /* Middle of frame */

    int bar;
    for (bar = 0; bar < 8; bar++) {
        int sample_x = bar * bar_width + bar_width / 2;
        uint32_t pixel = framebuffer[sample_y * width + sample_x];
        int r = (pixel >> 16) & 0xFF;
        int g = (pixel >> 8) & 0xFF;
        int b = pixel & 0xFF;
        printf("  Bar %d: R=%3d G=%3d B=%3d\n", bar, r, g, b);
    }

    /* Cleanup */
    free(encoded_line);
    free(decoded_line);
    free(framebuffer);
    colorbars_gen_free(&gen);
    pal_decoder_free(&dec);

    return 0;
}

/*=========================================================================*/
/* Generate and Decode NTSC Color Bars                                     */
/*=========================================================================*/

int test_ntsc_visual(void)
{
    colorbars_gen_t gen;
    ntsc_decoder_t dec;
    int line;
    int height = 240;  /* Half-height (one field) */
    int width;

    printf("\n=== NTSC Color Bars Visual Test ===\n");

    /* Initialize generator and decoder at 4fsc */
    if (colorbars_gen_init(&gen, COLOR_SYS_NTSC, NTSC_4FSC) != 0) {
        fprintf(stderr, "Failed to init NTSC generator\n");
        return -1;
    }

    if (ntsc_decoder_init(&dec, NTSC_4FSC) != 0) {
        fprintf(stderr, "Failed to init NTSC decoder\n");
        colorbars_gen_free(&gen);
        return -1;
    }

    width = gen.active_length;
    printf("NTSC: %d x %d at %d Hz sample rate\n", width, height, NTSC_4FSC);

    /* Allocate buffers */
    int16_t *encoded_line = calloc(gen.line_length, sizeof(int16_t));
    uint32_t *framebuffer = calloc(width * height, sizeof(uint32_t));
    uint32_t *decoded_line = calloc(width, sizeof(uint32_t));

    if (!encoded_line || !framebuffer || !decoded_line) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    /* Reset generator and decoder */
    colorbars_gen_reset(&gen);
    ntsc_decoder_new_field(&dec, 0);

    /* Generate and decode frame */
    for (line = 0; line < height; line++) {
        /* Generate encoded color bars line */
        colorbars_gen_line(&gen, encoded_line, line);

        /* Decode line */
        ntsc_decoder_decode_line(&dec, encoded_line, decoded_line, width);

        /* Copy to framebuffer */
        memcpy(&framebuffer[line * width], decoded_line, width * sizeof(uint32_t));
    }

    /* Write output image */
    write_ppm("ntsc_colorbars.ppm", framebuffer, width, height);

    /* Analyze color bar values */
    printf("\nNTSC Color Bar Analysis (center of each bar):\n");
    int bar_width = width / 8;
    int sample_y = height / 2;  /* Middle of frame */

    int bar;
    for (bar = 0; bar < 8; bar++) {
        int sample_x = bar * bar_width + bar_width / 2;
        uint32_t pixel = framebuffer[sample_y * width + sample_x];
        int r = (pixel >> 16) & 0xFF;
        int g = (pixel >> 8) & 0xFF;
        int b = pixel & 0xFF;
        printf("  Bar %d: R=%3d G=%3d B=%3d\n", bar, r, g, b);
    }

    /* Cleanup */
    free(encoded_line);
    free(decoded_line);
    free(framebuffer);
    colorbars_gen_free(&gen);
    ntsc_decoder_free(&dec);

    return 0;
}

/*=========================================================================*/
/* Generate Reference Color Bars (No Encoding)                             */
/*=========================================================================*/

int test_reference_bars(void)
{
    printf("\n=== Reference Color Bars (Direct RGB) ===\n");

    int width = 640;
    int height = 480;
    int bar_width = width / 8;

    /* Standard 75% color bar RGB values */
    uint32_t bar_colors[8] = {
        0xFFBFBFBF,  /* White (75%) */
        0xFFBFBF00,  /* Yellow */
        0xFF00BFBF,  /* Cyan */
        0xFF00BF00,  /* Green */
        0xFFBF00BF,  /* Magenta */
        0xFFBF0000,  /* Red */
        0xFF0000BF,  /* Blue */
        0xFF000000   /* Black */
    };

    uint32_t *framebuffer = calloc(width * height, sizeof(uint32_t));
    if (!framebuffer) {
        fprintf(stderr, "Memory allocation failed\n");
        return -1;
    }

    int x, y;
    for (y = 0; y < height; y++) {
        for (x = 0; x < width; x++) {
            int bar = x / bar_width;
            if (bar > 7) bar = 7;
            framebuffer[y * width + x] = bar_colors[bar];
        }
    }

    write_ppm("reference_colorbars.ppm", framebuffer, width, height);

    printf("\nReference Color Bar Values (75%% EBU):\n");
    printf("  White:   R=191 G=191 B=191\n");
    printf("  Yellow:  R=191 G=191 B=  0\n");
    printf("  Cyan:    R=  0 G=191 B=191\n");
    printf("  Green:   R=  0 G=191 B=  0\n");
    printf("  Magenta: R=191 G=  0 B=191\n");
    printf("  Red:     R=191 G=  0 B=  0\n");
    printf("  Blue:    R=  0 G=  0 B=191\n");
    printf("  Black:   R=  0 G=  0 B=  0\n");

    free(framebuffer);
    return 0;
}

/*=========================================================================*/
/* Main                                                                    */
/*=========================================================================*/

int main(int argc, char *argv[])
{
    printf("================================================\n");
    printf("Color Bars Visual Test Suite\n");
    printf("Based on PAL-CRT/NTSC-CRT Reference\n");
    printf("================================================\n");

    /* Test direct YUV to RGB conversion first */
    test_direct_yuv_to_rgb();

    /* Debug single line encode */
    test_single_line_debug();

    /* Generate reference bars */
    test_reference_bars();

    /* Test PAL encoding/decoding */
    test_pal_visual();

    /* Test NTSC encoding/decoding */
    test_ntsc_visual();

    printf("\n================================================\n");
    printf("Visual test complete!\n");
    printf("Generated files:\n");
    printf("  - reference_colorbars.ppm (direct RGB)\n");
    printf("  - pal_colorbars.ppm (encoded/decoded PAL)\n");
    printf("  - ntsc_colorbars.ppm (encoded/decoded NTSC)\n");
    printf("================================================\n");

    return 0;
}
