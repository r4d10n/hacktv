#ifndef HACKTV_RX_H
#define HACKTV_RX_H

#include <stdint.h>

// Define TV standards
typedef enum {
    STANDARD_NTSC,
    STANDARD_PAL
} tv_standard_t;

// Define video mode parameters
typedef struct {
    tv_standard_t standard;
    const char *name;
    double sample_rate;
    double line_rate;
    int total_lines;
    int active_lines;
    double h_sync_porch; // in microseconds
    double h_back_porch; // in microseconds
    double color_burst_duration; // in microseconds
    double h_active_video; // in microseconds
    double color_subcarrier_freq;
    double audio_subcarrier_freq;
    double v_sync_pulse_duration; // in microseconds
} video_mode_t;

typedef struct {
    float phase;
    float frequency;
    float error_sum;
} color_pll_t;

typedef struct {
    // FM demodulator state
    float last_phase;
    // Decimator state
    int decimation_ratio;
    int decimation_counter;
    // Output file
    FILE *output_file;
} audio_state_t;


// Define known video modes
static const video_mode_t video_modes[] = {
    {
        .standard = STANDARD_NTSC,
        .name = "ntsc",
        .sample_rate = 13.5e6, // Typical NTSC sample rate
        .line_rate = 15734.26, // NTSC line rate
        .total_lines = 525,
        .active_lines = 480,
        .h_sync_porch = 4.7,
        .h_back_porch = 4.7,
        .color_burst_duration = 2.5,
        .h_active_video = 52.66,
        .color_subcarrier_freq = 3579545.0,
        .audio_subcarrier_freq = 4500000.0,
        .v_sync_pulse_duration = 27.1
    },
    {
        .standard = STANDARD_PAL,
        .name = "pal",
        .sample_rate = 16.0e6,
        .line_rate = 15625, // PAL line rate
        .total_lines = 625,
        .active_lines = 576,
        .h_sync_porch = 4.7,
        .h_back_porch = 5.7,
        .color_burst_duration = 2.5,
        .h_active_video = 52.0,
        .color_subcarrier_freq = 4433618.75,
        .audio_subcarrier_freq = 5500000.0,
        .v_sync_pulse_duration = 27.3
    },
    { .standard = 0 } // End of list
};

#endif // HACKTV_RX_H