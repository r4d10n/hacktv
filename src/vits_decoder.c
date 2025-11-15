/* vits_decoder.c - VITS (Vertical Interval Test Signals) Decoder */
/*=======================================================================*/
/* Copyright 2025 - VITS Decoder Implementation                          */
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
#include "vits_decoder.h"

/* VITS line ranges (ITU-R BT.470) */
#define VITS_LINE_START_625  17        /* PAL: Lines 17-19 */
#define VITS_LINE_END_625    19
#define VITS_LINE_START_525  17        /* NTSC: Lines 17-19 */
#define VITS_LINE_END_525    19

/* Signal level thresholds (relative to 16-bit signed range) */
#define SYNC_LEVEL_THRESHOLD    -20000  /* Sync pulse level */
#define BLACK_LEVEL_THRESHOLD   -5000   /* Black level */
#define WHITE_LEVEL_THRESHOLD   20000   /* White level */

/* Pulse and bar timing (PAL, approximate) */
#define PULSE_START_US      11.0       /* Start of pulse */
#define PULSE_WIDTH_US      2.0        /* Pulse width */
#define BAR_START_US        20.0       /* Start of white bar */
#define BAR_WIDTH_US        15.0       /* Bar width */

/**
 * Initialize VITS decoder
 */
int vits_decoder_init(vits_decoder_t *vits, int sample_rate, int line_length, int is_625_line)
{
	memset(vits, 0, sizeof(vits_decoder_t));

	vits->sample_rate = sample_rate;
	vits->line_length = line_length;
	vits->is_625_line = is_625_line;

	/* Set VITS line ranges */
	if(is_625_line)
	{
		vits->vits_line_start = VITS_LINE_START_625;
		vits->vits_line_end = VITS_LINE_END_625;
	}
	else
	{
		vits->vits_line_start = VITS_LINE_START_525;
		vits->vits_line_end = VITS_LINE_END_525;
	}

	fprintf(stderr, "VITS decoder initialized: lines %d-%d\n",
		vits->vits_line_start, vits->vits_line_end);

	return 0;
}

/**
 * Free VITS decoder resources
 */
void vits_decoder_free(vits_decoder_t *vits)
{
	/* No dynamic allocations to free */
	(void)vits;
}

/**
 * Detect pulse and bar pattern
 */
static int detect_pulse_bar(vits_decoder_t *vits, int16_t *line)
{
	int pulse_start = (int)(PULSE_START_US * vits->sample_rate / 1000000.0);
	int pulse_width = (int)(PULSE_WIDTH_US * vits->sample_rate / 1000000.0);
	int bar_start = (int)(BAR_START_US * vits->sample_rate / 1000000.0);
	int bar_width = (int)(BAR_WIDTH_US * vits->sample_rate / 1000000.0);

	/* Check for pulse (should be high/white level) */
	int32_t pulse_sum = 0;
	int i;
	for(i = 0; i < pulse_width && (pulse_start + i) < vits->line_length; i++)
	{
		pulse_sum += line[pulse_start + i];
	}
	int pulse_avg = pulse_sum / pulse_width;

	/* Check for bar (should be white level) */
	int32_t bar_sum = 0;
	for(i = 0; i < bar_width && (bar_start + i) < vits->line_length; i++)
	{
		bar_sum += line[bar_start + i];
	}
	int bar_avg = bar_sum / bar_width;

	/* If both pulse and bar are above white threshold, it's likely pulse & bar */
	if(pulse_avg > WHITE_LEVEL_THRESHOLD / 2 && bar_avg > WHITE_LEVEL_THRESHOLD / 2)
	{
		return 1;
	}

	return 0;
}

/**
 * Detect staircase pattern
 */
static int detect_staircase(vits_decoder_t *vits, int16_t *line)
{
	/* Look for monotonically increasing levels */
	int active_start = vits->line_length / 8;
	int step_width = (vits->line_length - active_start) / 10;
	int steps_detected = 0;
	int i;

	int prev_level = line[active_start];
	for(i = 1; i < 10; i++)
	{
		int pos = active_start + i * step_width;
		if(pos >= vits->line_length) break;

		int current_level = line[pos];

		/* Check if level increased */
		if(current_level > prev_level + 1000)
		{
			steps_detected++;
		}
		prev_level = current_level;
	}

	/* If we detected at least 4 distinct steps, it's likely a staircase */
	return (steps_detected >= 4) ? 1 : 0;
}

/**
 * Detect multiburst pattern
 */
static int detect_multiburst(vits_decoder_t *vits, int16_t *line)
{
	/* Multiburst has varying frequencies, look for oscillations */
	int active_start = vits->line_length / 8;
	int active_end = vits->line_length * 7 / 8;
	int zero_crossings = 0;
	int i;

	int prev_sign = (line[active_start] > 0) ? 1 : -1;
	for(i = active_start + 1; i < active_end; i++)
	{
		int curr_sign = (line[i] > 0) ? 1 : -1;
		if(curr_sign != prev_sign)
		{
			zero_crossings++;
		}
		prev_sign = curr_sign;
	}

	/* Multiburst should have many zero crossings (high frequency content) */
	return (zero_crossings > 20) ? 1 : 0;
}

/**
 * Analyze pulse and bar signal for measurements
 */
