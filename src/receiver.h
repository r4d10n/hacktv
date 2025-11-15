/* receiver.h - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - Analog TV Receiver Implementation                    */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _RECEIVER_H
#define _RECEIVER_H

#include <stdint.h>
#include "video.h"
#include "fir.h"

/* Demodulator types */
typedef enum {
	RX_DEMOD_FM,
	RX_DEMOD_AM,
	RX_DEMOD_VSB,
} rx_demod_type_t;

/* Colour system types */
typedef enum {
	RX_COLOUR_NONE,
	RX_COLOUR_PAL,
	RX_COLOUR_NTSC,
	RX_COLOUR_SECAM,
} rx_colour_type_t;

/* FM Demodulator state */
typedef struct {
	int sample_rate;
	double deviation;
	cint32_t prev_sample;
	int32_t prev_angle;
	fir_int16_t *filter;
} rx_fm_demod_t;

/* AM Demodulator state */
typedef struct {
	int sample_rate;
	fir_int16_t *filter;
} rx_am_demod_t;

/* VSB Demodulator state */
typedef struct {
	int sample_rate;
	double carrier_freq;
	cint32_t carrier_phase;
	cint32_t carrier_step;
	fir_int16_t *filter;
} rx_vsb_demod_t;

/* Sync detector state */
typedef struct {
	int sample_rate;
	int line_length;          /* Expected samples per line */
	int frame_lines;          /* Lines per frame */
	int interlaced;

	/* Sync thresholds */
	int16_t sync_level;
	int16_t blanking_level;
	int16_t black_level;
	int16_t white_level;

	/* Detection state */
	int samples_since_sync;
	int current_line;
	int current_field;
	int in_sync;

	/* AGC */
	int16_t agc_level;
	int32_t agc_accumulator;
} rx_sync_t;

/* PAL colour decoder */
typedef struct {
	int sample_rate;
	int line_length;
	double subcarrier_freq;

	/* Colour burst detection */
	int burst_start;
	int burst_length;

	/* Subcarrier oscillator */
	cint32_t *carrier_lut;
	int carrier_lut_size;
	int carrier_phase;

	/* Chroma filters */
	fir_int16_t *u_filter;
	fir_int16_t *v_filter;

	/* PAL line alternation */
	int v_switch;
} rx_pal_decoder_t;

/* NTSC colour decoder */
typedef struct {
	int sample_rate;
	int line_length;
	double subcarrier_freq;

	/* Colour burst detection */
	int burst_start;
	int burst_length;

	/* Subcarrier oscillator */
	cint32_t *carrier_lut;
	int carrier_lut_size;
	int carrier_phase;

	/* Chroma filters */
	fir_int16_t *i_filter;
	fir_int16_t *q_filter;
} rx_ntsc_decoder_t;

/* SECAM colour decoder */
typedef struct {
	int sample_rate;
	int line_length;

	/* SECAM FM subcarriers */
	double dr_freq;  /* 4.40625 MHz - R-Y */
	double db_freq;  /* 4.25000 MHz - B-Y */

	rx_fm_demod_t dr_demod;
	rx_fm_demod_t db_demod;

	/* Line switching */
	int use_dr;  /* 0 = Db, 1 = Dr */
} rx_secam_decoder_t;

/* Audio demodulator */
typedef struct {
	int sample_rate;
	double carrier_freq;
	rx_fm_demod_t fm_demod;

	/* De-emphasis filter */
	fir_int16_t *deemph_filter;

	/* Output resampler */
	int output_rate;
	fir_int16_t *resampler;
} rx_audio_demod_t;

/* Main receiver configuration */
typedef struct {
	/* Input */
	int sample_rate;
	rx_demod_type_t demod_type;

	/* Video standard */
	int lines;
	int interlaced;
	r64_t frame_rate;

	/* Colour system */
	rx_colour_type_t colour_type;

	/* Audio */
	int enable_audio;
	double audio_carrier;
	int audio_output_rate;

	/* RF tuning */
	double rf_frequency;
	double if_frequency;
} rx_config_t;

