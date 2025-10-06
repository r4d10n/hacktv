/* hacktv-rx - Analogue TV receiver for SoapySDR */
/*=======================================================================*/
/* Copyright 2017 Philip Heron <phil@sanslogic.co.uk>                    */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*                                                                       */
/* This program is distributed in the hope that it will be useful,       */
/* but WITHOUT ANY WARRANTY; without even the implied warranty of        */
/* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         */
/* GNU General Public License for more details.                          */
/*                                                                       */
/* You should have received a copy of the GNU General Public License     */
/* along with this program.  If not, see <http://www.gnu.org/licenses/>. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <getopt.h>
#include <signal.h>
#include <SoapySDR/Device.h>
#include <SoapySDR/Formats.h>
#define _USE_MATH_DEFINES
#include <SoapySDR/Version.h>
#include <math.h>
#include "hacktv-rx.h"

#define RX_BUFFER_SIZE 16384

typedef enum {
    STATE_SEARCHING_FOR_SYNC,
    STATE_IN_SYNC_PULSE,
    STATE_IN_BACK_PORCH,
    STATE_IN_VIDEO_LINE
} sync_state_t;

typedef struct {
    const video_mode_t *mode;
    double sample_rate;
    sync_state_t state;

    // Timing calculated from mode and sample rate
    int samples_per_line;
    int h_sync_len_samples;
    int v_sync_pulse_len_samples;

    // State machine counters
    int line_sample_count;
    int sync_pulse_sample_count;
    int end_of_sync_counter;

    // Signal level tracking for automatic thresholding
    float min_level;
    float max_level;
    float sync_threshold;
    int level_avg_count;

    // Frame buffer
    float **frame_buffer;
    float *current_line_buffer;
    int current_line;

    // Color PLL
    color_pll_t pll;
    int back_porch_len_samples;
    int color_burst_len_samples;

    // Audio
    audio_state_t audio;

} rx_state_t;

static volatile sig_atomic_t _abort = 0;

static void update_pll(float i_sample, float q_sample, rx_state_t* rx) {
    // Generate local oscillator signal
    float lo_i = cosf(rx->pll.phase);
    float lo_q = sinf(rx->pll.phase);

    // Phase detector (simplified): Q_lo*I_in - I_lo*Q_in
    float phase_error = lo_q * i_sample - lo_i * q_sample;

    // Loop filter (PI controller)
    const float Kp = 0.0005f; // Proportional gain
    const float Ki = 0.00005f; // Integral gain

    rx->pll.error_sum += phase_error * Ki;
    float correction = phase_error * Kp + rx->pll.error_sum;

    // Update PLL phase and frequency
    rx->pll.frequency = rx->mode->color_subcarrier_freq + correction;
    rx->pll.phase += (rx->pll.frequency / rx->sample_rate) * 2.0f * M_PI;

    // Keep phase wrapped
    if (rx->pll.phase > M_PI) rx->pll.phase -= 2.0f * M_PI;
    if (rx->pll.phase < -M_PI) rx->pll.phase += 2.0f * M_PI;
}


static void save_frame_as_ppm(const char *filename, rx_state_t *rx, int verbose) {
    FILE *f = fopen(filename, "wb");
    if (!f) {
        perror("Failed to open PPM file");
        return;
    }

    int width = rx->samples_per_line - rx->h_sync_len_samples - rx->back_porch_len_samples;
    int height = rx->mode->active_lines;

    fprintf(f, "P6\n%d %d\n255\n", width, height);

    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            if (rx->frame_buffer[y] != NULL) {
                // For now, just output grayscale
                float val = rx->frame_buffer[y][x];
                float normalized = (val - rx->sync_threshold) / (rx->max_level - rx->sync_threshold);
                if (normalized < 0.0f) normalized = 0.0f;
                if (normalized > 1.0f) normalized = 1.0f;

                unsigned char pixel = (unsigned char)(normalized * 255.0f);
                fputc(pixel, f); // R
                fputc(pixel, f); // G
                fputc(pixel, f); // B
            } else {
                 fputc(0, f);
                 fputc(0, f);
                 fputc(0, f);
            }
        }
    }
    fclose(f);
    if (verbose) {
        printf("\nSaved frame to %s\n", filename);
    }
}

static void process_samples(int16_t *buffer, int length, int verbose, rx_state_t *rx) {
    for (int i = 0; i < length; i++) {
        float i_val = (float)buffer[i * 2];
        float q_val = (float)buffer[i * 2 + 1];
        float current_level = sqrtf(i_val * i_val + q_val * q_val);

        // Update min/max levels and calculate sync threshold
        if (rx->level_avg_count < 100000) { // Average over a number of samples to stabilize
            if (current_level < rx->min_level) rx->min_level = current_level;
            if (current_level > rx->max_level) rx->max_level = current_level;
            rx->level_avg_count++;
        } else {
            // Set sync threshold to be 25% of the way from min to max.
            // This is a heuristic and may need tuning.
            rx->sync_threshold = rx->min_level + (rx->max_level - rx->min_level) * 0.25f;
        }

        switch (rx->state) {
            case STATE_SEARCHING_FOR_SYNC:
                if (current_level < rx->sync_threshold && rx->sync_threshold > 0) {
                    rx->state = STATE_IN_SYNC_PULSE;
                    rx->sync_pulse_sample_count = 1;
                }
                break;

            case STATE_IN_SYNC_PULSE:
                if (current_level < rx->sync_threshold) {
                    rx->sync_pulse_sample_count++;
                    rx->end_of_sync_counter = 0; // Reset counter as we are still in sync
                } else {
                    // Wait for a few samples to be sure the sync pulse has ended
                    rx->end_of_sync_counter++;
                    if (rx->end_of_sync_counter > 4) { // Debounce threshold
                        // Check for V-sync (much longer than H-sync)
                        if (rx->sync_pulse_sample_count > rx->v_sync_pulse_len_samples * 0.8) {
                             if (verbose) {
                                //printf("\n--- V-SYNC ---\n");
                            }
                            rx->current_line = 0;
                            rx->state = STATE_SEARCHING_FOR_SYNC;
                        }
                        // Check for H-sync
                        else if (rx->sync_pulse_sample_count > rx->h_sync_len_samples * 0.5 &&
                            rx->sync_pulse_sample_count < rx->h_sync_len_samples * 1.5) {
                            rx->state = STATE_IN_BACK_PORCH;
                            rx->line_sample_count = 0;
                        } else {
                            // Not a valid sync pulse, go back to searching
                            rx->state = STATE_SEARCHING_FOR_SYNC;
                        }
                    }
                }
                break;

            case STATE_IN_BACK_PORCH:
                if (rx->line_sample_count < rx->color_burst_len_samples) {
                    update_pll(i_val, q_val, rx);
                }
                rx->line_sample_count++;
                if (rx->line_sample_count >= rx->back_porch_len_samples) {
                    rx->state = STATE_IN_VIDEO_LINE;
                    rx->line_sample_count = 0;
                }
                break;

            case STATE_IN_VIDEO_LINE:
                if (rx->line_sample_count < (rx->samples_per_line - rx->sync_pulse_sample_count - rx->back_porch_len_samples)) {
                    if (rx->line_sample_count < rx->samples_per_line) {
                        rx->current_line_buffer[rx->line_sample_count] = current_level;
                    }
                    rx->line_sample_count++;
                } else {
                    if (rx->current_line < rx->mode->active_lines) {
                        memcpy(rx->frame_buffer[rx->current_line], rx->current_line_buffer, sizeof(float) * rx->line_sample_count);
                        rx->current_line++;
                    }

                    if (rx->current_line >= rx->mode->active_lines) {
                        if (verbose) printf("\n--- FRAME COMPLETE ---\n");

                        char filename[256];
                        static int frame_count = 0;
                        snprintf(filename, sizeof(filename), "frame_%03d.ppm", frame_count++);
                        save_frame_as_ppm(filename, rx, verbose);

                        rx->current_line = 0;
                    }
                    rx->state = STATE_SEARCHING_FOR_SYNC;
                }
                break;
        }
    }

    if (verbose) {
        printf("Processing %d samples for %s. State: %d, PLL Freq: %.2f Hz\r", length, rx->mode->name, rx->state, rx->pll.frequency);
        fflush(stdout);
    }
}

static void process_audio(int16_t* buffer, int length, rx_state_t* rx) {
    for (int i = 0; i < length; i++) {
        // Mix with audio subcarrier LO
        float angle = -2.0f * M_PI * rx->mode->audio_subcarrier_freq / rx->sample_rate * i;
        float lo_i = cosf(angle);
        float lo_q = sinf(angle);

        float mixed_i = (float)buffer[i*2] * lo_i - (float)buffer[i*2+1] * lo_q;
        float mixed_q = (float)buffer[i*2] * lo_q + (float)buffer[i*2+1] * lo_i;

        // FM demodulate
        float phase = atan2f(mixed_q, mixed_i);
        float delta_phase = phase - rx->audio.last_phase;
        rx->audio.last_phase = phase;

        // Unwrap phase
        if (delta_phase > M_PI) delta_phase -= 2.0f * M_PI;
        if (delta_phase < -M_PI) delta_phase += 2.0f * M_PI;

        // Decimate and write to file
        if (rx->audio.decimation_counter++ == rx->audio.decimation_ratio) {
            rx->audio.decimation_counter = 0;
            int16_t audio_sample = (int16_t)(delta_phase * 10000.0f); // Scale factor, might need tuning
            if (rx->audio.output_file) {
                fwrite(&audio_sample, sizeof(int16_t), 1, rx->audio.output_file);
            }
        }
    }
}

static void _sigint_callback_handler(int signum)
{
	(void)signum;
	_abort = 1;
}

static void print_usage(void)
{
	printf(
		"\n"
		"Usage: hacktv-rx [options]\n"
		"\n"
		"  -d, --device <args>      SoapySDR device arguments.\n"
		"  -f, --frequency <value>  Frequency in Hz.\n"
		"  -s, --samplerate <value> Sample rate in Hz. Default: 16MHz\n"
		"  -g, --gain <value>       Set the RX gain. Default: 0dB\n"
		"  -m, --mode <name>        Set the television mode (ntsc, pal). Default: ntsc\n"
		"  -v, --verbose            Enable verbose output.\n"
		"\n"
	);
}

int main(int argc, char *argv[])
{
	int c;
	char *device_args = NULL;
	long long frequency = 0;
	double sample_rate = 16e6;
	double gain = 0;
	char *mode = "ntsc";
	int verbose = 0;
	SoapySDRDevice *sdr = NULL;
	SoapySDRStream *rx_stream = NULL;

	while ((c = getopt(argc, argv, "d:f:s:g:m:v")) != -1) {
		switch (c) {
			case 'd':
				device_args = optarg;
				break;
			case 'f':
				frequency = atoll(optarg);
				break;
			case 's':
				sample_rate = atof(optarg);
				break;
			case 'g':
				gain = atof(optarg);
				break;
			case 'm':
				mode = optarg;
				break;
			case 'v':
				verbose = 1;
				break;
			default:
				print_usage();
				return -1;
		}
	}

	if (!device_args || !frequency) {
		print_usage();
		return -1;
	}

	if (verbose) {
		printf("Starting receiver...\n");
		printf("Device: %s\n", device_args);
		printf("Frequency: %lld Hz\n", frequency);
		printf("Sample Rate: %f Hz\n", sample_rate);
		printf("Gain: %f dB\n", gain);
		printf("Mode: %s\n", mode);
	}

	const video_mode_t *selected_mode = NULL;
	for (int i = 0; video_modes[i].name != NULL; i++) {
		if (strcmp(mode, video_modes[i].name) == 0) {
			selected_mode = &video_modes[i];
			break;
		}
	}

	if (!selected_mode) {
		fprintf(stderr, "Invalid mode specified: %s\n", mode);
		return -1;
	}

	rx_state_t rx_state = {
		.mode = selected_mode,
		.sample_rate = sample_rate,
		.state = STATE_SEARCHING_FOR_SYNC,
		.samples_per_line = (int)(sample_rate / selected_mode->line_rate),
		.h_sync_len_samples = (int)((selected_mode->h_sync_porch / 1e6) * sample_rate),
        .v_sync_pulse_len_samples = (int)((selected_mode->v_sync_pulse_duration / 1e6) * sample_rate),
		.min_level = 1e6,
		.max_level = -1e6,
		.level_avg_count = 0,
        .current_line = 0,
        .frame_buffer = NULL,
        .current_line_buffer = NULL,
        .back_porch_len_samples = (int)((selected_mode->h_back_porch / 1e6) * sample_rate),
        .color_burst_len_samples = (int)((selected_mode->color_burst_duration / 1e6) * sample_rate),
        .pll = {
            .frequency = selected_mode->color_subcarrier_freq,
            .phase = 0.0f,
            .error_sum = 0.0f
        },
        .audio = {
            .last_phase = 0.0f,
            .decimation_ratio = (int)(sample_rate / 48000),
            .decimation_counter = 0,
            .output_file = NULL
        },
        .end_of_sync_counter = 0
	};

    rx_state.audio.output_file = fopen("audio_out.raw", "wb");
    if (!rx_state.audio.output_file) {
        perror("Failed to open audio output file");
        // We can continue without the audio file, but we should notify the user.
    }

	if (verbose) {
		printf("Samples per line: %d\n", rx_state.samples_per_line);
		printf("H-sync samples: %d\n", rx_state.h_sync_len_samples);
        printf("V-sync samples: %d\n", rx_state.v_sync_pulse_len_samples);
        printf("Back porch samples: %d\n", rx_state.back_porch_len_samples);
        printf("Color burst samples: %d\n", rx_state.color_burst_len_samples);
	}

    // Allocate frame buffer
    rx_state.frame_buffer = malloc(sizeof(float*) * selected_mode->active_lines);
    if (!rx_state.frame_buffer) {
        fprintf(stderr, "Failed to allocate frame buffer\n");
        return -1;
    }
    for (int i = 0; i < selected_mode->active_lines; i++) {
        rx_state.frame_buffer[i] = NULL; // Initialize to NULL
    }

    for (int i = 0; i < selected_mode->active_lines; i++) {
        rx_state.frame_buffer[i] = malloc(sizeof(float) * rx_state.samples_per_line);
        if (!rx_state.frame_buffer[i]) {
            fprintf(stderr, "Failed to allocate line buffer\n");
            goto cleanup;
        }
    }
    rx_state.current_line_buffer = malloc(sizeof(float) * rx_state.samples_per_line);
    if (!rx_state.current_line_buffer) {
        fprintf(stderr, "Failed to allocate current line buffer\n");
        goto cleanup;
    }

	signal(SIGINT, _sigint_callback_handler);

	SoapySDRKwargs *results = SoapySDRDevice_enumerate(NULL, NULL);
	if (!results) {
		fprintf(stderr, "No SoapySDR devices found.\n");
		goto cleanup;
	}
	SoapySDRKwargsList_clear(results, 0);

	sdr = SoapySDRDevice_makeStrArgs(device_args);
	if (!sdr) {
		fprintf(stderr, "SoapySDRDevice_make failed: %s\n", SoapySDRDevice_lastError());
		goto cleanup;
	}

	if (SoapySDRDevice_setSampleRate(sdr, SOAPY_SDR_RX, 0, sample_rate) != 0) {
		fprintf(stderr, "SoapySDRDevice_setSampleRate failed: %s\n", SoapySDRDevice_lastError());
		goto cleanup;
	}

	if (SoapySDRDevice_setFrequency(sdr, SOAPY_SDR_RX, 0, frequency, NULL) != 0) {
		fprintf(stderr, "SoapySDRDevice_setFrequency failed: %s\n", SoapySDRDevice_lastError());
		goto cleanup;
	}

	if (SoapySDRDevice_setGain(sdr, SOAPY_SDR_RX, 0, gain) != 0) {
		fprintf(stderr, "SoapySDRDevice_setGain failed: %s\n", SoapySDRDevice_lastError());
		goto cleanup;
	}

#if defined(SOAPY_SDR_API_VERSION) && (SOAPY_SDR_API_VERSION >= 0x00080000)
	rx_stream = SoapySDRDevice_setupStream(sdr, SOAPY_SDR_RX, SOAPY_SDR_CS16, NULL, 0, NULL);
	if (rx_stream == NULL)
#else
	if (SoapySDRDevice_setupStream(sdr, &rx_stream, SOAPY_SDR_RX, SOAPY_SDR_CS16, NULL, 0, NULL) != 0)
#endif
	{
		fprintf(stderr, "SoapySDRDevice_setupStream failed: %s\n", SoapySDRDevice_lastError());
		goto cleanup;
	}

	SoapySDRDevice_activateStream(sdr, rx_stream, 0, 0, 0);

	printf("Receiver running. Press Ctrl+C to exit.\n");

	int16_t buffer[RX_BUFFER_SIZE * 2]; // I and Q
	void *buffs[] = { buffer };

	while (!_abort) {
		int flags = 0;
		long long time_ns = 0;
		int ret = SoapySDRDevice_readStream(sdr, rx_stream, buffs, RX_BUFFER_SIZE, &flags, &time_ns, 100000);
		if (ret < 0) {
			fprintf(stderr, "Error reading stream: %s\n", SoapySDR_errToStr(ret));
			break;
		}
		process_samples(buffer, ret, verbose, &rx_state);
		process_audio(buffer, ret, &rx_state);
	}

	printf("\nShutting down.\n");

	SoapySDRDevice_deactivateStream(sdr, rx_stream, 0, 0);
	SoapySDRDevice_closeStream(sdr, rx_stream);

cleanup:
	if (sdr) {
		SoapySDRDevice_unmake(sdr);
	}

    if (rx_state.frame_buffer) {
        for (int i = 0; i < rx_state.mode->active_lines; i++) {
            if (rx_state.frame_buffer[i]) {
                free(rx_state.frame_buffer[i]);
            }
        }
        free(rx_state.frame_buffer);
    }
    if (rx_state.current_line_buffer) {
        free(rx_state.current_line_buffer);
    }
    if (rx_state.audio.output_file) {
        fclose(rx_state.audio.output_file);
    }

	return 0;
}