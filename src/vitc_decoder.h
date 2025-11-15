/* vitc_decoder.h - VITC (Vertical Interval Timecode) Decoder */
/*=======================================================================*/
/* Copyright 2025 - VITC Decoder Implementation                          */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _VITC_DECODER_H
#define _VITC_DECODER_H

#include <stdint.h>

/*
 * VITC (Vertical Interval Timecode) - SMPTE 12M
 *
 * VITC is a timecode format embedded in the VBI (Vertical Blanking Interval)
 * of analog video signals. Unlike LTC (Linear Timecode) which is audio-based,
 * VITC can be read at any tape speed including pause.
 *
 * Format:
 * - 90 bits total per line (in bi-phase mark coding)
 * - Contains: hours, minutes, seconds, frames
 * - User bits (32 bits for custom data)
 * - Drop frame flag, color frame flag
 * - CRC for error detection
 *
 * Bit rate: ~1.15 MHz for PAL, ~1.37 MHz for NTSC
 * Lines: Typically lines 10-20 for 625-line, 12-21 for 525-line
 * Encoding: Bi-phase mark (Manchester variant)
 */

/* VITC timecode structure */
typedef struct {
	int hours;          /* 0-23 */
	int minutes;        /* 0-59 */
	int seconds;        /* 0-59 */
	int frames;         /* 0-24 (PAL) or 0-29 (NTSC) */

	/* Flags */
	int drop_frame;     /* Drop frame flag (NTSC only) */
	int color_frame;    /* Color frame flag */
	int field_mark;     /* Field mark (odd/even) */

	/* User bits (8 groups of 4 bits) */
	uint8_t user_bits[8];

	/* Binary groups (alternative to BCD user bits) */
	uint32_t binary_groups;

	/* Quality indicators */
	int valid;          /* 1 if timecode is valid (CRC passed) */
	int confidence;     /* Confidence level (0-10) */

} vitc_timecode_t;

/* VITC decoder state */
typedef struct {
	int sample_rate;       /* Video sample rate */
	int line_length;       /* Samples per line */
	int is_625_line;       /* 1 for PAL (625), 0 for NTSC (525) */

	/* Timing parameters */
	int vitc_start;        /* Sample position of VITC start */
	int vitc_bit_width;    /* Samples per bit */

	/* Valid VITC lines */
	int vitc_line_start;   /* First line to check */
	int vitc_line_end;     /* Last line to check */

	/* Decoder state */
	vitc_timecode_t current_tc;  /* Current decoded timecode */
	vitc_timecode_t last_valid_tc; /* Last valid timecode */

	/* Statistics */
	int lines_processed;
	int valid_detections;
	int errors;
	int crc_errors;

} vitc_decoder_t;

/* Function prototypes */

/**
 * Initialize VITC decoder
 *
 * @param vitc       VITC decoder state
 * @param sample_rate Video sample rate
 * @param line_length Samples per line
 * @param is_625_line 1 for PAL (625), 0 for NTSC (525)
 * @return 0 on success, -1 on error
 */
int vitc_decoder_init(vitc_decoder_t *vitc, int sample_rate, int line_length, int is_625_line);

/**
 * Free VITC decoder resources
 *
 * @param vitc VITC decoder state
 */
void vitc_decoder_free(vitc_decoder_t *vitc);

/**
 * Process a video line for VITC data
 *
 * @param vitc     VITC decoder state
 * @param line     Video line samples (luma only)
 * @param line_num Line number (0-based)
 * @return 1 if VITC detected and decoded, 0 if no VITC, -1 on error
 */
int vitc_decoder_process_line(vitc_decoder_t *vitc, int16_t *line, int line_num);

/**
 * Get current timecode as a formatted string (HH:MM:SS:FF)
 *
 * @param vitc   VITC decoder state
 * @param buffer Buffer to write string to
 * @param size   Buffer size
 * @return Number of characters written
 */
int vitc_decoder_get_timecode_string(vitc_decoder_t *vitc, char *buffer, int size);

/**
 * Get comprehensive VITC information
 *
 * @param vitc   VITC decoder state
 * @param buffer Buffer to write string to
 * @param size   Buffer size
 * @return Number of characters written
 */
int vitc_decoder_get_info(vitc_decoder_t *vitc, char *buffer, int size);

/**
 * Check if current timecode is valid
 *
 * @param vitc VITC decoder state
 * @return 1 if valid, 0 if invalid
 */
int vitc_decoder_is_valid(vitc_decoder_t *vitc);

#endif /* _VITC_DECODER_H */
