/**
 * PAL-CRT Decode Wrapper for hacktv integration
 *
 * Provides a simple C interface for decoding PAL baseband signals using PAL-CRT
 */

#include <stdlib.h>
#include <string.h>
#include "pal_core.h"
#include "pal.h"

static struct PAL_CRT crt;
static unsigned char *output_buffer = NULL;
static int output_width = 720;
static int output_height = 576;
static int initialized = 0;

/* Initialize the decoder with output dimensions */
int decode_init(int w, int h)
{
    if (output_buffer != NULL) {
        free(output_buffer);
    }

    output_width = w;
    output_height = h;
    output_buffer = (unsigned char *)malloc(w * h * 3);
    if (output_buffer == NULL) {
        return -1;
    }

    memset(output_buffer, 0, w * h * 3);

    pal_init(&crt, w, h, PAL_PIX_FORMAT_RGB, output_buffer);

    /* Set default parameters for best quality */
    crt.saturation = 12;      /* slightly boost saturation */
    crt.brightness = 0;
    crt.contrast = 180;
    crt.black_point = 0;
    crt.white_point = 100;
    crt.scanlines = 0;        /* no scanline gaps */
    crt.blend = 0;            /* no blending with previous frame */
    crt.chroma_correction = 1; /* enable PAL delay line correction */
    crt.chroma_lag = 0;       /* no chroma lag */
    crt.v_fac = 0;
    crt.cc_period = 8;        /* color carrier period (PAL) */

    initialized = 1;
    return 0;
}

/* Get expected input size */
int get_input_size(void)
{
    return PAL_INPUT_SIZE;
}

/* Get horizontal resolution */
int get_hres(void)
{
    return PAL_HRES;
}

/* Get vertical resolution */
int get_vres(void)
{
    return PAL_VRES;
}

/* Set decoder parameters */
void decode_set_params(int saturation, int brightness, int contrast,
                       int black_point, int white_point, int chroma_correction)
{
    if (!initialized) return;

    crt.saturation = saturation;
    crt.brightness = brightness;
    crt.contrast = contrast;
    crt.black_point = black_point;
    crt.white_point = white_point;
    crt.chroma_correction = chroma_correction;
}

/* Decode a field of analog signal data */
int decode_field(const signed char *signal, int signal_len, unsigned char *out)
{
    if (!initialized || signal_len < PAL_INPUT_SIZE) {
        return -1;
    }

    /* Copy input signal to CRT analog buffer */
    memcpy(crt.analog, signal, PAL_INPUT_SIZE);

    /* Decode */
    pal_demodulate(&crt, 0);  /* 0 = no added noise */

    /* Copy output */
    memcpy(out, output_buffer, output_width * output_height * 3);

    return 0;
}

/* Decode with noise parameter */
int decode_field_noise(const signed char *signal, int signal_len,
                       unsigned char *out, int noise)
{
    if (!initialized || signal_len < PAL_INPUT_SIZE) {
        return -1;
    }

    memcpy(crt.analog, signal, PAL_INPUT_SIZE);
    pal_demodulate(&crt, noise);
    memcpy(out, output_buffer, output_width * output_height * 3);

    return 0;
}

/* Get raw pointer to analog buffer for direct writing */
signed char* get_analog_buffer(void)
{
    return crt.analog;
}

/* Decode after direct write to analog buffer */
int decode_direct(unsigned char *out, int noise)
{
    if (!initialized) {
        return -1;
    }

    pal_demodulate(&crt, noise);
    memcpy(out, output_buffer, output_width * output_height * 3);

    return 0;
}

/* Cleanup */
void decode_cleanup(void)
{
    if (output_buffer != NULL) {
        free(output_buffer);
        output_buffer = NULL;
    }
    initialized = 0;
}

/* Get version */
void get_version(int *major, int *minor, int *patch)
{
    *major = PAL_MAJOR;
    *minor = PAL_MINOR;
    *patch = PAL_PATCH;
}

/* Encode an RGB image to PAL analog signal using PAL-CRT's encoder */
int encode_field(const unsigned char *rgb, int width, int height, signed char *out)
{
    struct PAL_SETTINGS pal;

    if (!initialized) {
        return -1;
    }

    memset(&pal, 0, sizeof(struct PAL_SETTINGS));
    pal.data = rgb;
    pal.format = PAL_PIX_FORMAT_RGB;
    pal.w = width;
    pal.h = height;
    pal.raw = 0;
    pal.as_color = 1;  /* color mode */
    pal.field = 0;
    pal.hue = 0;
    pal.xoffset = 0;
    pal.yoffset = 0;
    pal.color_phase_error = 0;

    /* Encode using PAL-CRT's modulator */
    pal_modulate(&crt, &pal);

    /* Copy the analog signal */
    memcpy(out, crt.analog, PAL_INPUT_SIZE);

    return 0;
}

/* Roundtrip test: encode then decode */
int roundtrip_test(const unsigned char *rgb_in, int width, int height,
                   unsigned char *rgb_out, int noise)
{
    struct PAL_SETTINGS pal;

    if (!initialized) {
        return -1;
    }

    memset(&pal, 0, sizeof(struct PAL_SETTINGS));
    pal.data = rgb_in;
    pal.format = PAL_PIX_FORMAT_RGB;
    pal.w = width;
    pal.h = height;
    pal.raw = 0;
    pal.as_color = 1;
    pal.field = 0;
    pal.hue = 0;
    pal.xoffset = 0;
    pal.yoffset = 0;
    pal.color_phase_error = 0;

    /* Encode */
    pal_modulate(&crt, &pal);

    /* Decode */
    pal_demodulate(&crt, noise);

    /* Copy output */
    memcpy(rgb_out, output_buffer, output_width * output_height * 3);

    return 0;
}
