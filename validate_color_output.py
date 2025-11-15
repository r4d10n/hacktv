#!/usr/bin/env python3
"""
Validate color output from receiver
Analyzes RGB output to check if color bars are decoded correctly
"""

import struct
import sys

# Expected PAL color bars in RGB (approximate after YUV->RGB conversion)
# Order: White, Yellow, Cyan, Green, Magenta, Red, Blue, Black
EXPECTED_COLORS = [
    ("White",    (200, 255), (200, 255), (200, 255)),  # RGB all high
    ("Yellow",   (200, 255), (200, 255), (0, 100)),     # R+G, low B
    ("Cyan",     (0, 100),   (200, 255), (200, 255)),  # G+B, low R
    ("Green",    (0, 150),   (150, 255), (0, 150)),    # G high, R+B low
    ("Magenta",  (200, 255), (0, 100),   (200, 255)),  # R+B, low G
    ("Red",      (200, 255), (0, 100),   (0, 100)),    # R high, G+B low
    ("Blue",     (0, 100),   (0, 100),   (200, 255)),  # B high, R+G low
    ("Black",    (0, 100),   (0, 100),   (0, 100)),    # RGB all low
]

def read_rgb_frame(filename, width, height):
    """Read one frame of RGB32 data"""
    frame_size = width * height * 4  # 4 bytes per pixel (RGBA)

    with open(filename, 'rb') as f:
        data = f.read(frame_size)

    if len(data) < frame_size:
        print(f"Warning: File smaller than expected ({len(data)} < {frame_size})")
        return None

    # Parse RGB32 data
    pixels = []
    for y in range(height):
        row = []
        for x in range(width):
            offset = (y * width + x) * 4
            # RGB32 is BGRA order (little endian)
            b = data[offset]
            g = data[offset + 1]
            r = data[offset + 2]
            a = data[offset + 3]
            row.append((r, g, b))
        pixels.append(row)

    return pixels

def analyze_color_bars(pixels, width, height):
    """Analyze if color bars are present and correctly decoded"""

    print("="*70)
    print("COLOR BAR ANALYSIS")
    print("="*70)
    print()

    # Sample middle line (should be in active video area)
    sample_line = height // 2
    line_data = pixels[sample_line]

    # Divide into 8 bars
    bar_width = width // 8
    detected_bars = []

    print(f"Sampling line {sample_line} (middle of frame)")
    print(f"Bar width: {bar_width} pixels")
    print()

    for bar_idx in range(8):
        # Sample center of each bar
        start_x = bar_idx * bar_width
        sample_x = start_x + bar_width // 2

        if sample_x >= width:
            sample_x = width - 1

        # Get average RGB of a few pixels in the center of the bar
        samples = []
        for x in range(max(0, sample_x - 5), min(width, sample_x + 5)):
            samples.append(line_data[x])

        avg_r = sum(p[0] for p in samples) / len(samples)
        avg_g = sum(p[1] for p in samples) / len(samples)
        avg_b = sum(p[2] for p in samples) / len(samples)

        detected_bars.append((avg_r, avg_g, avg_b))

        print(f"Bar {bar_idx}: RGB({avg_r:3.0f}, {avg_g:3.0f}, {avg_b:3.0f})", end="")

        # Try to match with expected color
        if bar_idx < len(EXPECTED_COLORS):
            name, (r_min, r_max), (g_min, g_max), (b_min, b_max) = EXPECTED_COLORS[bar_idx]

            r_match = r_min <= avg_r <= r_max
            g_match = g_min <= avg_g <= g_max
            b_match = b_min <= avg_b <= b_max

            if r_match and g_match and b_match:
                print(f" -> {name} ✓")
            else:
                print(f" -> Expected {name} (R:{r_min}-{r_max}, G:{g_min}-{g_max}, B:{b_min}-{b_max}) ✗")
        else:
            print()

    print()

    # Check for chroma presence
    print("CHROMA DETECTION")
    print("-"*70)

    # Calculate color variance
    r_vals = [bar[0] for bar in detected_bars]
    g_vals = [bar[1] for bar in detected_bars]
    b_vals = [bar[2] for bar in detected_bars]

    r_range = max(r_vals) - min(r_vals)
    g_range = max(g_vals) - min(g_vals)
    b_range = max(b_vals) - min(b_vals)

    print(f"R channel range: {r_range:.1f}")
    print(f"G channel range: {g_range:.1f}")
    print(f"B channel range: {b_range:.1f}")
    print()

    # If all channels have similar high range, we have color
    # If all channels have low range, it's monochrome
    avg_range = (r_range + g_range + b_range) / 3

    if avg_range > 150:
        print("✓ Strong color variation detected - chroma decoding likely working")
        has_chroma = True
    elif avg_range > 80:
        print("⚠ Moderate color variation - partial chroma decoding")
        has_chroma = True
    else:
        print("✗ Low color variation - may be monochrome or chroma not decoded")
        has_chroma = False

    print()

    # Sample multiple lines to check consistency
    print("CONSISTENCY CHECK")
    print("-"*70)

    test_lines = [height // 4, height // 2, 3 * height // 4]
    line_variances = []

    for line_num in test_lines:
        if line_num >= height:
            continue

        line = pixels[line_num]
        bar_width = width // 8
        bar_colors = []

        for bar_idx in range(8):
            sample_x = bar_idx * bar_width + bar_width // 2
            if sample_x >= width:
                sample_x = width - 1

            r, g, b = line[sample_x]
            bar_colors.append((r + g + b) / 3)  # Average brightness

        variance = max(bar_colors) - min(bar_colors)
        line_variances.append(variance)
        print(f"Line {line_num:3d}: brightness variance = {variance:.1f}")

    avg_variance = sum(line_variances) / len(line_variances) if line_variances else 0
    print(f"Average variance: {avg_variance:.1f}")

    if avg_variance > 100:
        print("✓ Consistent pattern across lines")
    else:
        print("⚠ Low variance - pattern may not be clear")

    print()

    return has_chroma, detected_bars

def main():
    if len(sys.argv) < 3:
        print("Usage: validate_color_output.py <rgb_file> <width> <height>")
        sys.exit(1)

    filename = sys.argv[1]
    width = int(sys.argv[2])
    height = int(sys.argv[3])

    print(f"Reading RGB output: {filename}")
    print(f"Dimensions: {width}x{height}")
    print()

    pixels = read_rgb_frame(filename, width, height)
    if pixels is None:
        print("Error reading frame")
        sys.exit(1)

    has_chroma, bars = analyze_color_bars(pixels, width, height)

    print("="*70)
    print("SUMMARY")
    print("="*70)
    print()

    if has_chroma:
        print("✓ Color decoding appears to be working")
        print("  - Chroma subcarrier is being demodulated")
        print("  - YUV to RGB conversion is functioning")
    else:
        print("✗ Color decoding may not be working correctly")
        print("  - Signal may be monochrome")
        print("  - Or chroma PLL not locked")

    print()

if __name__ == '__main__':
    main()
