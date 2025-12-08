#!/usr/bin/env python3
"""
Decode PAL baseband using PAL-CRT with proper sinc resampling.

Key insight: hacktv outputs at 16 MHz (3.6 samples/cycle), but PAL-CRT
expects exactly 4 samples per subcarrier cycle (17.73 MHz).

This script properly resamples the signal to maintain phase coherence
of the chroma signal.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import ctypes
import os
import subprocess
import tempfile
import sys

# hacktv parameters
HACKTV_SAMPLE_RATE = 16e6
HACKTV_SAMPLES_PER_LINE = 1024
HACKTV_SAMPLES_PER_FRAME = HACKTV_SAMPLES_PER_LINE * 625

HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767

# PAL parameters
F_SC = 4433618.75  # PAL subcarrier frequency

# PAL-CRT parameters (4 samples per subcarrier cycle)
PALCRT_SAMPLE_RATE = F_SC * 4  # = 17,734,475 Hz
PALCRT_SAMPLES_PER_LINE = 1135  # ~64µs at 17.73 MHz
PALCRT_LINES_PER_FIELD = 312

# IRE levels for PAL-CRT
SYNC_LEVEL = -40
WHITE_LEVEL = 100


def resample_line_sinc(line_data, src_rate, dst_rate, dst_len):
    """
    Resample a single line using scipy's resample (sinc interpolation).
    This preserves the high-frequency chroma content properly.
    """
    # Calculate proper output length based on rate ratio
    src_len = len(line_data)
    # scipy.signal.resample uses sinc interpolation
    resampled = scipy_signal.resample(line_data.astype(np.float64), dst_len)
    return resampled


def resample_line_polyphase(line_data, up, down):
    """
    Resample using polyphase filter (more efficient for large ratios).
    up/down should be relatively prime integers representing the ratio.
    """
    return scipy_signal.resample_poly(line_data.astype(np.float64), up, down)


def resample_field_to_palcrt(field_data, method='sinc'):
    """
    Resample a full field from hacktv 16MHz to PAL-CRT 17.73MHz.

    method: 'sinc' for scipy.signal.resample, 'polyphase' for resample_poly
    """
    output = np.zeros(PALCRT_SAMPLES_PER_LINE * PALCRT_LINES_PER_FIELD, dtype=np.int8)

    for line in range(PALCRT_LINES_PER_FIELD):
        src_start = line * HACKTV_SAMPLES_PER_LINE
        if src_start + HACKTV_SAMPLES_PER_LINE > len(field_data):
            break

        line_data = field_data[src_start:src_start + HACKTV_SAMPLES_PER_LINE]

        if method == 'sinc':
            resampled = resample_line_sinc(line_data, HACKTV_SAMPLE_RATE,
                                          PALCRT_SAMPLE_RATE, PALCRT_SAMPLES_PER_LINE)
        else:
            # 17734475 / 16000000 ≈ 1135/1024 (close approximation)
            # Better: 4433618.75 * 4 / 16000000 = 17734475/16000000
            # Simplify: 1135/1024 is a good approximation
            resampled = resample_line_polyphase(line_data, 1135, 1024)
            # Trim or pad to exact length
            if len(resampled) > PALCRT_SAMPLES_PER_LINE:
                resampled = resampled[:PALCRT_SAMPLES_PER_LINE]
            elif len(resampled) < PALCRT_SAMPLES_PER_LINE:
                resampled = np.pad(resampled, (0, PALCRT_SAMPLES_PER_LINE - len(resampled)))

        # Convert to IRE scale for PAL-CRT
        normalized = (resampled - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

        dst_start = line * PALCRT_SAMPLES_PER_LINE
        output[dst_start:dst_start + PALCRT_SAMPLES_PER_LINE] = \
            np.clip(ire, -128, 127).astype(np.int8)

    return output


def decode_with_palcrt(resampled_field, lib, output_buffer, sat=30, contrast=180):
    """Decode a resampled field using PAL-CRT library."""
    lib.decode_set_params(sat, 0, contrast, 0, 100, 1)
    signal_ptr = resampled_field.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(resampled_field), output_buffer)
    return np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()


def measure_color_error(decoded, expected):
    """Measure color error between decoded and expected images."""
    diff = decoded.astype(np.float32) - expected.astype(np.float32)
    return np.sqrt(np.mean(diff ** 2))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Decode PAL with proper resampling')
    parser.add_argument('--test-pattern', type=str, default=None,
                        help='Test pattern image to encode and decode')
    parser.add_argument('--baseband', type=str, default='/tmp/pal_baseband.bin',
                        help='Baseband file to decode')
    parser.add_argument('--frame', type=int, default=0,
                        help='Frame number to decode')
    parser.add_argument('--output', type=str, default='/tmp/decoded_resampled.png',
                        help='Output image')
    parser.add_argument('--method', type=str, default='sinc',
                        choices=['sinc', 'polyphase'],
                        help='Resampling method')
    args = parser.parse_args()

    print("PAL-CRT Decoder with Proper Resampling")
    print("=" * 50)
    print(f"Resampling: {HACKTV_SAMPLE_RATE/1e6:.2f} MHz -> {PALCRT_SAMPLE_RATE/1e6:.2f} MHz")
    print(f"Method: {args.method}")

    # Load PAL-CRT library
    print("\nLoading PAL-CRT library...")
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    if args.test_pattern:
        # Encode and decode a test pattern
        print(f"\nTesting with pattern: {args.test_pattern}")

        # Generate PAL baseband from test pattern
        temp_bin = tempfile.mktemp(suffix='.bin')
        cmd = [
            './hacktv', '-o', temp_bin, '-m', 'i',
            '-l', '1',
            args.test_pattern
        ]
        print(f"  Encoding: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  hacktv failed: {result.stderr}")
            return 1

        baseband = np.fromfile(temp_bin, dtype=np.int16)
        os.unlink(temp_bin)

        frame_data = baseband[:int(HACKTV_SAMPLES_PER_FRAME)]
        reference = np.array(Image.open(args.test_pattern).convert('RGB').resize((720, 576)))
    else:
        # Decode from existing baseband
        print(f"\nDecoding frame {args.frame} from {args.baseband}")

        baseband = np.fromfile(args.baseband, dtype=np.int16)
        total_frames = len(baseband) // int(HACKTV_SAMPLES_PER_FRAME)
        print(f"  Total frames: {total_frames}")

        if args.frame >= total_frames:
            print(f"  Error: Frame {args.frame} out of range")
            return 1

        frame_start = args.frame * int(HACKTV_SAMPLES_PER_FRAME)
        frame_data = baseband[frame_start:frame_start + int(HACKTV_SAMPLES_PER_FRAME)]
        reference = None

    # Extract first field
    field_samples = HACKTV_SAMPLES_PER_LINE * PALCRT_LINES_PER_FIELD
    field_data = frame_data[:field_samples]

    print(f"\nResampling field ({args.method})...")
    resampled = resample_field_to_palcrt(field_data, method=args.method)
    print(f"  Input: {len(field_data)} samples")
    print(f"  Output: {len(resampled)} samples")

    print("\nDecoding with PAL-CRT...")
    decoded = decode_with_palcrt(resampled, lib, output_buffer)

    # Save result
    Image.fromarray(decoded).save(args.output)
    print(f"  Saved: {args.output}")

    if reference is not None:
        error = measure_color_error(decoded, reference)
        print(f"\n  RMS Error vs reference: {error:.1f}")

    lib.decode_cleanup()

    print("\nDone!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
