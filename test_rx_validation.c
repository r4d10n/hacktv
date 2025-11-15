/* Simple validation test for receiver components */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "src/receiver.h"
#include "src/common.h"

int main(void)
{
	printf("HackRX Receiver Validation Test\n");
	printf("================================\n\n");

	/* Test 1: YUV to RGB conversion */
	printf("Test 1: YUV to RGB Conversion\n");
	printf("-----------------------------\n");

	uint8_t r, g, b;

	// White (Y=max, U=0, V=0)
	yuv_to_rgb(32767, 0, 0, &r, &g, &b);
	printf("  YUV(32767,0,0) -> RGB(%d,%d,%d) [expected: ~255,255,255]\n", r, g, b);

	// Black (Y=min, U=0, V=0)
	yuv_to_rgb(-32768, 0, 0, &r, &g, &b);
	printf("  YUV(-32768,0,0) -> RGB(%d,%d,%d) [expected: ~0,0,0]\n", r, g, b);

	// Gray (Y=0, U=0, V=0)
	yuv_to_rgb(0, 0, 0, &r, &g, &b);
	printf("  YUV(0,0,0) -> RGB(%d,%d,%d) [expected: ~127,127,127]\n", r, g, b);

	printf("\n");

	/* Test 2: Sync detector */
	printf("Test 2: Sync Detection\n");
	printf("----------------------\n");

	rx_sync_t sync;
	int line_start, field;

	// Initialize for PAL (1024 samples/line)
	rx_sync_init(&sync, 16000000, 1024, 625, 1);

	printf("  Initialized sync detector\n");
	printf("  Sync level: %d\n", sync.sync_level);
	printf("  Blanking level: %d\n", sync.blanking_level);

	// Feed some test samples
	int samples_fed = 0;
	int syncs_detected = 0;

	// Simulate sync pulse
	for(int i = 0; i < 75; i++) {
		rx_sync_process(&sync, -32000, &line_start, &field);
		if(line_start) syncs_detected++;
		samples_fed++;
	}

	// Simulate active video
	for(int i = 0; i < 900; i++) {
		int video = (i % 100 < 50) ? -10000 : 32000;  // Alternating pattern
		rx_sync_process(&sync, video, &line_start, &field);
		if(line_start) syncs_detected++;
		samples_fed++;
	}

	// Another sync pulse
	for(int i = 0; i < 75; i++) {
		rx_sync_process(&sync, -32000, &line_start, &field);
		if(line_start) syncs_detected++;
		samples_fed++;
	}

	printf("  Fed %d samples\n", samples_fed);
	printf("  Detected %d sync pulses\n", syncs_detected);
	printf("  Sync status: %s\n", sync.in_sync ? "LOCKED" : "SEARCHING");

	printf("\n");

	/* Test 3: FM Demodulator */
	printf("Test 3: FM Demodulator\n");
	printf("----------------------\n");

	rx_fm_demod_t fm_demod;
	rx_fm_demod_init(&fm_demod, 16000000, 10000000.0);

	printf("  Initialized FM demodulator\n");
	printf("  Sample rate: %d Hz\n", fm_demod.sample_rate);
	printf("  Deviation: %.0f Hz\n", fm_demod.deviation);

	// Test with some carrier samples
	int16_t result = rx_fm_demod_process(&fm_demod, 10000, 0);
	printf("  Demod result (sample 1): %d\n", result);

	result = rx_fm_demod_process(&fm_demod, 10000, 1000);
	printf("  Demod result (sample 2): %d\n", result);

	rx_fm_demod_free(&fm_demod);

	printf("\n");

	printf("All basic tests completed!\n");
	printf("\nNOTE: These are basic functionality tests.\n");
	printf("Full signal processing requires proper test signals.\n");

	return 0;
}
