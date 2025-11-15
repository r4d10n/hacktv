#!/usr/bin/env python3
"""
Generate PAL color test signal with proper chroma subcarrier
This creates a baseband or modulated IQ file for testing the receiver
"""

import numpy as np
import struct
import sys

# PAL parameters
SAMPLE_RATE = 16000000  # 16 MHz
LINE_RATE = 15625  # Hz
LINE_LENGTH = SAMPLE_RATE // LINE_RATE  # 1024 samples per line
LINES_PER_FRAME = 625
SUBCARRIER_FREQ = 4433618.75  # PAL color subcarrier

# Timing (in samples)
SYNC_SAMPLES = 75  # Sync pulse ~4.7μs
BACK_PORCH = 82    # Back porch ~5.8μs
BURST_START = 12   # Color burst starts 12 samples into back porch
BURST_LENGTH = 36  # Color burst ~2.25μs (10 cycles)
ACTIVE_START = SYNC_SAMPLES + BACK_PORCH  # 157
ACTIVE_WIDTH = 720  # Active video samples

# Video levels (16-bit signed)
SYNC_LEVEL = -32000
BLANKING_LEVEL = -16000
BLACK_LEVEL = 0
WHITE_LEVEL = 28000

# PAL color bars in YUV
# Standard EBU color bars: White, Yellow, Cyan, Green, Magenta, Red, Blue, Black
COLOR_BARS = [
    # Y, U, V
    (WHITE_LEVEL, 0, 0),           # White
    (20000, -10000, 10000),         # Yellow
    (15000, 10000, -10000),         # Cyan
    (12000, -8000, -8000),          # Green
    (10000, 8000, 8000),            # Magenta
    (8000, -12000, 12000),          # Red
    (5000, 15000, -15000),          # Blue
    (BLACK_LEVEL, 0, 0),            # Black
]

def generate_pal_line(line_num, pattern='colorbars'):
    """Generate a single PAL line with color information"""
    line = np.zeros(LINE_LENGTH, dtype=np.int16)

    # Sync pulse
    line[0:SYNC_SAMPLES] = SYNC_LEVEL

    # Back porch (blanking)
    line[SYNC_SAMPLES:ACTIVE_START] = BLANKING_LEVEL

    # Color burst (10 cycles of subcarrier - continuous phase with chroma carrier)
    if pattern != 'mono':
        # Calculate burst position in line (continuous carrier phase)
        burst_start_sample = SYNC_SAMPLES + BURST_START
        t_burst = (burst_start_sample + np.arange(BURST_LENGTH)) / SAMPLE_RATE

        # Simplified: Use 0° burst (on U-axis) for testing
        # This should align directly with the cos/sin references in the decoder
        burst_phase_offset = 0.0  # 0° burst for simple alignment
        burst_signal = np.sin(2 * np.pi * SUBCARRIER_FREQ * t_burst + burst_phase_offset)
        burst_amplitude = 8000  # Burst amplitude
        line[burst_start_sample:burst_start_sample + BURST_LENGTH] = \
            BLANKING_LEVEL + (burst_signal * burst_amplitude).astype(np.int16)

    # Active video
    if pattern == 'colorbars':
        # Generate color bars with chroma
        bar_width = ACTIVE_WIDTH // 8

        for i, (y, u, v) in enumerate(COLOR_BARS):
            start = ACTIVE_START + i * bar_width
            end = start + bar_width if i < 7 else ACTIVE_START + ACTIVE_WIDTH
            width = end - start

            # Luminance (Y)
            luma = np.full(width, y, dtype=np.int16)

            # Chrominance modulated onto subcarrier (continuous phase, NO offset)
            # The burst establishes the reference, but chroma is on unshifted carrier
            # PAL: U modulated on cos, V on sin with line alternation
            t = (start + np.arange(width)) / SAMPLE_RATE
            carrier_phase = 2 * np.pi * SUBCARRIER_FREQ * t  # No phase offset
            carrier_cos = np.cos(carrier_phase)
            carrier_sin = np.sin(carrier_phase)

            # PAL V-switch: V phase alternates every line
            v_phase = 1 if (line_num % 2) == 0 else -1

            chroma = (u * carrier_cos + v * v_phase * carrier_sin) * 0.3  # 30% chroma gain

            line[start:end] = np.clip(luma + chroma, -32768, 32767).astype(np.int16)

    elif pattern == 'whiteflag':
        # Alternating white/black bars
        bar_width = ACTIVE_WIDTH // 8
        for i in range(8):
            start = ACTIVE_START + i * bar_width
            end = start + bar_width if i < 7 else ACTIVE_START + ACTIVE_WIDTH
            level = WHITE_LEVEL if (i % 2) == 0 else BLACK_LEVEL
            line[start:end] = level

    elif pattern == 'mono':
        # Simple grayscale ramp
        line[ACTIVE_START:ACTIVE_START + ACTIVE_WIDTH] = \
            np.linspace(BLACK_LEVEL, WHITE_LEVEL, ACTIVE_WIDTH, dtype=np.int16)

    return line

