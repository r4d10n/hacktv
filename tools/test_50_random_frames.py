#!/usr/bin/env python3
"""
Test PAL decoder with color correction on 50 random frames.
Saves decoded frames and comparison results.
"""

import numpy as np
from PIL import Image
import ctypes
import os
import json
import random
from datetime import datetime

SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767

PAL_HRES = 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES

SYNC_LEVEL = -40
WHITE_LEVEL = 100

# Color correction matrix
COLOR_MATRIX = np.array([
    [ 1.0026791,  -1.0288666,   1.0008646],
    [-0.08147726,  0.8675986,   0.1154002],
    [-0.5413261,   2.5849624,  -1.1179323]
])


def resample_to_palcrt(field_data):
    """Resample hacktv 16MHz to PAL-CRT 4*f_sc."""
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


def apply_color_correction(img):
    """Apply color correction matrix."""
    flat = img.reshape(-1, 3).astype(np.float32)
    transformed = np.dot(flat, COLOR_MATRIX.T)
    return np.clip(transformed, 0, 255).astype(np.uint8).reshape(img.shape)


def main():
    print("50 Random Frame PAL Decoding Test")
    print("=" * 50)

    # Setup
    output_dir = 'samples/random_50_test'
    os.makedirs(output_dir, exist_ok=True)

    print("\nLoading PAL-CRT library...")
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int]*6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    print("Loading baseband...")
    baseband = np.fromfile('/tmp/pal_baseband.bin', dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME
    print(f"  Total frames available: {total_frames}")

    # Select 50 random frames (avoiding first/last 10 frames)
    random.seed(42)  # For reproducibility
    frame_range = list(range(10, min(total_frames - 10, 500)))
    test_frames = sorted(random.sample(frame_range, min(50, len(frame_range))))

    print(f"  Selected {len(test_frames)} random frames")
    print(f"  Frame range: {test_frames[0]} to {test_frames[-1]}")

    print("\nDecoding frames...")
    results = []

    for i, fn in enumerate(test_frames):
        frame_start = fn * SAMPLES_PER_FRAME
        frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

        # Decode
        field_samples = SAMPLES_PER_LINE * 312
        field_data = frame_data[:field_samples]
        resampled = resample_to_palcrt(field_data)
        signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
        lib.decode_field(signal_ptr, len(resampled), output_buffer)

        decoded_raw = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
        decoded_corrected = apply_color_correction(decoded_raw)

        # Save corrected frame
        img = Image.fromarray(decoded_corrected)
        img.save(f'{output_dir}/frame_{fn:04d}.png')

        # Compute basic stats
        mean_brightness = np.mean(decoded_corrected)
        color_variance = np.var(decoded_corrected.astype(float), axis=(0,1)).mean()

        results.append({
            'frame': fn,
            'mean_brightness': float(mean_brightness),
            'color_variance': float(color_variance)
        })

        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(test_frames)} frames...")

    lib.decode_cleanup()

    # Save results summary
    summary = {
        'timestamp': datetime.now().isoformat(),
        'total_frames_tested': len(test_frames),
        'frame_numbers': test_frames,
        'decoder': 'PAL-CRT + color correction matrix',
        'color_matrix': COLOR_MATRIX.tolist(),
        'frames': results,
        'statistics': {
            'mean_brightness': float(np.mean([r['mean_brightness'] for r in results])),
            'std_brightness': float(np.std([r['mean_brightness'] for r in results])),
            'mean_color_variance': float(np.mean([r['color_variance'] for r in results]))
        }
    }

    with open(f'{output_dir}/test_results.json', 'w') as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Frames decoded: {len(test_frames)}")
    print(f"Mean brightness: {summary['statistics']['mean_brightness']:.1f}")
    print(f"Brightness std: {summary['statistics']['std_brightness']:.1f}")
    print(f"Mean color variance: {summary['statistics']['mean_color_variance']:.1f}")
    print(f"\nResults saved to {output_dir}/")
    print(f"  - {len(test_frames)} decoded frames (frame_XXXX.png)")
    print(f"  - test_results.json")


if __name__ == '__main__':
    main()
