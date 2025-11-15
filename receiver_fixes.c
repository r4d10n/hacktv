/* receiver_fixes.c - Critical fixes for receiver demodulation */

/*
 * ISSUE 1: AM demodulator loses sign information
 * Fix: Add baseband bypass mode
 */

/* Add this to receiver.c after rx_am_demod_process */

int16_t rx_baseband_process(int16_t i, int16_t q)
{
	/* For baseband signals (Q~=0), just return I channel directly */
	/* This preserves sign information needed for sync detection */
	(void)q;  /* Unused */
	return i;
}

/*
 * ISSUE 2: Signal levels not properly scaled
 * The demodulated signal needs to match expected video levels
 */

/* Improved AM demodulator that handles baseband better */
int16_t rx_am_demod_process_improved(rx_am_demod_t *demod, int16_t i, int16_t q)
{
	int32_t magnitude;
	int16_t output;

	/* Check if this is baseband (Q is very small compared to I) */
	int32_t abs_i = abs(i);
	int32_t abs_q = abs(q);

	/* If Q is less than 5% of I, treat as baseband */
	if(abs_q < (abs_i / 20))
	{
		/* Baseband mode - return I directly */
		return i;
	}

	/* Standard AM envelope detection */
	if(abs_i > abs_q)
	{
		magnitude = abs_i + (abs_q >> 1);
	}
	else
	{
		magnitude = abs_q + (abs_i >> 1);
	}

	output = (int16_t)CLAMP(magnitude, INT16_MIN, INT16_MAX);

	return output;
}

/*
 * ISSUE 3: Monochrome decoding not extracting Y properly
 * The Y value is always 0 because line buffer values aren't being used correctly
 */

/* Fixed monochrome line decoding */
void rx_mono_decode_line_fixed(int16_t *line, uint32_t *rgb_out, int width)
{
	int x;
	uint8_t gray;

	for(x = 0; x < width; x++)
	{
		/* Get Y value from line buffer */
		int16_t y = line[x];

		/* Convert from signed 16-bit to unsigned 8-bit */
		/* Map: -32768 -> 0 (black), 0 -> 127 (gray), 32767 -> 255 (white) */
		int32_t scaled = ((int32_t)y + 32768) >> 8;
		gray = (uint8_t)CLAMP(scaled, 0, 255);

		/* Pack into RGB32 */
		rgb_out[x] = (0xFF << 24) | (gray << 16) | (gray << 8) | gray;
	}
}

/*
 * ISSUE 4: Sync detection AGC needs tuning
 * AGC should adapt faster to signal level changes
 */

/* Improved sync detection with better AGC */
int rx_sync_process_improved(rx_sync_t *sync, int16_t sample, int *line_start, int *field)
{
	int sync_detected = 0;

	*line_start = 0;
	*field = sync->current_field;

	/* Improved AGC - accumulate absolute values */
	int32_t abs_sample = abs(sample);
	sync->agc_accumulator += abs_sample;

	/* Update AGC every 100 samples for faster adaptation */
	if(sync->samples_since_sync % 100 == 0 && sync->agc_accumulator > 0)
	{
		sync->agc_level = sync->agc_accumulator / 100;
		sync->agc_accumulator = 0;

		/* Update sync threshold - sync pulses are most negative */
		/* Set threshold at 60% of peak-to-peak */
		sync->sync_level = -(sync->agc_level * 6) / 10;
		sync->blanking_level = -sync->agc_level / 4;
	}

	/* Detect sync pulse (signal goes below threshold) */
	/* Also require sufficient time since last sync to avoid triggering on noise */
	if(sample < sync->sync_level && sync->samples_since_sync > sync->line_length / 2)
	{
		sync_detected = 1;
		*line_start = 1;

		sync->current_line++;
		if(sync->current_line >= sync->frame_lines)
		{
			sync->current_line = 0;
			if(sync->interlaced)
			{
				sync->current_field = !sync->current_field;
			}
		}

		sync->samples_since_sync = 0;
		sync->in_sync = 1;
	}
	else
	{
		sync->samples_since_sync++;

		/* Lose sync if we haven't seen a sync pulse in 2 line periods */
		if(sync->samples_since_sync > sync->line_length * 2)
		{
			sync->in_sync = 0;
		}
	}

	return sync->in_sync;
}
