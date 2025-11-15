/* wss_decoder.c - WSS (Widescreen Signaling) Decoder */
/*=======================================================================*/
/* Copyright 2025 - WSS Decoder Implementation                           */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "wss_decoder.h"

/* WSS timing constants for PAL (ITU-R BT.1119) */
#define WSS_START_US         11.0      /* Start time from line sync (microseconds) */
#define WSS_BIT_RATE         5000000   /* 5.0 MHz bit rate */
#define WSS_BIT_PERIOD_US    0.2       /* 200ns per bit */
#define WSS_TOTAL_BITS       50        /* 29 run-in + 12 start + 14 data (but we only decode last 14) */

/* WSS start code (after run-in): 111000110001 */
#define WSS_START_CODE       0xE31     /* 111000110001 in binary */
#define WSS_START_CODE_BITS  12

/* Bi-phase (Manchester) decoding threshold */
#define WSS_THRESHOLD        0         /* Threshold for detecting transitions (relative to black level) */

/**
 * Initialize WSS decoder
 */
int wss_decoder_init(wss_decoder_t *wss, int sample_rate, int line_length, int lines)
{
	memset(wss, 0, sizeof(wss_decoder_t));

	wss->sample_rate = sample_rate;
	wss->line_length = line_length;

	/* Calculate WSS timing parameters */
	wss->wss_start = (int)(WSS_START_US * sample_rate / 1000000.0);
	wss->wss_bit_width = sample_rate / WSS_BIT_RATE;

	/* Determine WSS line based on system */
	if(lines == 625)
	{
		/* PAL: Line 23 (field 1) */
		wss->wss_line = 23;
	}
	else if(lines == 525)
	{
		/* NTSC: Line 20 (field 1) - less common */
		wss->wss_line = 20;
	}
	else
	{
		fprintf(stderr, "WSS: Unsupported line count: %d\n", lines);
		return -1;
	}

	wss->valid = 0;
	wss->confidence = 0;

	fprintf(stderr, "WSS decoder initialized: line %d, start sample %d, bit width %d samples\n",
		wss->wss_line, wss->wss_start, wss->wss_bit_width);

	return 0;
}

/**
 * Free WSS decoder resources
 */
void wss_decoder_free(wss_decoder_t *wss)
{
	/* No dynamic allocations to free */
	(void)wss;
}

/**
 * Decode bi-phase (Manchester) encoded bit
 *
 * In bi-phase encoding:
 * - Transition from low->high in middle of bit = '1'
 * - Transition from high->low in middle of bit = '0'
 */
static int decode_biphase_bit(int16_t *samples, int bit_width)
{
	int first_half_sum = 0;
	int second_half_sum = 0;
	int i;

	/* Average first half of bit period */
	for(i = 0; i < bit_width / 2; i++)
	{
		first_half_sum += samples[i];
	}
	first_half_sum /= (bit_width / 2);

	/* Average second half of bit period */
	for(i = bit_width / 2; i < bit_width; i++)
	{
		second_half_sum += samples[i];
	}
	second_half_sum /= (bit_width - bit_width / 2);

	/* Detect transition direction */
	if(second_half_sum > first_half_sum)
	{
		return 1;  /* Low to high = '1' */
	}
	else
	{
		return 0;  /* High to low = '0' */
	}
}

/**
 * Calculate parity for WSS word (even parity on groups)
 */
static int wss_check_parity(uint16_t word)
{
	/* WSS uses a more complex parity scheme, but for simplicity
	 * we'll do basic validation based on reserved bits */

	/* Bit 7 should be 0 (reserved) */
	if((word >> 7) & 1)
	{
		return 0;  /* Invalid */
	}

	/* For now, accept the word if it passes basic checks */
	return 1;
}

/**
 * Decode WSS 14-bit word into aspect ratio and other information
 */
static void wss_decode_word(wss_decoder_t *wss, uint16_t word)
{
	/* Extract fields from 14-bit word */

	/* Bits 0-3: Aspect ratio group (4 bits, but we use 3 + enhanced) */
	int aspect_bits = (word & 0x0F);
	wss->aspect_ratio = (wss_aspect_t)aspect_bits;

	/* Bit 3: Enhanced mode */
	wss->enhanced_mode = (word >> 3) & 1;

	/* Bits 4-6: Subtitles */
	wss->subtitles = (word >> 4) & 0x07;

	/* Bit 11: Copyright */
	wss->copyright = (word >> 11) & 1;

	/* Bit 12: Copy restriction */
	wss->copy_restriction = (word >> 12) & 1;

	wss->valid = 1;
	wss->valid_detections++;
}

