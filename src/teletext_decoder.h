/* hackrx - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - Teletext Decoder Implementation                      */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _TELETEXT_DECODER_H
#define _TELETEXT_DECODER_H

#include <stdint.h>
#include <stdio.h>

/* Teletext packet size */
#define TTX_PACKET_SIZE 45

/* VBI line range for teletext */
#define TTX_LINE_START_625 7   /* First teletext line in 625-line system */
#define TTX_LINE_END_625   22  /* Last teletext line in 625-line system */
#define TTX_LINE_START_525 10  /* First teletext line in 525-line system */
#define TTX_LINE_END_525   21  /* Last teletext line in 525-line system */

/* Teletext page structure */
typedef struct _ttx_page_t {
	uint16_t page_number;        /* 100-899 */
	uint8_t subpage;             /* 0-255 */
	char content[25][40];        /* 25 rows, 40 columns */
	int valid;
	struct _ttx_page_t *next;
} ttx_page_t;

/* Teletext decoder state */
typedef struct {
	int sample_rate;
	int line_length;             /* Samples per line */
	int is_625_line;             /* 1 for PAL (625), 0 for NTSC (525) */

	/* Clock run-in detection */
	int clock_run_in_length;     /* Expected clock run-in samples */
	int data_start;              /* Sample position where data starts */

	/* Bit extraction */
	int samples_per_bit;

	/* Current packet being decoded */
	uint8_t packet[TTX_PACKET_SIZE];
	int packet_valid;

	/* Page storage */
	ttx_page_t *pages;           /* Linked list of captured pages */
	ttx_page_t *current_page;    /* Page currently being assembled */

	/* Subtitle extraction */
	char subtitles[4][40];       /* Up to 4 subtitle rows */
	int subtitle_valid;

	/* Statistics */
	uint32_t packets_received;
	uint32_t packets_errors;
	uint32_t pages_captured;

	/* Output file for raw packets (optional) */
	FILE *raw_output;

} ttx_decoder_t;

/* Initialize teletext decoder */
extern int ttx_decoder_init(ttx_decoder_t *dec, int sample_rate, int line_length, int is_625_line);

/* Process VBI line samples */
extern int ttx_decoder_process_line(ttx_decoder_t *dec, const int16_t *line_samples, int line_number);

/* Get captured page by number */
extern ttx_page_t* ttx_decoder_get_page(ttx_decoder_t *dec, uint16_t page_number);

/* Get current subtitles (returns 1 if available) */
extern int ttx_decoder_get_subtitles(ttx_decoder_t *dec, char subtitles[4][40]);

/* Save captured pages to file */
extern int ttx_decoder_save_pages(ttx_decoder_t *dec, const char *filename);

/* Enable raw packet output */
extern int ttx_decoder_enable_raw_output(ttx_decoder_t *dec, const char *filename);

/* Free resources */
extern void ttx_decoder_free(ttx_decoder_t *dec);

#endif
