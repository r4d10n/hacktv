#!/usr/bin/env python3
"""
Convert hacktv 16MHz PAL baseband to PAL-CRT format with per-line phase alignment.

Key insight: PAL-CRT expects the carrier phase to be at specific positions per sample.
At 17.73 MHz (4 samples/cycle), sample N has phase = (N * 90°) mod 360°.

We need to resample hacktv such that the burst lands at a sample position where
PAL-CRT expects the burst phase (135° or -135° depending on line).
"""

import numpy as np
from scipy.interpolate import interp1d
from scipy import signal as scipy_signal
from PIL import Image
import ctypes
import sys
import os

# hacktv parameters
HACKTV_SR = 16e6
HACKTV_HRES = 1024
F_SC = 4433618.75

# PAL-CRT parameters
PALCRT_SR = F_SC * 4  # 17,734,475 Hz
PALCRT_HRES = 1135
PALCRT_VRES = 312

# Signal levels
HACKTV_SYNC = int(-0.30 * 32767)
HACKTV_BLACK = 0
HACKTV_WHITE = int(0.70 * 32767)
SYNC_LEVEL = -40
BLACK_LEVEL = 0
WHITE_LEVEL = 100

# Timing
HACKTV_BURST_START = 90
HACKTV_BURST_END = 126


def measure_burst_phase(line_data):
    """Measure the carrier phase at the burst."""
    omega = 2 * np.pi * F_SC / HACKTV_SR

    burst = line_data[HACKTV_BURST_START:HACKTV_BURST_END].astype(np.float64)
    t = np.arange(HACKTV_BURST_START, HACKTV_BURST_END)

    # Demodulate burst
    burst_sin = np.mean(burst * np.sin(t * omega))
    burst_cos = np.mean(burst * np.cos(t * omega))

    phase = np.arctan2(burst_sin, burst_cos)
    return phase


def convert_line_phase_aligned(hacktv_line, line_num):
    """
    Convert a line with phase alignment.

    PAL-CRT at 17.73 MHz: carrier phase at sample N is (N * 90°) mod 360°
    PAL burst should be at 135° (or -135° on alternate lines due to V-switch)

    We need to find the time offset such that when we resample, the burst
    lands at a PAL-CRT sample position with the correct phase.
    """
    # Measure actual burst phase in hacktv signal
    burst_phase = measure_burst_phase(hacktv_line)

    # PAL burst phase alternates: +135° on even lines, -135° on odd lines
    # (This is the V-switch for PAL)
    target_burst_phase = np.deg2rad(135) if line_num % 2 == 0 else np.deg2rad(-135)

    # PAL-CRT burst is around sample 145 (middle of burst region 126-165)
    # At sample 145, carrier phase = (145 * 90°) mod 360° = (13050) mod 360° = 90°
    # But we want burst at 135° or -135°...

    # Actually, let's think differently:
    # At PAL-CRT sample N, the carrier phase is (N * π/2) radians
    # We want to find time offset T such that:
    #   burst_phase (measured) maps to target_burst_phase at PAL-CRT output

    # The hacktv burst center is at ~5.8 µs
    hacktv_burst_time = (HACKTV_BURST_START + HACKTV_BURST_END) / 2 / HACKTV_SR

    # At this time, the carrier phase in hacktv is burst_phase
    # When resampled to PAL-CRT, we want sample M to have phase target_burst_phase
    # Sample M at PAL-CRT has phase (M * π/2)
    # So we want M such that (M * π/2) ≈ target_burst_phase (mod 2π)

    # Find M that gives closest phase to target
    # M * 90° ≈ target (in degrees)
    target_deg = np.rad2deg(target_burst_phase)
    if target_deg < 0:
        target_deg += 360

    # M = target_deg / 90, but M must be integer
    # Best M is around 145 for burst region
    # Let's find M in range 140-150 that gives closest phase
    best_m = 145
    best_diff = 180
    for m in range(135, 155):
        phase_at_m = (m * 90) % 360
        diff = min(abs(phase_at_m - target_deg), 360 - abs(phase_at_m - target_deg))
        if diff < best_diff:
            best_diff = diff
            best_m = m

    # Time at PAL-CRT sample best_m
    palcrt_burst_time = best_m / PALCRT_SR

    # Time offset to align bursts
    time_offset = palcrt_burst_time - hacktv_burst_time

    # Also need to account for the phase difference
    # The measured burst_phase needs to map to the phase at best_m
    phase_at_best_m = (best_m * np.pi / 2) % (2 * np.pi)
    phase_diff = burst_phase - phase_at_best_m

    # Convert phase difference to time shift
    # phase = omega * t, so t = phase / omega
    omega_palcrt = 2 * np.pi * F_SC / PALCRT_SR  # = π/2 per sample
    additional_time_shift = phase_diff / (2 * np.pi * F_SC)

    total_time_offset = time_offset + additional_time_shift

    # Create interpolator
    hacktv_t = np.arange(HACKTV_HRES) / HACKTV_SR
    interp = interp1d(hacktv_t, hacktv_line.astype(float), kind='cubic',
                      bounds_error=False, fill_value=(hacktv_line[0], hacktv_line[-1]))

    # Generate PAL-CRT samples
    palcrt_t = np.arange(PALCRT_HRES) / PALCRT_SR
    source_t = palcrt_t - total_time_offset

    resampled = interp(source_t)

    # Convert to IRE scale
    normalized = (resampled - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
    ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

    return np.clip(ire, -128, 127).astype(np.int8)


def convert_field(hacktv_field):
    """Convert a complete field with per-line phase alignment."""
    output = np.zeros(PALCRT_HRES * PALCRT_VRES, dtype=np.int8)

    for line in range(PALCRT_VRES):
        src_start = line * HACKTV_HRES
        if src_start + HACKTV_HRES > len(hacktv_field):
            break

        hacktv_line = hacktv_field[src_start:src_start + HACKTV_HRES]
        converted = convert_line_phase_aligned(hacktv_line, line)

        dst_start = line * PALCRT_HRES
        output[dst_start:dst_start + PALCRT_HRES] = converted

    return output


def decode_with_palcrt(signal, saturation=100, contrast=180):
    """Decode using PAL-CRT library."""
    lib_path = os.path.join(os.path.dirname(__file__), '../external/pal-crt/libpal_decode.so')
    lib = ctypes.CDLL(lib_path)

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
    parser = argparse.ArgumentParser(description='Convert hacktv to PAL-CRT with phase alignment')
    parser.add_argument('--input', type=str, required=True)
    parser.add_argument('--frame', type=int, default=0)
    parser.add_argument('--output', type=str, required=True)
    parser.add_argument('--saturation', type=int, default=100)
    parser.add_argument('--contrast', type=int, default=180)
    args = parser.parse_args()

    print("Phase-Aligned hacktv to PAL-CRT Converter")
    print("=" * 50)

    # Load baseband
    print(f"Loading {args.input}...")
    file_size = os.path.getsize(args.input)
    frame_samples = HACKTV_HRES * 625
    total_frames = file_size // (frame_samples * 2)
    print(f"  Total frames: {total_frames}")

    if args.frame >= total_frames:
        print(f"Error: Frame {args.frame} out of range")
        return 1

    baseband = np.memmap(args.input, dtype=np.int16, mode='r')

    # Extract field
    frame_start = args.frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = np.array(baseband[frame_start:frame_start + field_samples])

    # Convert with phase alignment
    print(f"Converting frame {args.frame} with phase alignment...")
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
