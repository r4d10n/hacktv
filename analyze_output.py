#!/usr/bin/env python3
"""
Analyze the receiver output to verify it matches the expected test pattern.
"""

import struct
import sys

def analyze_rgb_output(filename, width, height):
    """
    Analyze raw RGB32 output file.
    """
    print(f"Analyzing RGB output: {filename}")
    print(f"  Expected dimensions: {width}x{height}")
    print()

    # Read the file
    with open(filename, 'rb') as f:
        data = f.read()

    expected_size = width * height * 4  # 4 bytes per pixel (RGBA)
    actual_size = len(data)

    print(f"File size:")
    print(f"  Expected: {expected_size} bytes ({expected_size / 1024 / 1024:.2f} MB)")
    print(f"  Actual: {actual_size} bytes ({actual_size / 1024 / 1024:.2f} MB)")
    print()

    if actual_size < expected_size:
        print(f"Warning: File is smaller than expected for one frame")
        print(f"  Actual frames in file: {actual_size / (width * 4):.1f} lines")
        height = min(height, actual_size // (width * 4))
    elif actual_size > expected_size:
        num_frames = actual_size // expected_size
        print(f"File contains {num_frames} frames")
        print()

    # Sample some pixels
    print("Sampling pixels from first frame:")
    print()

    # Check first line
    print("First line (should be mostly sync/blanking):")
    for i in range(min(10, width)):
        offset = i * 4
        if offset + 4 <= len(data):
            r, g, b, a = struct.unpack('BBBB', data[offset:offset+4])
            print(f"  Pixel {i}: R={r:3d} G={g:3d} B={b:3d} A={a:3d}")

    print()

    # Check middle line
    if height > 100:
        middle_line = height // 2
        print(f"Middle line {middle_line} (should show pattern):")
        line_offset = middle_line * width * 4
        for i in range(0, min(width, 720), width // 10):
            offset = line_offset + i * 4
            if offset + 4 <= len(data):
                r, g, b, a = struct.unpack('BBBB', data[offset:offset+4])
                print(f"  Pixel {i}: R={r:3d} G={g:3d} B={b:3d} A={a:3d}")

    print()

    # Calculate statistics
    print("Statistics:")

    # Sample every 100th pixel
    r_values = []
    g_values = []
    b_values = []

    for i in range(0, len(data) - 4, 400):  # Sample every 100th pixel
        r, g, b, a = struct.unpack('BBBB', data[i:i+4])
        r_values.append(r)
        g_values.append(g)
        b_values.append(b)

    if r_values:
        print(f"  Red channel:   min={min(r_values):3d}, max={max(r_values):3d}, avg={sum(r_values)/len(r_values):6.2f}")
        print(f"  Green channel: min={min(g_values):3d}, max={max(g_values):3d}, avg={sum(g_values)/len(g_values):6.2f}")
        print(f"  Blue channel:  min={min(b_values):3d}, max={max(b_values):3d}, avg={sum(b_values)/len(b_values):6.2f}")

        # Check if we have variation (indicates some pattern was decoded)
        r_range = max(r_values) - min(r_values)
        g_range = max(g_values) - min(g_values)
        b_range = max(b_values) - min(b_values)

        print()
        print("Output validation:")
        if r_range > 50 or g_range > 50 or b_range > 50:
            print("  ✓ Output shows variation (pattern detected)")
        else:
            print("  ✗ Output is mostly uniform (possible issue)")

        # Check if output is not all zeros or all max
        avg_brightness = (sum(r_values) + sum(g_values) + sum(b_values)) / (len(r_values) * 3)
        if 10 < avg_brightness < 245:
            print("  ✓ Average brightness in reasonable range")
        else:
            print(f"  ⚠ Average brightness unusual: {avg_brightness:.1f}")

    print()

def create_simple_ppm(input_file, output_file, width, height, max_lines=100):
    """
    Convert first frame to PPM format for easy viewing.
    """
    print(f"Creating PPM image: {output_file}")

    with open(input_file, 'rb') as f:
        data = f.read()

    # Limit height for easier viewing
    height = min(height, max_lines)
    pixels_to_read = width * height

    with open(output_file, 'w') as f:
        # PPM header
        f.write(f"P3\n")
        f.write(f"{width} {height}\n")
        f.write(f"255\n")

        # Write pixels
        for i in range(pixels_to_read):
            offset = i * 4
            if offset + 4 <= len(data):
                r, g, b, a = struct.unpack('BBBB', data[offset:offset+4])
                f.write(f"{r} {g} {b} ")
                if (i + 1) % width == 0:
                    f.write("\n")

    print(f"  Created {width}x{height} PPM image")
    print(f"  You can view it with: display {output_file}")
    print()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: analyze_output.py <rgb_file> <width> <height>")
        sys.exit(1)

    filename = sys.argv[1]
    width = int(sys.argv[2])
    height = int(sys.argv[3])

    analyze_rgb_output(filename, width, height)

    # Create a PPM for visual inspection
    ppm_file = filename.replace('.rgb', '.ppm')
    create_simple_ppm(filename, ppm_file, width, height, max_lines=100)
