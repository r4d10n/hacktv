#!/usr/bin/env python3
"""
Analyze what PAL-CRT's own encoder produces to understand the expected format.
"""

import numpy as np
from PIL import Image
import ctypes
import os

F_SC = 4433618.75
PALCRT_SR = F_SC * 4
PALCRT_HRES = 1135
PALCRT_VRES = 312

# Burst location in PAL-CRT format (at 17.73 MHz)
# Burst should be ~7.1µs = sample 126 to ~9.3µs = sample 165
BURST_START = 126
BURST_END = 165


def encode_with_palcrt(rgb_image):
    """Encode RGB image to PAL signal using PAL-CRT's encoder."""
    lib_path = os.path.join(os.path.dirname(__file__), '../external/pal-crt/libpal_decode.so')
    lib = ctypes.CDLL(lib_path)

    # Setup function signatures
    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.encode_field.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_int8)]
    lib.encode_field.restype = ctypes.c_int
    lib.decode_cleanup.restype = None

    height, width, _ = rgb_image.shape

    # Initialize decoder first (required for encode_field to work)
    ret = lib.decode_init(width, height)
    if ret != 0:
        print(f"decode_init failed with code {ret}")
        return None

    rgb_ptr = rgb_image.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))

    signal = np.zeros(PALCRT_HRES * PALCRT_VRES, dtype=np.int8)
    signal_ptr = signal.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))

    ret = lib.encode_field(rgb_ptr, width, height, signal_ptr)
    if ret != 0:
        print(f"encode_field failed with code {ret}")
        lib.decode_cleanup()
        return None

    lib.decode_cleanup()
    return signal


def analyze_burst(signal_line, line_num):
    """Analyze burst phase and amplitude in a line."""
    omega = 2 * np.pi * F_SC / PALCRT_SR  # Should be exactly π/2 per sample

    burst = signal_line[BURST_START:BURST_END].astype(np.float64)
    t = np.arange(BURST_START, BURST_END)

    # Demodulate
    burst_sin = burst * np.sin(t * omega)
    burst_cos = burst * np.cos(t * omega)

    sin_mean = np.mean(burst_sin)
    cos_mean = np.mean(burst_cos)

    phase = np.arctan2(sin_mean, cos_mean) * 180 / np.pi
    amp = np.sqrt(sin_mean**2 + cos_mean**2)

    return phase, amp


def analyze_chroma(signal_line, start, end, burst_phase):
    """Analyze chroma in a region with burst-locked demodulation."""
    omega = 2 * np.pi * F_SC / PALCRT_SR

    # Phase correction to align with burst
    phase_correction = (135 - burst_phase) * np.pi / 180

    region = signal_line[start:end].astype(np.float64)
    t = np.arange(start, end)

    i_demod = region * np.cos(t * omega + phase_correction)
    q_demod = region * np.sin(t * omega + phase_correction)

    return np.mean(i_demod) * 2, np.mean(q_demod) * 2


def main():
    print("PAL-CRT Encoded Signal Analysis")
    print("=" * 60)

    # Create a color bar test image
    height = 576
    width = 720
    bar_width = width // 8

    # 75% color bars: white, yellow, cyan, green, magenta, red, blue, black
    colors_75 = [
        (191, 191, 191),  # white
        (191, 191, 0),    # yellow
        (0, 191, 191),    # cyan
        (0, 191, 0),      # green
        (191, 0, 191),    # magenta
        (191, 0, 0),      # red
        (0, 0, 191),      # blue
        (0, 0, 0),        # black
    ]

    image = np.zeros((height, width, 3), dtype=np.uint8)
    for i, color in enumerate(colors_75):
        image[:, i*bar_width:(i+1)*bar_width] = color

    print("Created 75% color bar test image")

    # Encode
    print("Encoding with PAL-CRT...")
    signal = encode_with_palcrt(image)

    print(f"Signal shape: {signal.shape}, dtype: {signal.dtype}")
    print(f"Signal range: [{np.min(signal)}, {np.max(signal)}]")

    # Analyze burst phase across lines
    print("\nBurst phase analysis (lines 100-110):")
    print("-" * 50)

    for line in range(100, 111):
        line_start = line * PALCRT_HRES
        line_data = signal[line_start:line_start + PALCRT_HRES]

        phase, amp = analyze_burst(line_data, line)
        v_switch = -1 if line & 1 else 1

        print(f"  Line {line}: burst_phase={phase:+7.1f}°, amp={amp:.0f}, v_sw={v_switch:+d}")

    # Analyze color bar on specific line
    print("\n\nColor bar analysis on line 200:")
    print("-" * 60)

    line_num = 200
    line_start = line_num * PALCRT_HRES
    line_data = signal[line_start:line_start + PALCRT_HRES]

    burst_phase, burst_amp = analyze_burst(line_data, line_num)
    print(f"Burst phase: {burst_phase:.1f}°, amp: {burst_amp:.0f}")

    # Color bar regions in PAL-CRT (active video starts ~12µs = sample 213)
    ACTIVE_START = 230
    BAR_WIDTH = 57  # 720 pixels / 8 bars ≈ 90 -> scaled to 1135 samples / 64µs active
    bar_names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']

    print("\nMeasured chroma:")
    for i, name in enumerate(bar_names):
        bar_start = ACTIVE_START + i * BAR_WIDTH + 10
        bar_end = bar_start + BAR_WIDTH - 20

        region = line_data[bar_start:bar_end]
        y_mean = np.mean(region.astype(float))

        i_val, q_val = analyze_chroma(line_data, bar_start, bar_end, burst_phase)
        amp = np.sqrt(i_val**2 + q_val**2)
        phase = np.arctan2(q_val, i_val) * 180 / np.pi

        print(f"  {name:10s}: Y={y_mean:+6.1f}, I={i_val:+7.1f}, Q={q_val:+7.1f}, "
              f"amp={amp:6.1f}, phase={phase:+7.1f}°")

    # Compare hacktv and PAL-CRT burst/timing expectations
    print("\n\nTiming analysis:")
    print("-" * 60)

    # Find sync tip in line
    line_data_float = line_data.astype(float)
    sync_level = np.min(line_data_float[:200])
    sync_region = np.where(line_data_float[:200] < sync_level + 10)[0]
    if len(sync_region) > 0:
        sync_start = sync_region[0]
        sync_end = sync_region[-1]
        print(f"Sync region: samples {sync_start}-{sync_end}")
        print(f"  Time: {sync_start/PALCRT_SR*1e6:.2f}µs - {sync_end/PALCRT_SR*1e6:.2f}µs")

    # Find burst region (local max around burst location)
    burst_region = np.abs(line_data_float[100:200])
    burst_peak = np.argmax(burst_region) + 100
    print(f"Burst peak at sample: {burst_peak}")
    print(f"  Time: {burst_peak/PALCRT_SR*1e6:.2f}µs")

    # Show raw samples around key regions
    print("\nRaw samples (sync region, samples 0-50):")
    for s in range(0, 50, 5):
        vals = [f"{line_data[s+i]:+4d}" for i in range(5)]
        print(f"  [{s:3d}-{s+4:3d}]: " + ", ".join(vals))

    print("\nRaw samples (burst region, samples 126-166):")
    for s in range(126, 166, 5):
        vals = [f"{line_data[s+i]:+4d}" for i in range(5)]
        print(f"  [{s:3d}-{s+4:3d}]: " + ", ".join(vals))


if __name__ == '__main__':
    main()
