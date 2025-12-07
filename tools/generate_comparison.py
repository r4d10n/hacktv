#!/usr/bin/env python3
"""
Generate comparison videos using all three PAL decoders:
1. Custom Python decoder (decode_baseband.py)
2. PAL-CRT library (decode_pal_crt.py)
3. Svofski-style decoder (decode_svofski.py)
"""

import os
import sys
import subprocess
import numpy as np
from PIL import Image
import argparse

# Add tools directory to path
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)


def decode_with_custom(input_file, output_file, sample_rate, num_frames):
    """Decode using custom Python decoder."""
    print("\n=== Custom Python Decoder ===")
    cmd = [
        'python3', os.path.join(TOOLS_DIR, 'decode_baseband.py'),
        input_file, output_file,
        '-m', 'pal',
        '-s', str(sample_rate),
        '-n', str(num_frames)
    ]
    subprocess.run(cmd, check=True)
    return output_file


def decode_with_pal_crt(input_file, output_file, sample_rate, num_frames):
    """Decode using PAL-CRT library."""
    print("\n=== PAL-CRT Decoder ===")
    cmd = [
        'python3', os.path.join(TOOLS_DIR, 'decode_pal_crt.py'),
        input_file, output_file,
        '-s', str(sample_rate),
        '-n', str(num_frames)
    ]
    subprocess.run(cmd, check=True)
    return output_file


def decode_with_svofski(input_file, output_file, sample_rate, num_frames):
    """Decode using svofski-style decoder."""
    print("\n=== Svofski-style Decoder ===")
    cmd = [
        'python3', os.path.join(TOOLS_DIR, 'decode_svofski.py'),
        input_file, output_file,
        '-s', str(sample_rate),
        '-n', str(num_frames)
    ]
    subprocess.run(cmd, check=True)
    return output_file


def create_side_by_side(images, output_file, labels=None):
    """Create side-by-side comparison image."""
    widths = [img.width for img in images]
    heights = [img.height for img in images]

    total_width = sum(widths)
    max_height = max(heights)

    combined = Image.new('RGB', (total_width, max_height + 30), (0, 0, 0))

    x_offset = 0
    for i, img in enumerate(images):
        combined.paste(img, (x_offset, 30))
        if labels and i < len(labels):
            # Would need PIL.ImageDraw for text, skip for now
            pass
        x_offset += img.width

    combined.save(output_file)
    print(f"Saved comparison to {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Generate PAL decoder comparison videos')
    parser.add_argument('input', help='Input baseband file (int16 raw)')
    parser.add_argument('-o', '--output', default='/tmp/comparison',
                        help='Output directory prefix')
    parser.add_argument('-s', '--samplerate', type=int, default=16000000,
                        help='Input sample rate')
    parser.add_argument('-n', '--frames', type=int, default=375,
                        help='Number of frames (375 = 15 seconds at 25fps)')
    parser.add_argument('--decoders', nargs='+',
                        default=['custom', 'pal_crt', 'svofski'],
                        help='Which decoders to use')

    args = parser.parse_args()

    print(f"Input: {args.input}")
    print(f"Frames: {args.frames} ({args.frames / 25:.1f} seconds)")
    print(f"Decoders: {args.decoders}")

    outputs = {}

    # Run each decoder
    if 'custom' in args.decoders:
        try:
            outputs['custom'] = decode_with_custom(
                args.input,
                f"{args.output}_custom.mp4",
                args.samplerate,
                args.frames
            )
        except Exception as e:
            print(f"Custom decoder failed: {e}")

    if 'pal_crt' in args.decoders:
        try:
            outputs['pal_crt'] = decode_with_pal_crt(
                args.input,
                f"{args.output}_pal_crt.mp4",
                args.samplerate,
                args.frames
            )
        except Exception as e:
            print(f"PAL-CRT decoder failed: {e}")

    if 'svofski' in args.decoders:
        try:
            outputs['svofski'] = decode_with_svofski(
                args.input,
                f"{args.output}_svofski.png",  # Single frame for now
                args.samplerate,
                1  # Just one frame for svofski (slow)
            )
        except Exception as e:
            print(f"Svofski decoder failed: {e}")

    print("\n=== Results ===")
    for name, path in outputs.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  {name}: {path} ({size / 1024 / 1024:.1f} MB)")
        else:
            print(f"  {name}: FAILED")


if __name__ == '__main__':
    main()