def generate_pal_test_signal(num_frames=5, pattern='colorbars', modulation='baseband'):
    """
    Generate PAL test signal

    Args:
        num_frames: Number of frames to generate
        pattern: 'colorbars', 'whiteflag', or 'mono'
        modulation: 'baseband' (I=signal, Q=0) or 'fm' (frequency modulated)

    Returns:
        Interleaved I/Q samples as int16 array
    """
    total_samples = num_frames * LINES_PER_FRAME * LINE_LENGTH
    iq_samples = np.zeros(total_samples * 2, dtype=np.int16)  # Interleaved I/Q

    print(f"Generating {num_frames} frames of PAL {pattern} pattern...")
    print(f"Modulation: {modulation}")
    print(f"Sample rate: {SAMPLE_RATE} Hz")
    print(f"Subcarrier: {SUBCARRIER_FREQ:.2f} Hz")
    print(f"Total samples: {total_samples} ({total_samples * 2 * 2 / 1024 / 1024:.2f} MB)")

    sample_idx = 0
    for frame in range(num_frames):
        for line in range(LINES_PER_FRAME):
            # Generate baseband signal
            line_data = generate_pal_line(line, pattern)

            if modulation == 'baseband':
                # Baseband: I=signal, Q=0
                for i in range(LINE_LENGTH):
                    iq_samples[sample_idx + i * 2] = line_data[i]      # I channel
                    iq_samples[sample_idx + i * 2 + 1] = 0             # Q channel
                sample_idx += LINE_LENGTH * 2

            elif modulation == 'fm':
                # FM modulation (simplified - would need proper FM modulator)
                # For now, just use baseband as FM would require carrier
                print("Warning: FM modulation not fully implemented, using baseband")
                for i in range(LINE_LENGTH):
                    iq_samples[sample_idx + i * 2] = line_data[i]      # I channel
                    iq_samples[sample_idx + i * 2 + 1] = 0             # Q channel
                sample_idx += LINE_LENGTH * 2

        if (frame + 1) % 10 == 0:
            print(f"  Generated frame {frame + 1}/{num_frames}")

    return iq_samples

def main():
    if len(sys.argv) < 2:
        print("Usage: generate_color_test.py <output.iq> [pattern] [frames]")
        print("  Patterns: colorbars (default), whiteflag, mono")
        print("  Frames: number of frames (default: 5)")
        sys.exit(1)

    output_file = sys.argv[1]
    pattern = sys.argv[2] if len(sys.argv) > 2 else 'colorbars'
    num_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    # Generate test signal
    iq_data = generate_pal_test_signal(num_frames=num_frames, pattern=pattern, modulation='baseband')

    # Write to file (int16 interleaved I/Q)
    print(f"\nWriting to {output_file}...")
    with open(output_file, 'wb') as f:
        f.write(iq_data.tobytes())

    file_size_mb = len(iq_data) * 2 / 1024 / 1024
    print(f"Done! File size: {file_size_mb:.2f} MB")
    print(f"\nTo test with hackrx:")
    print(f"  ./src/hackrx -i {output_file} -o output.rgb -m pal -d am -s {SAMPLE_RATE}")

if __name__ == '__main__':
    main()