int vits_analyze_pulse_bar(vits_decoder_t *vits, int16_t *line)
{
	int pulse_start = (int)(PULSE_START_US * vits->sample_rate / 1000000.0);
	int pulse_width = (int)(PULSE_WIDTH_US * vits->sample_rate / 1000000.0);
	int bar_start = (int)(BAR_START_US * vits->sample_rate / 1000000.0);
	int bar_width = (int)(BAR_WIDTH_US * vits->sample_rate / 1000000.0);

	/* Measure white level from pulse */
	int32_t white_sum = 0;
	int i;
	for(i = 0; i < pulse_width && (pulse_start + i) < vits->line_length; i++)
	{
		white_sum += line[pulse_start + i];
	}
	vits->measurements.white_level = white_sum / pulse_width;

	/* Measure black level from back porch */
	int black_start = vits->line_length / 16;  /* After sync */
	int black_width = vits->line_length / 32;
	int32_t black_sum = 0;
	for(i = 0; i < black_width && (black_start + i) < vits->line_length; i++)
	{
		black_sum += line[black_start + i];
	}
	vits->measurements.black_level = black_sum / black_width;

	/* Calculate contrast ratio */
	if(vits->measurements.black_level != 0)
	{
		vits->measurements.contrast_ratio =
			(vits->measurements.white_level * 100) / abs(vits->measurements.black_level);
	}

	return 1;
}

/**
 * Analyze multiburst signal for frequency response
 */
int vits_analyze_multiburst(vits_decoder_t *vits, int16_t *line)
{
	/* Simplified analysis - measure peak-to-peak amplitude in different segments */
	int active_start = vits->line_length / 8;
	int segment_width = (vits->line_length - active_start) / 6;
	int i, j;

	for(i = 0; i < 6; i++)
	{
		int seg_start = active_start + i * segment_width;
		int16_t min_val = 32767, max_val = -32768;

		for(j = 0; j < segment_width && (seg_start + j) < vits->line_length; j++)
		{
			int16_t val = line[seg_start + j];
			if(val < min_val) min_val = val;
			if(val > max_val) max_val = val;
		}

		vits->measurements.freq_response[i] = max_val - min_val;
	}

	/* Estimate bandwidth (find where response drops to 50%) */
	int ref_level = vits->measurements.freq_response[0];
	for(i = 0; i < 6; i++)
	{
		if(vits->measurements.freq_response[i] < ref_level / 2)
		{
			vits->measurements.bandwidth_mhz = i + 1;  /* Simplified */
			break;
		}
	}

	return 1;
}

/**
 * Process a video line for VITS signals
 */
vits_type_t vits_decoder_process_line(vits_decoder_t *vits, int16_t *line, int line_num)
{
	vits_type_t detected_type = VITS_TYPE_NONE;

	/* Only process VITS lines */
	if(line_num < vits->vits_line_start || line_num > vits->vits_line_end)
	{
		return VITS_TYPE_NONE;
	}

	vits->lines_processed++;

	/* Try to detect different VITS patterns */
	if(detect_pulse_bar(vits, line))
	{
		detected_type = VITS_TYPE_PULSE_BAR;
		vits_analyze_pulse_bar(vits, line);
		vits->signals_detected++;
	}
	else if(detect_multiburst(vits, line))
	{
		detected_type = VITS_TYPE_MULTIBURST;
		vits_analyze_multiburst(vits, line);
		vits->signals_detected++;
	}
	else if(detect_staircase(vits, line))
	{
		detected_type = VITS_TYPE_STAIRCASE;
		vits->signals_detected++;
	}

	/* Store detection result */
	int line_index = line_num - vits->vits_line_start;
	if(line_index >= 0 && line_index < 10)
	{
		vits->detected_types[line_index] = detected_type;
		if(detected_type != VITS_TYPE_NONE)
		{
			vits->detection_confidence[line_index]++;
		}
	}

	return detected_type;
}

/**
 * Get signal type name
 */
const char* vits_type_to_string(vits_type_t type)
{
	switch(type)
	{
		case VITS_TYPE_PULSE_BAR:  return "Pulse & Bar";
		case VITS_TYPE_STAIRCASE:  return "Staircase";
		case VITS_TYPE_MULTIBURST: return "Multiburst";
		case VITS_TYPE_COLOR_BARS: return "Color Bars";
		case VITS_TYPE_WINDOW:     return "Window";
		case VITS_TYPE_CUSTOM:     return "Custom";
		case VITS_TYPE_NONE:
		default:                   return "None";
	}
}

/**
 * Get current VITS measurements as a formatted string
 */
int vits_decoder_get_info(vits_decoder_t *vits, char *buffer, int size)
{
	if(vits->signals_detected == 0)
	{
		return snprintf(buffer, size, "VITS: No test signals detected");
	}

	/* Find most common detected signal */
	int max_conf = 0;
	vits_type_t primary_type = VITS_TYPE_NONE;
	int i;
	for(i = 0; i < 10; i++)
	{
		if(vits->detection_confidence[i] > max_conf)
		{
			max_conf = vits->detection_confidence[i];
			primary_type = vits->detected_types[i];
		}
	}

	if(primary_type == VITS_TYPE_PULSE_BAR)
	{
		return snprintf(buffer, size,
			"VITS: %s | White: %d | Black: %d | Contrast: %d:1",
			vits_type_to_string(primary_type),
			vits->measurements.white_level,
			vits->measurements.black_level,
			vits->measurements.contrast_ratio / 100);
	}
	else if(primary_type == VITS_TYPE_MULTIBURST)
	{
		return snprintf(buffer, size,
			"VITS: %s | Bandwidth: ~%d MHz",
			vits_type_to_string(primary_type),
			vits->measurements.bandwidth_mhz);
	}
	else
	{
		return snprintf(buffer, size,
			"VITS: %s detected",
			vits_type_to_string(primary_type));
	}
}
