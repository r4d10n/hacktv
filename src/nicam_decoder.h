/* hackrx - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - NICAM 728 Decoder Implementation                     */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _NICAM_DECODER_H
#define _NICAM_DECODER_H

#include <stdint.h>
#include "common.h"
#include "nicam728.h"

/* NICAM decoder state */
typedef struct {
	int sample_rate;
	double subcarrier_freq;  /* 6.552 MHz for PAL */

	/* DQPSK demodulator state */
	cint32_t prev_symbol;
	int symbol_rate;
	int samples_per_symbol;
	int symbol_counter;

	/* Symbol buffer */
	uint8_t symbols[NICAM_FRAME_SYMS];
	int symbol_index;

	/* Frame synchronization */
	int sync_state;  /* 0 = searching, 1 = locked */
	int sync_errors;
	uint8_t frame[NICAM_FRAME_BYTES];
	int frame_bit_index;

	/* Audio output buffer */
	int16_t audio_out[NICAM_AUDIO_LEN * 2];
	int audio_available;

	/* Mode information */
	uint8_t mode;
	uint8_t reserve;

	/* PRN sequence for descrambling */
	uint8_t prn[NICAM_FRAME_BYTES - 1];

	/* De-emphasis filter state */
	int fir_p;
	int16_t fir_l[_J17_NTAPS];
	int16_t fir_r[_J17_NTAPS];

	/* Statistics */
	uint32_t frames_decoded;
	uint32_t frames_errors;

} nicam_decoder_t;

/* Initialize NICAM decoder */
extern int nicam_decoder_init(nicam_decoder_t *dec, int sample_rate, double subcarrier_freq);

/* Process IQ samples and extract NICAM audio */
extern int nicam_decoder_process(nicam_decoder_t *dec, const int16_t *iq_samples, int num_samples);

/* Get decoded audio if available (returns number of samples, 0 if none) */
extern int nicam_decoder_get_audio(nicam_decoder_t *dec, int16_t *audio_out);

/* Free resources */
extern void nicam_decoder_free(nicam_decoder_t *dec);

#endif
