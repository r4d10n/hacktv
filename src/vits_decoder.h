/* vits_decoder.h - VITS (Vertical Interval Test Signals) Decoder */
/*=======================================================================*/
/* Copyright 2025 - VITS Decoder Implementation                          */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _VITS_DECODER_H
#define _VITS_DECODER_H

#include <stdint.h>

/*
 * VITS (Vertical Interval Test Signals)
 *
 * VITS are standardized test signals inserted in the VBI (Vertical Blanking
 * Interval) to allow monitoring of video signal quality and transmission
 * characteristics.
 *
 * Common VITS signals:
 * - Pulse and bar (line 17): White level reference, black level
 * - Staircase (line 17): Luminance linearity test
 * - Multiburst (line 18): Chrominance and frequency response
 * - Color bars: Phase and amplitude reference
 *
 * Standards: ITU-R BT.470, SMPTE RP-219
 */

/* VITS signal types */
typedef enum {
	VITS_TYPE_NONE = 0,
	VITS_TYPE_PULSE_BAR,      /* Pulse and bar (white level, black level) */
	VITS_TYPE_STAIRCASE,      /* Luminance staircase (5 or 10 steps) */
	VITS_TYPE_MULTIBURST,     /* Frequency response test (0.5-5.8 MHz) */
	VITS_TYPE_COLOR_BARS,     /* Color bar pattern */
	VITS_TYPE_WINDOW,         /* Window signal */
	VITS_TYPE_CUSTOM,         /* Unknown/custom test signal */
} vits_type_t;

/* VITS measurement results */
typedef struct {
	/* Pulse and bar measurements */
	int white_level;          /* White level (IRE or mV) */
	int black_level;          /* Black level (IRE or mV) */
	int sync_level;           /* Sync level (IRE or mV) */
	int contrast_ratio;       /* White/black ratio */

	/* Luminance linearity (from staircase) */
	int luma_steps[10];       /* Measured step levels */
	int luma_linearity;       /* Linearity error percentage */

	/* Frequency response (from multiburst) */
	int freq_response[6];     /* Amplitude at different frequencies */
	int bandwidth_mhz;        /* Effective bandwidth */

	/* Signal quality */
	int snr_db;               /* Signal-to-noise ratio */
	int distortion_percent;   /* Total distortion */

} vits_measurement_t;

/* VITS decoder state */
typedef struct {
	int sample_rate;          /* Video sample rate */
	int line_length;          /* Samples per line */
	int is_625_line;          /* 1 for PAL (625), 0 for NTSC (525) */

	/* VITS line ranges */
	int vits_line_start;      /* First VITS line */
	int vits_line_end;        /* Last VITS line */

	/* Detected signals */
	vits_type_t detected_types[10];  /* Detected signal types per line */
	int detection_confidence[10];    /* Confidence for each detection */

	/* Measurements */
	vits_measurement_t measurements;

	/* Statistics */
	int lines_processed;
	int signals_detected;
	int errors;

} vits_decoder_t;

/* Function prototypes */

/**
 * Initialize VITS decoder
 *
 * @param vits       VITS decoder state
 * @param sample_rate Video sample rate
 * @param line_length Samples per line
 * @param is_625_line 1 for PAL (625), 0 for NTSC (525)
 * @return 0 on success, -1 on error
 */
int vits_decoder_init(vits_decoder_t *vits, int sample_rate, int line_length, int is_625_line);

/**
 * Free VITS decoder resources
 *
 * @param vits VITS decoder state
 */
void vits_decoder_free(vits_decoder_t *vits);

/**
 * Process a video line for VITS signals
 *
 * @param vits     VITS decoder state
 * @param line     Video line samples (luma only)
 * @param line_num Line number (0-based)
 * @return VITS signal type if detected, VITS_TYPE_NONE otherwise
 */
vits_type_t vits_decoder_process_line(vits_decoder_t *vits, int16_t *line, int line_num);

/**
 * Get signal type name
 *
 * @param type VITS signal type
 * @return Human-readable signal type name
 */
const char* vits_type_to_string(vits_type_t type);

/**
 * Get current VITS measurements as a formatted string
 *
 * @param vits   VITS decoder state
 * @param buffer Buffer to write string to
 * @param size   Buffer size
 * @return Number of characters written
 */
int vits_decoder_get_info(vits_decoder_t *vits, char *buffer, int size);

/**
 * Analyze pulse and bar signal
 *
 * @param vits VITS decoder state
 * @param line Video line samples
 * @return 1 if analyzed successfully, 0 otherwise
 */
int vits_analyze_pulse_bar(vits_decoder_t *vits, int16_t *line);

/**
 * Analyze multiburst signal
 *
 * @param vits VITS decoder state
 * @param line Video line samples
 * @return 1 if analyzed successfully, 0 otherwise
 */
int vits_analyze_multiburst(vits_decoder_t *vits, int16_t *line);

#endif /* _VITS_DECODER_H */
