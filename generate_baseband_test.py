#!/usr/bin/env python3
"""
Generate a simple baseband PAL test signal (no carrier modulation).
This makes it easier to test the receiver's sync and video decoding.
"""

import math
import struct
import sys

def generate_baseband_pal(output_file, duration_seconds=0.2, sample_rate=16000000):
    """
    Generate a baseband PAL test signal with sync pulses and test pattern.
    Output format: int16 complex (I/Q), but baseband (Q=0).
    """

    # PAL parameters
    lines_per_frame = 625
    frames_per_second = 25
    line_duration = 64e-6
    h_sync_duration = 4.7e-6

    samples_per_line = int(sample_rate * line_duration)
    samples_per_h_sync = int(sample_rate * h_sync_duration)
    total_frames = int(duration_seconds * frames_per_second)

    print(f"Generating baseband PAL test signal:")
    print(f"  Sample rate: {sample_rate/1e6:.1f} MHz")
    print(f"  Duration: {duration_seconds} seconds")
    print(f"  Frames: {total_frames}")
    print(f"  Samples per line: {samples_per_line}")
    print()

    # Signal levels (16-bit signed)
    sync_level = -32000
    blanking_level = -11000
    black_level = 0
    white_level = 32000

    with open(output_file, 'wb') as f:
        for frame in range(total_frames):
            for line_num in range(lines_per_frame):
                # Visible lines
                is_visible = (line_num >= 23 and line_num < 310) or (line_num >= 336 and line_num < 623)

                for sample in range(samples_per_line):
                    # Generate baseband video
                    if sample < samples_per_h_sync:
                        # H-sync pulse
                        video = sync_level
                    elif sample < samples_per_h_sync + int(samples_per_line * 0.08):
                        # Back porch
                        video = blanking_level
                    elif is_visible:
                        # Active video - create clear test pattern
                        x_pos = (sample - samples_per_h_sync - int(samples_per_line * 0.08)) / \
                                (samples_per_line - samples_per_h_sync - int(samples_per_line * 0.08))

                        # Create 8 vertical bars
                        bar = int(x_pos * 8)

                        # Alternate black and white
                        if bar % 2 == 0:
                            video = white_level
                        else:
                            video = black_level

                        # Add horizontal variation - lighter top half, darker bottom half
                        if line_num < 312:
                            video = int(video * 1.0)
                        else:
                            video = int(video * 0.7)
                    else:
                        # Blanking
                        video = blanking_level

                    # Output as I/Q samples (baseband, so Q=0)
                    i_sample = max(-32768, min(32767, video))
                    q_sample = 0

                    f.write(struct.pack('<hh', i_sample, q_sample))

            if (frame + 1) % 1 == 0:
                print(f"  Generated frame {frame + 1}/{total_frames}")

    total_samples = total_frames * lines_per_frame * samples_per_line
    print(f"\nGenerated {total_samples} samples")
    print(f"Output: {output_file}")
    print(f"Size: {total_samples * 4 / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    output_file = sys.argv[1] if len(sys.argv) > 1 else "test_baseband.iq"
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
    sample_rate = int(sys.argv[3]) if len(sys.argv) > 3 else 16000000

    generate_baseband_pal(output_file, duration, sample_rate)
