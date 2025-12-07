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
