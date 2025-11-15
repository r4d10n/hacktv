/* hackrx - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - Teletext Decoder Implementation                      */
/*                                                                       */
/* Teletext (World System Teletext Level 1) Decoder                      */
/* Based on ETS 300 706 specification                                    */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "teletext_decoder.h"

/* Hamming 8/4 decode table */
static const uint8_t _hamming84_decode[256] = {
	0x01, 0xFF, 0x01, 0x01, 0xFF, 0x00, 0x01, 0xFF,
	0xFF, 0x02, 0x01, 0xFF, 0x0A, 0xFF, 0xFF, 0x07,
	0xFF, 0x00, 0x01, 0xFF, 0x00, 0x00, 0xFF, 0x00,
	0x06, 0xFF, 0xFF, 0x0B, 0xFF, 0x00, 0x03, 0xFF,
	0xFF, 0x0C, 0x01, 0xFF, 0x04, 0xFF, 0xFF, 0x07,
	0x06, 0xFF, 0xFF, 0x07, 0xFF, 0x07, 0x07, 0x07,
	0x06, 0xFF, 0xFF, 0x05, 0xFF, 0x00, 0x0D, 0xFF,
	0x06, 0x06, 0x06, 0xFF, 0x06, 0xFF, 0xFF, 0x07,
	0xFF, 0x02, 0x01, 0xFF, 0x04, 0xFF, 0xFF, 0x09,
	0x02, 0x02, 0xFF, 0x02, 0xFF, 0x02, 0x03, 0xFF,
	0x08, 0xFF, 0xFF, 0x05, 0xFF, 0x00, 0x03, 0xFF,
	0xFF, 0x02, 0x03, 0xFF, 0x03, 0xFF, 0x03, 0x03,
	0x04, 0xFF, 0xFF, 0x05, 0x04, 0x04, 0x04, 0xFF,
	0xFF, 0x02, 0x0F, 0xFF, 0x04, 0xFF, 0xFF, 0x07,
	0xFF, 0x05, 0x05, 0x05, 0x04, 0xFF, 0xFF, 0x05,
	0x06, 0xFF, 0xFF, 0x05, 0xFF, 0x0E, 0x03, 0xFF,
	0xFF, 0x0C, 0x01, 0xFF, 0x0A, 0xFF, 0xFF, 0x09,
	0x0A, 0xFF, 0xFF, 0x0B, 0x0A, 0x0A, 0x0A, 0xFF,
	0x08, 0xFF, 0xFF, 0x0B, 0xFF, 0x00, 0x0D, 0xFF,
	0xFF, 0x0B, 0x0B, 0x0B, 0x0A, 0xFF, 0xFF, 0x0B,
	0x0C, 0x0C, 0xFF, 0x0C, 0xFF, 0x0C, 0x0D, 0xFF,
	0xFF, 0x0C, 0x0F, 0xFF, 0x0A, 0xFF, 0xFF, 0x07,
	0xFF, 0x0C, 0x0D, 0xFF, 0x0D, 0xFF, 0x0D, 0x0D,
	0x06, 0xFF, 0xFF, 0x0B, 0xFF, 0x0E, 0x0D, 0xFF,
	0x08, 0xFF, 0xFF, 0x09, 0xFF, 0x09, 0x09, 0x09,
	0xFF, 0x02, 0x0F, 0xFF, 0x0A, 0xFF, 0xFF, 0x09,
	0x08, 0x08, 0x08, 0xFF, 0x08, 0xFF, 0xFF, 0x09,
	0x08, 0xFF, 0xFF, 0x0B, 0xFF, 0x0E, 0x03, 0xFF,
	0xFF, 0x0C, 0x0F, 0xFF, 0x04, 0xFF, 0xFF, 0x09,
	0x0F, 0xFF, 0x0F, 0x0F, 0xFF, 0x0E, 0x0F, 0xFF,
	0x08, 0xFF, 0xFF, 0x05, 0xFF, 0x0E, 0x0D, 0xFF,
	0xFF, 0x0E, 0x0F, 0xFF, 0x0E, 0x0E, 0xFF, 0x0E
};

