#!/usr/bin/env python3
"""
Convert hacktv 16MHz PAL baseband to PAL-CRT compatible format.

Key differences between hacktv and PAL-CRT:
- hacktv: 16 MHz, 1024 samples/line, sync at ~0-75, burst at ~90-126
- PAL-CRT: 17.73 MHz (4×f_sc), 1135 samples/line, sync at ~28-110, burst at ~126-170

This converter:
1. Shifts timing so sync/burst align with PAL-CRT expectations
2. Resamples to 17.73 MHz
3. Converts levels to PAL-CRT's IRE scale
"""

import numpy as np
from scipy.interpolate import interp1d
from PIL import Image
import ctypes
import sys
import os

# hacktv parameters (16 MHz)
HACKTV_SR = 16e6
HACKTV_HRES = 1024
HACKTV_SYNC_LEVEL = -0.30 * 32767  # -9830
HACKTV_WHITE_LEVEL = 0.70 * 32767  # +22937

# PAL parameters
F_SC = 4433618.75

# PAL-CRT parameters (4 × f_sc = 17.73 MHz)
PALCRT_SR = F_SC * 4  # 17,734,475 Hz
PALCRT_HRES = 1135
PALCRT_VRES = 312

# Timing (in microseconds from line start)
# hacktv: sync starts at ~0µs, burst at ~5.6µs, active at ~10.5µs
# PAL-CRT: sync starts at ~1.6µs, burst at ~7.1µs, active at ~12µs
HACKTV_SYNC_START_US = 0.0
HACKTV_BURST_START_US = 5.6
PALCRT_SYNC_START_US = 1.6
PALCRT_BURST_START_US = 7.1

# Time shift to align burst positions
TIME_SHIFT_US = PALCRT_BURST_START_US - HACKTV_BURST_START_US  # ~1.5 µs

# PAL-CRT IRE levels
SYNC_LEVEL = -40
BLACK_LEVEL = 0
WHITE_LEVEL = 100


def convert_line(hacktv_line):
    """
    Convert a single line from hacktv 16MHz to PAL-CRT 17.73MHz format.

    The conversion:
    1. Create time axis for hacktv samples (0 to 64µs)
    2. Create time axis for PAL-CRT samples, shifted by TIME_SHIFT_US
    3. Interpolate hacktv samples at shifted PAL-CRT times
    4. Convert to IRE scale
    """
    # Time axis for hacktv (64 µs line)
    hacktv_t = np.arange(HACKTV_HRES) / HACKTV_SR  # 0 to 64µs

    # Create interpolator
    interp = interp1d(hacktv_t, hacktv_line.astype(float),
                      kind='cubic', bounds_error=False,
                      fill_value=(hacktv_line[0], hacktv_line[-1]))

    # Time axis for PAL-CRT, shifted backward to align burst
    palcrt_t = np.arange(PALCRT_HRES) / PALCRT_SR  # 0 to 64µs
    shifted_t = palcrt_t - TIME_SHIFT_US * 1e-6  # Shift to align

    # Interpolate
    resampled = interp(shifted_t)

    # Convert to IRE scale
    # hacktv: sync=-9830, white=+22937 (range = 32767)
    # PAL-CRT: sync=-40, white=+100 (range = 140)
    normalized = (resampled - HACKTV_SYNC_LEVEL) / (HACKTV_WHITE_LEVEL - HACKTV_SYNC_LEVEL)
    ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

    return np.clip(ire, -128, 127).astype(np.int8)


def convert_field(hacktv_field):
    """Convert a complete field."""
    output = np.zeros(PALCRT_HRES * PALCRT_VRES, dtype=np.int8)

    for line in range(PALCRT_VRES):
        src_start = line * HACKTV_HRES
        if src_start + HACKTV_HRES > len(hacktv_field):
            break

        hacktv_line = hacktv_field[src_start:src_start + HACKTV_HRES]
        converted = convert_line(hacktv_line)

        dst_start = line * PALCRT_HRES
        output[dst_start:dst_start + PALCRT_HRES] = converted

    return output


def decode_with_palcrt(signal, saturation=30, contrast=180):
    """Decode a signal using PAL-CRT library."""
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(saturation, 0, contrast, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()
    signal_ptr = signal.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(signal), output_buffer)

    decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
    lib.decode_cleanup()

    return decoded


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Convert hacktv to PAL-CRT format')
    parser.add_argument('--input', type=str, required=True, help='Input hacktv baseband file')
    parser.add_argument('--frame', type=int, default=0, help='Frame number')
    parser.add_argument('--output', type=str, required=True, help='Output image')
    parser.add_argument('--saturation', type=int, default=30, help='PAL-CRT saturation')
    parser.add_argument('--contrast', type=int, default=180, help='PAL-CRT contrast')
    args = parser.parse_args()

    print("hacktv to PAL-CRT Converter")
    print("=" * 50)

    # Load baseband
    print(f"Loading {args.input}...")
    baseband = np.fromfile(args.input, dtype=np.int16)

    frame_samples = HACKTV_HRES * 625
    total_frames = len(baseband) // frame_samples
    print(f"  Total frames: {total_frames}")

    if args.frame >= total_frames:
        print(f"Error: Frame {args.frame} out of range")
        return 1

    # Extract field
    frame_start = args.frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = baseband[frame_start:frame_start + field_samples]

    # Convert
    print(f"Converting frame {args.frame}...")
    converted = convert_field(field_data)

    # Decode
    print("Decoding with PAL-CRT...")
    decoded = decode_with_palcrt(converted, args.saturation, args.contrast)

    # Save
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    Image.fromarray(decoded).save(args.output)
    print(f"Saved: {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
