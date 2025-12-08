#!/usr/bin/env python3
"""
Generate rainbow and comprehensive color test patterns for PAL testing.
"""

import numpy as np
from PIL import Image
import colorsys
import os


def create_rainbow_gradient(width=720, height=576):
    """Create a horizontal rainbow gradient (full hue sweep)."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    for x in range(width):
        hue = x / width  # 0 to 1
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        img[:, x] = [int(r * 255), int(g * 255), int(b * 255)]

    return img


def create_rainbow_saturation(width=720, height=576):
    """Create rainbow with saturation gradient (horizontal=hue, vertical=saturation)."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    for y in range(height):
        sat = 1.0 - (y / height)  # Top: full saturation, bottom: gray
        for x in range(width):
            hue = x / width
            r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
            img[y, x] = [int(r * 255), int(g * 255), int(b * 255)]

    return img


def create_hsv_wheel(width=720, height=576):
    """Create HSV color wheel with brightness gradient."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    # Top half: hue sweep at full saturation and value
    half_h = height // 2
    for y in range(half_h):
        val = 0.5 + 0.5 * (y / half_h)  # 0.5 to 1.0
        for x in range(width):
            hue = x / width
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, val)
            img[y, x] = [int(r * 255), int(g * 255), int(b * 255)]

    # Bottom half: hue sweep with varying saturation
    for y in range(half_h, height):
        sat = 1.0 - ((y - half_h) / half_h)  # 1.0 to 0.0
        for x in range(width):
            hue = x / width
            r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
            img[y, x] = [int(r * 255), int(g * 255), int(b * 255)]

    return img


def create_color_squares(width=720, height=576):
    """Create a grid of color squares covering various hue/saturation combinations."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    # 12 hues x 4 saturations x 3 values = 144 squares
    num_hues = 12
    num_sats = 4
    num_vals = 3

    sq_w = width // num_hues
    sq_h = height // (num_sats * num_vals)

    for h_idx in range(num_hues):
        hue = h_idx / num_hues
        for s_idx in range(num_sats):
            sat = 1.0 - s_idx * 0.25  # 1.0, 0.75, 0.5, 0.25
            for v_idx in range(num_vals):
                val = 1.0 - v_idx * 0.25  # 1.0, 0.75, 0.5

                r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
                color = [int(r * 255), int(g * 255), int(b * 255)]

                row = s_idx * num_vals + v_idx
                x1 = h_idx * sq_w
                x2 = x1 + sq_w
                y1 = row * sq_h
                y2 = y1 + sq_h

                img[y1:y2, x1:x2] = color

    return img


def create_ramp_pattern(width=720, height=576):
    """Create color ramps that test specific aspects of color decoding."""
    img = np.zeros((height, width, 3), dtype=np.uint8)

    section_h = height // 8

    # Section 0: Pure red ramp
    for x in range(width):
        val = int(255 * x / width)
        img[0:section_h, x] = [val, 0, 0]

    # Section 1: Pure green ramp
    for x in range(width):
        val = int(255 * x / width)
        img[section_h:2*section_h, x] = [0, val, 0]

    # Section 2: Pure blue ramp
    for x in range(width):
        val = int(255 * x / width)
        img[2*section_h:3*section_h, x] = [0, 0, val]

    # Section 3: Yellow ramp (R+G)
    for x in range(width):
        val = int(255 * x / width)
        img[3*section_h:4*section_h, x] = [val, val, 0]

    # Section 4: Cyan ramp (G+B)
    for x in range(width):
        val = int(255 * x / width)
        img[4*section_h:5*section_h, x] = [0, val, val]

    # Section 5: Magenta ramp (R+B)
    for x in range(width):
        val = int(255 * x / width)
        img[5*section_h:6*section_h, x] = [val, 0, val]

    # Section 6: Gray ramp
    for x in range(width):
        val = int(255 * x / width)
        img[6*section_h:7*section_h, x] = [val, val, val]

    # Section 7: Rainbow
    for x in range(width):
        hue = x / width
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        img[7*section_h:8*section_h, x] = [int(r * 255), int(g * 255), int(b * 255)]

    return img


def main():
    out_dir = '/tmp/color_test_patterns'
    os.makedirs(out_dir, exist_ok=True)

    print("Generating comprehensive color test patterns...")

    # Generate all patterns
    patterns = [
        ('rainbow_hue.png', create_rainbow_gradient()),
        ('rainbow_saturation.png', create_rainbow_saturation()),
        ('hsv_wheel.png', create_hsv_wheel()),
        ('color_squares.png', create_color_squares()),
        ('color_ramps.png', create_ramp_pattern()),
    ]

    for name, img in patterns:
        path = os.path.join(out_dir, name)
        Image.fromarray(img).save(path)
        print(f"  Created: {path}")

    print("\nDone!")


if __name__ == '__main__':
    main()