/* Parity table for odd parity */
static const uint8_t _parity[128] = {
	0x80, 0x01, 0x02, 0x83, 0x04, 0x85, 0x86, 0x07,
	0x08, 0x89, 0x8A, 0x0B, 0x8C, 0x0D, 0x0E, 0x8F,
	0x10, 0x91, 0x92, 0x13, 0x94, 0x15, 0x16, 0x97,
	0x98, 0x19, 0x1A, 0x9B, 0x1C, 0x9D, 0x9E, 0x1F,
	0x20, 0xA1, 0xA2, 0x23, 0xA4, 0x25, 0x26, 0xA7,
	0xA8, 0x29, 0x2A, 0xAB, 0x2C, 0xAD, 0xAE, 0x2F,
	0xB0, 0x31, 0x32, 0xB3, 0x34, 0xB5, 0xB6, 0x37,
	0x38, 0xB9, 0xBA, 0x3B, 0xBC, 0x3D, 0x3E, 0xBF,
	0x40, 0xC1, 0xC2, 0x43, 0xC4, 0x45, 0x46, 0xC7,
	0xC8, 0x49, 0x4A, 0xCB, 0x4C, 0xCD, 0xCE, 0x4F,
	0xD0, 0x51, 0x52, 0xD3, 0x54, 0xD5, 0xD6, 0x57,
	0x58, 0xD9, 0xDA, 0x5B, 0xDC, 0x5D, 0x5E, 0xDF,
	0xE0, 0x61, 0x62, 0xE3, 0x64, 0xE5, 0xE6, 0x67,
	0x68, 0xE9, 0xEA, 0x6B, 0xEC, 0x6D, 0x6E, 0xEF,
	0x70, 0xF1, 0xF2, 0x73, 0xF4, 0x75, 0x76, 0xF7,
	0xF8, 0x79, 0x7A, 0xFB, 0x7C, 0xFD, 0xFE, 0x7F
};

/* Unham 8/4 - returns 0xFF on error */
static uint8_t _unham84(uint8_t byte)
{
	return _hamming84_decode[byte];
}

/* Remove parity bit */
static uint8_t _deparity(uint8_t byte)
{
	/* Check if parity is correct */
	if(_parity[byte & 0x7F] != byte)
	{
		return 0x00;  /* Parity error */
	}
	return byte & 0x7F;
}

/* Detect clock run-in and extract bit timing */
static int _detect_clock_run_in(const int16_t *samples, int num_samples, int *bit_start, int *samples_per_bit)
{
	/* Clock run-in is alternating 1/0 pattern for at least 16 bits */
	/* Teletext data rate is 6.9375 Mbit/s for 625-line, 5.727272 Mbit/s for 525-line */

	int i, transitions = 0;
	int last_level = 0;
	int transition_positions[32];
	int avg_period;

	/* Detect zero crossings */
	for(i = 1; i < num_samples && transitions < 32; i++)
	{
		int current_level = (samples[i] > 0) ? 1 : 0;
		if(current_level != last_level)
		{
			transition_positions[transitions++] = i;
			last_level = current_level;
		}
	}

	/* Need at least 10 transitions for reliable clock */
	if(transitions < 10)
	{
		return -1;
	}

	/* Calculate average period between transitions */
	avg_period = 0;
	for(i = 1; i < transitions; i++)
	{
		avg_period += transition_positions[i] - transition_positions[i-1];
	}
	avg_period /= (transitions - 1);

	*samples_per_bit = avg_period;  /* One bit period */
	*bit_start = transition_positions[transitions - 1] + avg_period;  /* Start after clock run-in */

	return 0;
}

/* Extract bits from NRZ samples */
static int _extract_bits(const int16_t *samples, int bit_start, int samples_per_bit, uint8_t *bytes, int num_bytes)
{
	int byte_idx, bit_idx, sample_pos;
	int16_t sample_val;

	for(byte_idx = 0; byte_idx < num_bytes; byte_idx++)
	{
		bytes[byte_idx] = 0;

		for(bit_idx = 0; bit_idx < 8; bit_idx++)
		{
			/* Sample at bit center */
			sample_pos = bit_start + (byte_idx * 8 + bit_idx) * samples_per_bit + samples_per_bit / 2;

			sample_val = samples[sample_pos];

			/* NRZ: positive = 1, negative = 0 */
			if(sample_val > 0)
			{
				bytes[byte_idx] |= (1 << bit_idx);  /* LSB first */
			}
		}
	}

	return 0;
}

/* Parse packet and extract page data */
static int _parse_packet(ttx_decoder_t *dec, const uint8_t *packet)
{
	uint8_t magazine, packet_num, page_units, page_tens;
	uint16_t page_number;
	int i;

	/* Check framing code (should be 0xE7 0x27 but inverted bitwise) */
	/* Actually teletext uses clock run-in followed by framing code */

	/* Decode magazine and packet number from bytes 2-3 (Hamming 8/4) */
	magazine = _unham84(packet[3]) & 0x07;
	if(magazine == 0) magazine = 8;

	packet_num = (_unham84(packet[4]) & 0x01) | ((_unham84(packet[3]) & 0x08) >> 2);

	if(packet_num == 0xFF || magazine == 0xFF)
	{
		return -1;  /* Hamming error */
	}

	/* Packet 0 is header with page number */
	if(packet_num == 0)
	{
		page_units = _unham84(packet[5]);
		page_tens = _unham84(packet[6]);

		if(page_units == 0xFF || page_tens == 0xFF)
		{
			return -1;
		}

		page_number = (magazine * 100) + (page_tens * 10) + page_units;

		/* Create or update page */
		if(!dec->current_page || dec->current_page->page_number != page_number)
		{
			/* Allocate new page */
			ttx_page_t *new_page = calloc(1, sizeof(ttx_page_t));
			if(new_page)
			{
				new_page->page_number = page_number;
				new_page->valid = 1;
				new_page->next = dec->pages;
				dec->pages = new_page;
				dec->current_page = new_page;
				dec->pages_captured++;
			}
		}

		/* Extract header text (bytes 13-44 with parity) */
		if(dec->current_page)
		{
			for(i = 0; i < 32; i++)
			{
				dec->current_page->content[0][i] = _deparity(packet[13 + i]);
			}
		}
	}
	/* Packets 1-24 contain page content */
	else if(packet_num >= 1 && packet_num <= 24 && dec->current_page)
	{
		/* Extract text data (bytes 5-44 with parity) */
		for(i = 0; i < 40; i++)
		{
			dec->current_page->content[packet_num][i] = _deparity(packet[5 + i]);
		}

		/* Check for subtitles (page 888 or subtitle flag) */
		if(dec->current_page->page_number == 888 && packet_num >= 1 && packet_num <= 4)
		{
			for(i = 0; i < 40; i++)
			{
				dec->subtitles[packet_num - 1][i] = dec->current_page->content[packet_num][i];
			}
			dec->subtitle_valid = 1;
		}
	}

	dec->packets_received++;

	/* Write raw packet if output enabled */
	if(dec->raw_output)
	{
		fwrite(packet, 1, TTX_PACKET_SIZE, dec->raw_output);
	}

	return 0;
}