/* Receiver state */
typedef struct {
	rx_config_t conf;

	/* Demodulator */
	rx_fm_demod_t fm_demod;
	rx_am_demod_t am_demod;
	rx_vsb_demod_t vsb_demod;

	/* Sync detector */
	rx_sync_t sync;

	/* Colour decoder */
	rx_pal_decoder_t pal_decoder;
	rx_ntsc_decoder_t ntsc_decoder;
	rx_secam_decoder_t secam_decoder;

	/* Audio decoder */
	rx_audio_demod_t audio_demod;

	/* Line buffer */
	int16_t *line_buffer;
	int line_buffer_size;
	int line_buffer_pos;

	/* Frame buffer (RGB) */
	uint32_t *framebuffer;
	int frame_width;
	int frame_height;

	/* Audio buffer */
	int16_t *audio_buffer;
	int audio_buffer_size;
	int audio_buffer_pos;

	/* Statistics */
	uint64_t samples_processed;
	int frames_decoded;
	int sync_errors;

} rx_t;

/* Function prototypes */

/* Initialization */
int rx_init(rx_t *rx, rx_config_t *conf);
void rx_free(rx_t *rx);

/* Demodulation */
int rx_fm_demod_init(rx_fm_demod_t *demod, int sample_rate, double deviation);
void rx_fm_demod_free(rx_fm_demod_t *demod);
int16_t rx_fm_demod_process(rx_fm_demod_t *demod, int16_t i, int16_t q);

int rx_am_demod_init(rx_am_demod_t *demod, int sample_rate);
void rx_am_demod_free(rx_am_demod_t *demod);
int16_t rx_am_demod_process(rx_am_demod_t *demod, int16_t i, int16_t q);

int rx_vsb_demod_init(rx_vsb_demod_t *demod, int sample_rate, double carrier_freq);
void rx_vsb_demod_free(rx_vsb_demod_t *demod);
int16_t rx_vsb_demod_process(rx_vsb_demod_t *demod, int16_t i, int16_t q);

/* Sync detection */
int rx_sync_init(rx_sync_t *sync, int sample_rate, int line_length, int frame_lines, int interlaced);
int rx_sync_process(rx_sync_t *sync, int16_t sample, int *line_start, int *field);

/* Colour decoding */
int rx_pal_init(rx_pal_decoder_t *pal, int sample_rate, int line_length);
void rx_pal_free(rx_pal_decoder_t *pal);
void rx_pal_decode_line(rx_pal_decoder_t *pal, int16_t *line, uint32_t *rgb_out, int width);

int rx_ntsc_init(rx_ntsc_decoder_t *ntsc, int sample_rate, int line_length);
void rx_ntsc_free(rx_ntsc_decoder_t *ntsc);
void rx_ntsc_decode_line(rx_ntsc_decoder_t *ntsc, int16_t *line, uint32_t *rgb_out, int width);

int rx_secam_init(rx_secam_decoder_t *secam, int sample_rate, int line_length);
void rx_secam_free(rx_secam_decoder_t *secam);
void rx_secam_decode_line(rx_secam_decoder_t *secam, int16_t *line, uint32_t *rgb_out, int width);

/* Audio decoding */
int rx_audio_init(rx_audio_demod_t *audio, int sample_rate, double carrier_freq, int output_rate);
void rx_audio_free(rx_audio_demod_t *audio);
int16_t rx_audio_process(rx_audio_demod_t *audio, int16_t i, int16_t q);

/* Main processing */
int rx_process_samples(rx_t *rx, int16_t *samples, int count);
int rx_get_frame(rx_t *rx, uint32_t **framebuffer, int *width, int *height);
int rx_get_audio(rx_t *rx, int16_t **audio, int *count);

/* Utility functions */
void yuv_to_rgb(int16_t y, int16_t u, int16_t v, uint8_t *r, uint8_t *g, uint8_t *b);

#endif /* _RECEIVER_H */
