#!/usr/bin/env python3
"""
Generate a synthetic PAL test signal in IQ format for testing hackrx receiver.
This creates a simplified PAL-like signal with sync pulses and test pattern.
"""

import math
import struct
import sys

def generate_pal_test_signal(output_file, duration_seconds=1.0, sample_rate=16000000):
    """
    Generate a synthetic PAL test signal.

    PAL Specifications:
    - 625 lines, 25 fps
    - Line duration: 64 µs
    - Horizontal sync: 4.7 µs
    - Video bandwidth: ~5.5 MHz
    """

    # PAL parameters
    lines_per_frame = 625
    frames_per_second = 25
    line_duration = 64e-6  # 64 microseconds
    h_sync_duration = 4.7e-6  # 4.7 microseconds

    # Calculate samples
    samples_per_line = int(sample_rate * line_duration)
    samples_per_h_sync = int(sample_rate * h_sync_duration)
    total_frames = int(duration_seconds * frames_per_second)

    print(f"Generating PAL test signal:")
    print(f"  Sample rate: {sample_rate/1e6:.1f} MHz")
    print(f"  Duration: {duration_seconds} seconds")
    print(f"  Frames: {total_frames}")
    print(f"  Samples per line: {samples_per_line}")
    print(f"  Total samples: {total_frames * lines_per_frame * samples_per_line}")
    print()

    # Signal levels (16-bit signed)
    sync_level = -32000
    blanking_level = -10000
    black_level = 0
    white_level = 28000

    # Open output file
    with open(output_file, 'wb') as f:
        sample_count = 0

        for frame in range(total_frames):
            for line_num in range(lines_per_frame):
                # Determine if this is a visible line or vertical blanking
                is_visible = (line_num >= 23 and line_num < 310) or (line_num >= 336 and line_num < 623)

                for sample in range(samples_per_line):
                    # Generate baseband video signal
                    if sample < samples_per_h_sync:
                        # Horizontal sync pulse
                        video = sync_level
                    elif sample < samples_per_h_sync + int(samples_per_line * 0.1):
                        # Back porch / blanking
                        video = blanking_level
                    elif is_visible:
                        # Active video - simple test pattern
                        # Create vertical bars
                        x_position = (sample - samples_per_h_sync) / (samples_per_line - samples_per_h_sync)

                        # 8 vertical bars
                        bar_number = int(x_position * 8)
                        if bar_number % 2 == 0:
                            video = white_level
                        else:
                            video = black_level

                        # Add some horizontal variation
                        if line_num % 50 < 25:
                            video = int(video * 0.8)
                    else:
                        # Blanking lines
                        video = blanking_level

                    # FM modulate the video signal onto a carrier
                    # Use simple FM: phase = integral of (carrier_freq + deviation * video)
                    # For this test, we'll use a simplified approach

                    # Carrier frequency (e.g., IF at 6 MHz)
                    carrier_freq = 0.1e6  # Low carrier for simplicity
                    deviation = 0.05e6

                    # Normalized video signal (-1 to 1)
                    video_norm = video / 32768.0

                    # FM modulation
                    t = sample_count / sample_rate
                    phase = 2.0 * math.pi * carrier_freq * t + 2.0 * math.pi * deviation * video_norm * t

                    # Generate I/Q samples
                    i_sample = int(20000 * math.cos(phase))
                    q_sample = int(20000 * math.sin(phase))

                    # Clamp to int16 range
                    i_sample = max(-32768, min(32767, i_sample))
                    q_sample = max(-32768, min(32767, q_sample))

                    # Write as int16 little-endian
                    f.write(struct.pack('<h', i_sample))
                    f.write(struct.pack('<h', q_sample))

                    sample_count += 1

            # Progress indicator
            if (frame + 1) % 5 == 0:
                print(f"  Generated frame {frame + 1}/{total_frames}")

    print(f"\nGenerated {sample_count} IQ samples")
    print(f"Output file: {output_file}")
    print(f"File size: {sample_count * 4} bytes ({sample_count * 4 / 1024 / 1024:.2f} MB)")

if __name__ == "__main__":
    output_file = sys.argv[1] if len(sys.argv) > 1 else "test_pal.iq"
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    sample_rate = int(sys.argv[3]) if len(sys.argv) > 3 else 16000000

    generate_pal_test_signal(output_file, duration, sample_rate)