/* Initialize decoder */
int ttx_decoder_init(ttx_decoder_t *dec, int sample_rate, int line_length, int is_625_line)
{
	memset(dec, 0, sizeof(ttx_decoder_t));

	dec->sample_rate = sample_rate;
	dec->line_length = line_length;
	dec->is_625_line = is_625_line;

	/* Teletext data rate */
	double data_rate = is_625_line ? 6937500.0 : 5727272.0;  /* bits/s */
	dec->samples_per_bit = (int)(sample_rate / data_rate);

	/* Clock run-in starts around 12µs into line */
	dec->clock_run_in_length = (int)(sample_rate * 12e-6);

	return 0;
}

/* Process VBI line */
int ttx_decoder_process_line(ttx_decoder_t *dec, const int16_t *line_samples, int line_number)
{
	int bit_start, samples_per_bit;
	uint8_t packet[TTX_PACKET_SIZE];

	/* Check if line is in teletext range */
	if(dec->is_625_line)
	{
		if(line_number < TTX_LINE_START_625 || line_number > TTX_LINE_END_625)
			return 0;
	}
	else
	{
		if(line_number < TTX_LINE_START_525 || line_number > TTX_LINE_END_525)
			return 0;
	}

	/* Detect clock run-in and get bit timing */
	if(_detect_clock_run_in(line_samples, dec->line_length, &bit_start, &samples_per_bit) != 0)
	{
		dec->packets_errors++;
		return -1;
	}

	/* Extract packet bits */
	if(_extract_bits(line_samples, bit_start, samples_per_bit, packet, TTX_PACKET_SIZE) != 0)
	{
		dec->packets_errors++;
		return -1;
	}

	/* Parse packet */
	return _parse_packet(dec, packet);
}

/* Get page by number */
ttx_page_t* ttx_decoder_get_page(ttx_decoder_t *dec, uint16_t page_number)
{
	ttx_page_t *page = dec->pages;

	while(page)
	{
		if(page->page_number == page_number && page->valid)
		{
			return page;
		}
		page = page->next;
	}

	return NULL;
}

/* Get subtitles */
int ttx_decoder_get_subtitles(ttx_decoder_t *dec, char subtitles[4][40])
{
	if(!dec->subtitle_valid)
	{
		return 0;
	}

	memcpy(subtitles, dec->subtitles, sizeof(dec->subtitles));
	return 1;
}

/* Save pages to file */
int ttx_decoder_save_pages(ttx_decoder_t *dec, const char *filename)
{
	FILE *fp = fopen(filename, "w");
	if(!fp)
	{
		return -1;
	}

	ttx_page_t *page = dec->pages;
	int row;

	while(page)
	{
		if(page->valid)
		{
			fprintf(fp, "\n========== Page %03d ==========\n", page->page_number);

			for(row = 0; row < 25; row++)
			{
				fprintf(fp, "%.*s\n", 40, page->content[row]);
			}
		}
		page = page->next;
	}

	fclose(fp);
	return 0;
}

/* Enable raw output */
int ttx_decoder_enable_raw_output(ttx_decoder_t *dec, const char *filename)
{
	dec->raw_output = fopen(filename, "wb");
	return (dec->raw_output != NULL) ? 0 : -1;
}

/* Free resources */
void ttx_decoder_free(ttx_decoder_t *dec)
{
	/* Free all pages */
	ttx_page_t *page = dec->pages;
	while(page)
	{
		ttx_page_t *next = page->next;
		free(page);
		page = next;
	}

	if(dec->raw_output)
	{
		fclose(dec->raw_output);
	}

	memset(dec, 0, sizeof(ttx_decoder_t));
}
