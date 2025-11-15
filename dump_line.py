#!/usr/bin/env python3
"""
Dump a full line from RGB output to see the pattern.
"""

import struct
import sys

def dump_line(rgb_file, width, height, line_num):
    """
    Dump all pixels from a specific line.
    """
    with open(rgb_file, 'rb') as f:
        # Skip to the line
        f.seek(line_num * width * 4)

        pixels = []
        for x in range(width):
            data = f.read(4)
            if len(data) < 4:
                break
            r, g, b, a = struct.unpack('BBBB', data)
            pixels.append(r)

    print(f"Line {line_num} - {len(pixels)} pixels")
    print()

    # Show every 10th pixel
    print("Every 10th pixel:")
    for x in range(0, len(pixels), 10):
        print(f"  Pixel {x:3d}: {pixels[x]:3d}")

    print()

    # Show histogram
    print("Value histogram:")
    bins = {}
    for p in pixels:
        bin_val = (p // 10) * 10
        bins[bin_val] = bins.get(bin_val, 0) + 1

    for bin_val in sorted(bins.keys()):
        bar = '#' * (bins[bin_val] // 10)
        print(f"  {bin_val:3d}-{bin_val+9:3d}: {bins[bin_val]:4d} {bar}")

    # Detect transitions
    print()
    print("Brightness transitions:")
    last_val = pixels[0]
    for x in range(1, len(pixels)):
        if abs(pixels[x] - last_val) > 30:
            print(f"  Pixel {x:3d}: {last_val:3d} -> {pixels[x]:3d}")
            last_val = pixels[x]

if __name__ == "__main__":
    rgb_file = sys.argv[1]
    width = int(sys.argv[2])
    height = int(sys.argv[3])
    line_num = int(sys.argv[4]) if len(sys.argv) > 4 else height // 2

    dump_line(rgb_file, width, height, line_num)
