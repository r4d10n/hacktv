/* wss_decoder.h - WSS (Widescreen Signaling) Decoder */
/*=======================================================================*/
/* Copyright 2025 - WSS Decoder Implementation                           */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _WSS_DECODER_H
#define _WSS_DECODER_H

#include <stdint.h>

/*
 * WSS (Widescreen Signaling) - ITU-R BT.1119
 *
 * WSS is a system for signaling the aspect ratio and other format information
 * of a television signal. In PAL systems, it's transmitted on line 23 (field 1).
 *
 * The signal consists of:
 * - Start code (run-in + start bits)
 * - 14-bit data word
 * - Transmitted at 5.0 MHz bit rate (200ns per bit)
 * - Bi-phase coded (Manchester encoding)
 *
 * Timing (for PAL):
 * - Line 23, starting at ~11.0 µs from line sync
 * - Total duration: ~35 bits × 200ns = 7.0 µs
 */

/* WSS aspect ratio formats */
typedef enum {
	WSS_ASPECT_4_3_FULL       = 0x0,  /* 4:3 full format */
	WSS_ASPECT_14_9_LETTERBOX = 0x1,  /* 14:9 letterbox, center */
	WSS_ASPECT_14_9_TOP       = 0x2,  /* 14:9 letterbox, top */
	WSS_ASPECT_16_9_LETTERBOX = 0x4,  /* 16:9 letterbox, center */
	WSS_ASPECT_16_9_TOP       = 0x5,  /* 16:9 letterbox, top */
	WSS_ASPECT_16_9_FULL      = 0x7,  /* 16:9 full format (anamorphic) */
	WSS_ASPECT_4_3_SHOOT      = 0x8,  /* >16:9 letterbox, center (shoot & protect 4:3) */
	WSS_ASPECT_14_9_FULL      = 0xB,  /* 14:9 full format (anamorphic) */
	WSS_ASPECT_16_9_SHOOT     = 0xD,  /* >16:9 letterbox, center (shoot & protect 16:9) */
} wss_aspect_t;

/* WSS decoder state */
typedef struct {
	int sample_rate;           /* Video sample rate */
	int line_length;           /* Samples per line */

	/* Timing parameters */
	int wss_start;             /* Sample position of WSS start (from line sync) */
	int wss_bit_width;         /* Samples per bit */

	/* Line 23 detection */
	int wss_line;              /* Line number for WSS (23 for PAL) */

	/* Decoder state */
	uint16_t current_word;     /* Current 14-bit WSS word */
	int valid;                 /* 1 if current word is valid */
	int confidence;            /* Confidence counter (0-10) */

	/* Decoded information */
	wss_aspect_t aspect_ratio;
	int enhanced_mode;         /* 0 = camera mode, 1 = enhanced mode */
	int subtitles;             /* Subtitle information (3 bits) */
	int copyright;             /* Copyright asserted */
	int copy_restriction;      /* Copying restricted */

	/* Statistics */
	int lines_processed;
	int valid_detections;
	int errors;

} wss_decoder_t;

/* Function prototypes */

/**
 * Initialize WSS decoder
 *
 * @param wss        WSS decoder state
 * @param sample_rate Video sample rate (e.g., 13500000 for PAL)
 * @param line_length Samples per line
 * @param lines      Total lines (625 for PAL, 525 for NTSC)
 * @return 0 on success, -1 on error
 */
int wss_decoder_init(wss_decoder_t *wss, int sample_rate, int line_length, int lines);

/**
 * Free WSS decoder resources
 *
 * @param wss WSS decoder state
 */
void wss_decoder_free(wss_decoder_t *wss);

/**
 * Process a video line for WSS data
 *
 * @param wss        WSS decoder state
 * @param line       Video line samples (luma only)
 * @param line_num   Line number (0-based)
 * @param field      Field number (0 or 1)
 * @return 1 if WSS detected and decoded, 0 if no WSS, -1 on error
 */
int wss_decoder_process_line(wss_decoder_t *wss, int16_t *line, int line_num, int field);

/**
 * Get aspect ratio string
 *
 * @param aspect WSS aspect ratio code
 * @return Human-readable aspect ratio string
 */
const char* wss_aspect_to_string(wss_aspect_t aspect);

/**
 * Get current WSS information as a formatted string
 *
 * @param wss    WSS decoder state
 * @param buffer Buffer to write string to
 * @param size   Buffer size
 * @return Number of characters written
 */
int wss_decoder_get_info(wss_decoder_t *wss, char *buffer, int size);

#endif /* _WSS_DECODER_H */
