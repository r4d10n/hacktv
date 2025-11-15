#!/usr/bin/env python3
"""
Comprehensive receiver validation - compare input pattern to output.
"""

import struct
import sys

def validate_test_pattern(rgb_file, width, height):
    """
    Validate that the receiver properly decoded the 8-bar test pattern.
    """
    print("="*70)
    print("RECEIVER OUTPUT VALIDATION")
    print("="*70)
    print()

    # Read RGB output
    with open(rgb_file, 'rb') as f:
        data = f.read()

    bytes_per_frame = width * height * 4
    num_frames = len(data) // bytes_per_frame

    print(f"File: {rgb_file}")
    print(f"Dimensions: {width}x{height}")
    print(f"File size: {len(data)} bytes ({len(data)/1024/1024:.2f} MB)")
    print(f"Frames detected: {num_frames}")
    print()

    # Analyze first frame
    print("FIRST FRAME ANALYSIS")
    print("-" * 70)

    # Check sync/blanking lines (first 22 lines)
    print("\n1. Sync and Blanking Lines (lines 0-22):")
    sync_pixels = []
    for line_num in range(min(23, height)):
        offset = line_num * width * 4
        if offset + 4 <= len(data):
            r, g, b, a = struct.unpack('BBBB', data[offset:offset+4])
            sync_pixels.append(r)
            if line_num < 5:
                print(f"   Line {line_num:2d}: RGB({r:3d}, {g:3d}, {b:3d})")

    avg_sync = sum(sync_pixels) / len(sync_pixels) if sync_pixels else 0
    print(f"   Average level: {avg_sync:.1f} (expected: dark, near 0-50)")

    if avg_sync < 100:
        print("   ✓ Sync/blanking area is correctly dark")
    else:
        print("   ⚠ Sync/blanking area may be too bright")

    # Check active video lines
    print("\n2. Active Video Lines:")

    # Sample middle line (should have alternating pattern)
    mid_line = height // 2
    print(f"\n   Sampling line {mid_line} (should show 8-bar pattern):")

    line_offset = mid_line * width * 4
    samples_per_bar = width // 8

    bar_levels = []
    for bar in range(8):
        # Sample middle of each bar
        x = bar * samples_per_bar + samples_per_bar // 2
        offset = line_offset + x * 4

        if offset + 4 <= len(data):
            r, g, b, a = struct.unpack('BBBB', data[offset:offset+4])
            bar_levels.append(r)
            expected = "WHITE" if bar % 2 == 0 else "BLACK"
            status = "✓" if (bar % 2 == 0 and r > 200) or (bar % 2 == 1 and r < 50) else "⚠"
            print(f"   Bar {bar}: RGB({r:3d}, {g:3d}, {b:3d}) - Expected: {expected:5s} {status}")

    print("\n3. Pattern Validation:")

    # Check if bars alternate properly
    alternates_correctly = True
    for i in range(len(bar_levels) - 1):
        current_is_bright = bar_levels[i] > 150
        next_is_bright = bar_levels[i+1] > 150

        if current_is_bright == next_is_bright:
            alternates_correctly = False
            break

    if alternates_correctly and len(bar_levels) == 8:
        print("   ✓ 8-bar pattern correctly alternates between black and white")
    else:
        print("   ⚠ Pattern may not be alternating correctly")

    # Check contrast ratio
    max_level = max(bar_levels) if bar_levels else 0
    min_level = min(bar_levels) if bar_levels else 0
    contrast = max_level - min_level

    print(f"\n   Brightness range: {min_level} to {max_level}")
    print(f"   Contrast: {contrast}")

    if contrast > 150:
        print("   ✓ Good contrast (>150)")
    elif contrast > 80:
        print("   ⚠ Moderate contrast (80-150)")
    else:
        print("   ✗ Low contrast (<80)")

    # Overall statistics
    print("\n4. Overall Statistics:")

    all_pixels = []
    for i in range(0, min(len(data), bytes_per_frame), 400):  # Sample every 100th pixel
        if i + 4 <= len(data):
            r, g, b, a = struct.unpack('BBBB', data[i:i+4])
            all_pixels.append(r)

    if all_pixels:
        min_val = min(all_pixels)
        max_val = max(all_pixels)
        avg_val = sum(all_pixels) / len(all_pixels)

        print(f"   Pixel values: min={min_val}, max={max_val}, avg={avg_val:.1f}")
        print(f"   Dynamic range: {max_val - min_val}")

        # Check if output uses full range
        if max_val > 200 and min_val < 50:
            print("   ✓ Full dynamic range utilized")
        else:
            print("   ⚠ Dynamic range limited")

    # Final verdict
    print("\n" + "="*70)
    print("FINAL VERDICT")
    print("="*70)

    tests_passed = 0
    total_tests = 4

    if avg_sync < 100:
        tests_passed += 1
        print("✓ Sync detection: PASS")
    else:
        print("✗ Sync detection: FAIL")

    if alternates_correctly:
        tests_passed += 1
        print("✓ Pattern decoding: PASS")
    else:
        print("✗ Pattern decoding: FAIL")

    if contrast > 80:
        tests_passed += 1
        print("✓ Contrast: PASS")
    else:
        print("✗ Contrast: FAIL")

    if max_val > 200 and min_val < 50:
        tests_passed += 1
        print("✓ Dynamic range: PASS")
    else:
        print("✗ Dynamic range: FAIL")

    print()
    print(f"Score: {tests_passed}/{total_tests} tests passed")

    if tests_passed == total_tests:
        print("🎉 RECEIVER WORKING CORRECTLY! 🎉")
        return 0
    elif tests_passed >= total_tests - 1:
        print("✓ Receiver working well (minor issues)")
        return 0
    else:
        print("⚠ Receiver needs more work")
        return 1

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: validate_receiver.py <rgb_file> <width> <height>")
        sys.exit(1)

    rgb_file = sys.argv[1]
    width = int(sys.argv[2])
    height = int(sys.argv[3])

    sys.exit(validate_test_pattern(rgb_file, width, height))
