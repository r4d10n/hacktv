#!/usr/bin/env python3
"""
Resample hacktv signal to PAL-CRT format with carrier phase alignment.

The key insight is that PAL-CRT expects samples at exactly 0°, 90°, 180°, 270°
of the carrier cycle. We need to resample hacktv to hit these exact phases.
"""

import numpy as np
from scipy import signal as scipy_signal
from scipy.interpolate import interp1d
from PIL import Image
import ctypes

# Parameters
HACKTV_SR = 16e6
HACKTV_HRES = 1024
F_SC = 4433618.75
PALCRT_SR = F_SC * 4  # 17.73 MHz
PALCRT_HRES = 1135
PALCRT_VRES = 312

HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767
SYNC_LEVEL = -40
WHITE_LEVEL = 100


def find_burst_zero_crossing(line_data, burst_start=80, burst_end=130):
    """Find the positive-going zero crossing of the burst to get phase reference."""
    burst = line_data[burst_start:burst_end].astype(float)
    # Find zero crossings
    signs = np.sign(burst)
    zero_crossings = np.where(np.diff(signs) > 0)[0]  # Positive-going
    if len(zero_crossings) > 0:
        # Return the sample position of first positive-going zero crossing
        return burst_start + zero_crossings[0]
    return burst_start + len(burst) // 2


def resample_line_phase_locked(hacktv_line, line_num, frame_num):
    """
    Resample a single line with burst alignment.

    Key insight: PAL-CRT expects burst at ~7.1 µs (sample 126 at 17.73 MHz)
    But hacktv has burst at ~5.6 µs (sample 90 at 16 MHz)

    We need to add a time offset so that hacktv burst aligns with
    where PAL-CRT expects it.

    Timing offset = 7.1 - 5.6 = 1.5 µs
    """
    # hacktv burst is at ~5.6 µs from line start
    hacktv_burst_time = 5.6e-6

    # PAL-CRT expects burst at sample ~126, which is 126/17.73e6 = 7.1 µs
    palcrt_burst_time = 7.1e-6

    # Offset to add to hacktv time
    time_offset = palcrt_burst_time - hacktv_burst_time  # ~1.5 µs

    # Create interpolator for hacktv line
    hacktv_t = np.arange(len(hacktv_line)) / HACKTV_SR

    interp = interp1d(hacktv_t, hacktv_line.astype(float), kind='cubic',
                      bounds_error=False, fill_value=(hacktv_line[0], hacktv_line[-1]))

    # For each PAL-CRT sample, calculate the corresponding hacktv time
    palcrt_t = np.arange(PALCRT_HRES) / PALCRT_SR
    hacktv_sample_times = palcrt_t - time_offset  # Shift backward to align burst

    # Resample
    output = interp(hacktv_sample_times)

    # Convert to IRE scale
    normalized = (output - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
    ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

    return np.clip(ire, -128, 127).astype(np.int8)


def resample_field(hacktv_field, frame_num):
    """Resample a complete field."""
    output = np.zeros(PALCRT_HRES * PALCRT_VRES, dtype=np.int8)

    for line in range(PALCRT_VRES):
        src_start = line * HACKTV_HRES
        if src_start + HACKTV_HRES > len(hacktv_field):
            break

        line_data = hacktv_field[src_start:src_start + HACKTV_HRES]
        resampled = resample_line_phase_locked(line_data, line, frame_num)

        dst_start = line * PALCRT_HRES
        output[dst_start:dst_start + PALCRT_HRES] = resampled

    return output


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Resample hacktv with carrier phase locking')
    parser.add_argument('--input', type=str, default='/tmp/color_calibration/colorbars_pal.bin')
    parser.add_argument('--frame', type=int, default=15)
    parser.add_argument('--output', type=str, default='/tmp/resampled_phase_locked.png')
    args = parser.parse_args()

    print("Carrier Phase-Locked Resampler")
    print("=" * 50)

    # Load baseband
    baseband = np.fromfile(args.input, dtype=np.int16)

    # Extract field
    frame_samples = HACKTV_HRES * 625
    frame_start = args.frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = baseband[frame_start:frame_start + field_samples]

    print(f"Resampling frame {args.frame}...")
    resampled = resample_field(field_data, args.frame)

    # Decode with PAL-CRT
    print("Decoding...")
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()
    signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(resampled), output_buffer)

    decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
    Image.fromarray(decoded).save(args.output)

    lib.decode_cleanup()
    print(f"Saved: {args.output}")

    # Sample some pixels to check color
    print("\nColor samples:")
    samples = [(100, 100), (100, 300), (100, 500)]
    for y, x in samples:
        print(f"  ({y},{x}): RGB = {decoded[y, x]}")


if __name__ == '__main__':
    main()