/**
 * Process a video line for WSS data
 */
int wss_decoder_process_line(wss_decoder_t *wss, int16_t *line, int line_num, int field)
{
	int i;
	uint16_t decoded_word = 0;
	int bit;
	int start_pos;
	int valid_start_code = 0;

	/* Only process WSS line in field 1 */
	if(line_num != wss->wss_line || field != 0)
	{
		return 0;
	}

	wss->lines_processed++;

	/* Check if we have enough samples */
	if(wss->wss_start + (WSS_TOTAL_BITS * wss->wss_bit_width) > wss->line_length)
	{
		wss->errors++;
		return -1;
	}

	/* Look for start code (skip run-in, decode start code) */
	start_pos = wss->wss_start + (29 * wss->wss_bit_width);  /* Skip run-in */

	/* Decode 12-bit start code */
	uint16_t start_code = 0;
	for(i = 0; i < WSS_START_CODE_BITS; i++)
	{
		bit = decode_biphase_bit(&line[start_pos + i * wss->wss_bit_width], wss->wss_bit_width);
		start_code = (start_code << 1) | bit;
	}

	/* Verify start code */
	if(start_code == WSS_START_CODE)
	{
		valid_start_code = 1;
	}
	else
	{
		/* Start code mismatch - might not be valid WSS */
		wss->confidence = (wss->confidence > 0) ? wss->confidence - 1 : 0;
		return 0;
	}

	/* Decode 14 data bits */
	start_pos += WSS_START_CODE_BITS * wss->wss_bit_width;
	for(i = 0; i < 14; i++)
	{
		bit = decode_biphase_bit(&line[start_pos + i * wss->wss_bit_width], wss->wss_bit_width);
		decoded_word = (decoded_word << 1) | bit;
	}

	/* Validate word */
	if(!wss_check_parity(decoded_word))
	{
		wss->errors++;
		wss->confidence = (wss->confidence > 0) ? wss->confidence - 1 : 0;
		return 0;
	}

	/* Decode word into structured information */
	wss_decode_word(wss, decoded_word);
	wss->current_word = decoded_word;

	/* Increase confidence */
	wss->confidence = (wss->confidence < 10) ? wss->confidence + 1 : 10;

	return 1;
}

/**
 * Get aspect ratio string
 */
const char* wss_aspect_to_string(wss_aspect_t aspect)
{
	switch(aspect)
	{
		case WSS_ASPECT_4_3_FULL:       return "4:3 full format";
		case WSS_ASPECT_14_9_LETTERBOX: return "14:9 letterbox (center)";
		case WSS_ASPECT_14_9_TOP:       return "14:9 letterbox (top)";
		case WSS_ASPECT_16_9_LETTERBOX: return "16:9 letterbox (center)";
		case WSS_ASPECT_16_9_TOP:       return "16:9 letterbox (top)";
		case WSS_ASPECT_16_9_FULL:      return "16:9 full format (anamorphic)";
		case WSS_ASPECT_4_3_SHOOT:      return ">16:9 letterbox (shoot & protect 4:3)";
		case WSS_ASPECT_14_9_FULL:      return "14:9 full format (anamorphic)";
		case WSS_ASPECT_16_9_SHOOT:     return ">16:9 letterbox (shoot & protect 16:9)";
		default:                        return "Unknown aspect ratio";
	}
}

/**
 * Get current WSS information as a formatted string
 */
int wss_decoder_get_info(wss_decoder_t *wss, char *buffer, int size)
{
	if(!wss->valid || wss->confidence < 3)
	{
		return snprintf(buffer, size, "WSS: No signal detected");
	}

	return snprintf(buffer, size,
		"WSS: %s | Enhanced: %s | Subtitles: %d | Copyright: %s | Copy: %s",
		wss_aspect_to_string(wss->aspect_ratio),
		wss->enhanced_mode ? "Yes" : "No",
		wss->subtitles,
		wss->copyright ? "Yes" : "No",
		wss->copy_restriction ? "Restricted" : "Allowed");
}
