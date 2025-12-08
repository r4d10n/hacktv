#!/usr/bin/env python3
"""
Test different PAL-CRT parameter combinations to find best color decoding.
"""

import numpy as np
from PIL import Image
import ctypes
import os

SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767

PAL_HRES = 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES

SYNC_LEVEL = -40
WHITE_LEVEL = 100

# Reference colors (75% EBU)
EXPECTED_COLORS = np.array([
    [191, 191, 191],  # white
    [191, 191, 0],    # yellow
    [0, 191, 191],    # cyan
    [0, 191, 0],      # green
    [191, 0, 191],    # magenta
    [191, 0, 0],      # red
    [0, 0, 191],      # blue
    [0, 0, 0],        # black
])


def resample_to_palcrt(field_data):
    resampled = np.zeros(PAL_INPUT_SIZE, dtype=np.int8)
    for line in range(min(312, PAL_VRES)):
        src_start = line * SAMPLES_PER_LINE
        if src_start + SAMPLES_PER_LINE > len(field_data):
            break
        line_data = field_data[src_start:src_start + SAMPLES_PER_LINE].astype(np.float64)
        x_src = np.arange(len(line_data))
        x_dst = np.linspace(0, len(line_data) - 1, PAL_HRES)
        resampled_line = np.interp(x_dst, x_src, line_data)
        normalized = (resampled_line - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)
        resampled[line * PAL_HRES:(line + 1) * PAL_HRES] = np.clip(ire, -128, 127).astype(np.int8)
    return resampled


def sample_color_bars(image, num_bars=8):
    h, w = image.shape[:2]
    bar_width = w // num_bars
    samples = []
    y_start = h // 4
    y_end = 3 * h // 4
    for i in range(num_bars):
        x_center = i * bar_width + bar_width // 2
        x_start = x_center - bar_width // 4
        x_end = x_center + bar_width // 4
        region = image[y_start:y_end, x_start:x_end]
        mean_color = np.mean(region, axis=(0, 1))
        samples.append(mean_color)
    return np.array(samples)


def compute_error(measured, expected):
    return np.mean(np.sqrt(np.sum((measured - expected) ** 2, axis=1)))


def main():
    print("Testing PAL-CRT Parameter Combinations")
    print("=" * 60)

    # Load color bars baseband
    baseband_file = '/tmp/color_calibration/colorbars_pal.bin'
    if not os.path.exists(baseband_file):
        print("Run analyze_color_transform.py first!")
        return

    baseband = np.fromfile(baseband_file, dtype=np.int16)
    frame_num = 25
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]
    field_samples = SAMPLES_PER_LINE * 312
    field_data = frame_data[:field_samples]

    # Load PAL-CRT library
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')
    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int]*6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    # Test parameters
    saturations = [10, 20, 30, 40, 50, 60, 80, 100]
    contrasts = [128, 150, 180, 200, 220]
    chroma_corrections = [0, 1]

    results = []
    os.makedirs('/tmp/palcrt_tests', exist_ok=True)

    print("\nTesting parameter combinations...")
    for sat in saturations:
        for contrast in contrasts:
            for chroma in chroma_corrections:
                lib.decode_set_params(sat, 0, contrast, 0, 100, chroma)

                resampled = resample_to_palcrt(field_data)
                signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
                lib.decode_field(signal_ptr, len(resampled), output_buffer)

                decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
                measured = sample_color_bars(decoded)
                error = compute_error(measured, EXPECTED_COLORS)

                results.append({
                    'sat': sat,
                    'contrast': contrast,
                    'chroma': chroma,
                    'error': error,
                    'measured': measured
                })

    lib.decode_cleanup()

    # Sort by error
    results.sort(key=lambda x: x['error'])

    print("\nTop 10 configurations:")
    print("-" * 60)
    print(f"{'Rank':4s} {'Sat':4s} {'Cont':5s} {'Chr':4s} {'Error':8s}")
    print("-" * 60)

    for i, r in enumerate(results[:10]):
        print(f"{i+1:4d} {r['sat']:4d} {r['contrast']:5d} {r['chroma']:4d} {r['error']:8.1f}")

    # Show best result color mapping
    best = results[0]
    print(f"\nBest: sat={best['sat']}, contrast={best['contrast']}, chroma={best['chroma']}")
    print("\nColor mapping:")
    names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']
    for i, name in enumerate(names):
        exp = EXPECTED_COLORS[i]
        meas = best['measured'][i]
        print(f"  {name:10s}: expected ({exp[0]:3d},{exp[1]:3d},{exp[2]:3d}) → "
              f"decoded ({meas[0]:5.1f},{meas[1]:5.1f},{meas[2]:5.1f})")

    # Save best result image
    lib.decode_init(720, 576)
    lib.decode_set_params(best['sat'], 0, best['contrast'], 0, 100, best['chroma'])
    resampled = resample_to_palcrt(field_data)
    signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(resampled), output_buffer)
    decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
    Image.fromarray(decoded).save('/tmp/palcrt_tests/best_colorbars.png')
    lib.decode_cleanup()

    print(f"\nBest result saved to /tmp/palcrt_tests/best_colorbars.png")


if __name__ == '__main__':
    main()
