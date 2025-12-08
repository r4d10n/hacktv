#!/usr/bin/env python3
"""
Generate EBU 75% color bars test pattern for PAL color calibration.

Standard 75% EBU color bars (in order left to right):
- White (75%)
- Yellow
- Cyan
- Green
- Magenta
- Red
- Blue
- Black

This gives us 8 known reference colors to calibrate the decoder.
"""

import numpy as np
from PIL import Image
import os

# 75% EBU color bars - standard PAL test pattern
# Values are 75% of full (191 instead of 255)
COLOR_BARS_75 = {
    'white':   (191, 191, 191),
    'yellow':  (191, 191, 0),
    'cyan':    (0, 191, 191),
    'green':   (0, 191, 0),
    'magenta': (191, 0, 191),
    'red':     (191, 0, 0),
    'blue':    (0, 0, 191),
    'black':   (0, 0, 0),
}

# 100% color bars for comparison
COLOR_BARS_100 = {
    'white':   (255, 255, 255),
    'yellow':  (255, 255, 0),
    'cyan':    (0, 255, 255),
    'green':   (0, 255, 0),
    'magenta': (255, 0, 255),
    'red':     (255, 0, 0),
    'blue':    (0, 0, 255),
    'black':   (0, 0, 0),
}

# Additional test colors for better gamut coverage
EXTENDED_COLORS = {
    'orange':      (255, 128, 0),
    'pink':        (255, 192, 203),
    'brown':       (139, 69, 19),
    'sky_blue':    (135, 206, 235),
    'forest_green':(34, 139, 34),
    'purple':      (128, 0, 128),
    'gray_25':     (64, 64, 64),
    'gray_50':     (128, 128, 128),
    'gray_75':     (191, 191, 191),
    'skin_tone':   (255, 205, 148),
}


def create_color_bars(width=720, height=576, colors=COLOR_BARS_75):
    """Create standard color bars pattern."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    color_names = list(colors.keys())
    bar_width = width // len(color_names)

    for i, name in enumerate(color_names):
        x_start = i * bar_width
        x_end = (i + 1) * bar_width if i < len(color_names) - 1 else width
        img[:, x_start:x_end] = colors[name]

    return img, color_names


def create_extended_test_pattern(width=720, height=576):
    """Create extended test pattern with more colors."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    # Top half: standard 75% color bars
    bar_colors = list(COLOR_BARS_75.values())
    bar_width = width // 8
    for i, color in enumerate(bar_colors):
        x_start = i * bar_width
        x_end = (i + 1) * bar_width if i < 7 else width
        img[:height//2, x_start:x_end] = color

    # Bottom half: extended colors
    ext_colors = list(EXTENDED_COLORS.values())
    ext_width = width // len(ext_colors)
    for i, color in enumerate(ext_colors):
        x_start = i * ext_width
        x_end = (i + 1) * ext_width if i < len(ext_colors) - 1 else width
        img[height//2:, x_start:x_end] = color

    return img


def create_gradient_test(width=720, height=576):
    """Create gradient test pattern for checking smooth color transitions."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    section_height = height // 6

    # Red gradient
    for x in range(width):
        img[0:section_height, x] = (int(255 * x / width), 0, 0)

    # Green gradient
    for x in range(width):
        img[section_height:2*section_height, x] = (0, int(255 * x / width), 0)

    # Blue gradient
    for x in range(width):
        img[2*section_height:3*section_height, x] = (0, 0, int(255 * x / width))

    # Yellow gradient (R+G)
    for x in range(width):
        v = int(255 * x / width)
        img[3*section_height:4*section_height, x] = (v, v, 0)

    # Cyan gradient (G+B)
    for x in range(width):
        v = int(255 * x / width)
        img[4*section_height:5*section_height, x] = (0, v, v)

    # Gray gradient
    for x in range(width):
        v = int(255 * x / width)
        img[5*section_height:, x] = (v, v, v)

    return img


def main():
    output_dir = '/tmp/color_test_patterns'
    os.makedirs(output_dir, exist_ok=True)

    print("Generating color test patterns...")

    # 1. Standard 75% color bars
    bars_75, names = create_color_bars(colors=COLOR_BARS_75)
    Image.fromarray(bars_75).save(f'{output_dir}/colorbars_75.png')
    print(f"  Created colorbars_75.png")

    # 2. 100% color bars
    bars_100, _ = create_color_bars(colors=COLOR_BARS_100)
    Image.fromarray(bars_100).save(f'{output_dir}/colorbars_100.png')
    print(f"  Created colorbars_100.png")

    # 3. Extended test pattern
    extended = create_extended_test_pattern()
    Image.fromarray(extended).save(f'{output_dir}/extended_colors.png')
    print(f"  Created extended_colors.png")

    # 4. Gradient test
    gradient = create_gradient_test()
    Image.fromarray(gradient).save(f'{output_dir}/gradients.png')
    print(f"  Created gradients.png")

    # Save reference color values
    print("\n75% Color Bars Reference Values:")
    for name, rgb in COLOR_BARS_75.items():
        print(f"  {name:10s}: RGB({rgb[0]:3d}, {rgb[1]:3d}, {rgb[2]:3d})")

    print("\nExtended Colors Reference:")
    for name, rgb in EXTENDED_COLORS.items():
        print(f"  {name:15s}: RGB({rgb[0]:3d}, {rgb[1]:3d}, {rgb[2]:3d})")

    print(f"\nPatterns saved to {output_dir}/")
    print("\nNext step: Encode these through hacktv and decode with PAL-CRT")


if __name__ == '__main__':
    main()
