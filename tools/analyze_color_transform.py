#!/usr/bin/env python3
"""
Analyze the PAL-CRT color transformation by encoding/decoding color bars.

This script:
1. Creates color bar video
2. Encodes through hacktv PAL mode
3. Decodes with PAL-CRT
4. Compares decoded colors with expected values
5. Derives proper color correction
"""

import numpy as np
from PIL import Image
import subprocess
import ctypes
import os
import json

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

# Reference colors (75% EBU)
COLOR_BARS_75 = [
    ('white',   (191, 191, 191)),
    ('yellow',  (191, 191, 0)),
    ('cyan',    (0, 191, 191)),
    ('green',   (0, 191, 0)),
    ('magenta', (191, 0, 191)),
    ('red',     (191, 0, 0)),
    ('blue',    (0, 0, 191)),
    ('black',   (0, 0, 0)),
]


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


def decode_with_palcrt(lib, baseband_data, output_buffer):
    """Decode one frame with PAL-CRT."""
    field_samples = SAMPLES_PER_LINE * 312
    field_data = baseband_data[:field_samples]
    resampled = resample_to_palcrt(field_data)
    signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(resampled), output_buffer)
    return np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()


def sample_color_bars(image, num_bars=8):
    """Sample the center of each color bar."""
    h, w = image.shape[:2]
    bar_width = w // num_bars
    samples = []

    # Sample from middle rows (avoid edge artifacts)
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


def compute_color_correction_matrix(measured, expected):
    """
    Compute 3x3 color correction matrix using least squares.

    Transform: corrected = measured @ M.T
    We want: expected ≈ measured @ M.T
    """
    # Ensure float
    measured = measured.astype(np.float64)
    expected = expected.astype(np.float64)

    # Solve: expected = measured @ M.T
    # M.T = (measured.T @ measured)^-1 @ measured.T @ expected
    M_T, residuals, rank, s = np.linalg.lstsq(measured, expected, rcond=None)

    return M_T.T  # Return 3x3 matrix


def analyze_error(measured, expected, names):
    """Analyze color errors."""
    print("\nColor Error Analysis:")
    print("-" * 70)
    print(f"{'Color':12s} {'Expected':20s} {'Measured':20s} {'Error':10s}")
    print("-" * 70)

    total_error = 0
    for i, name in enumerate(names):
        exp = expected[i]
        meas = measured[i]
        error = np.sqrt(np.sum((exp - meas) ** 2))
        total_error += error
        print(f"{name:12s} ({exp[0]:3.0f},{exp[1]:3.0f},{exp[2]:3.0f})      "
              f"({meas[0]:3.0f},{meas[1]:3.0f},{meas[2]:3.0f})      {error:6.1f}")

    print("-" * 70)
    print(f"Mean RGB Error: {total_error / len(names):.1f}")
    return total_error / len(names)


def main():
    output_dir = '/tmp/color_calibration'
    os.makedirs(output_dir, exist_ok=True)

    print("PAL Color Transform Analysis")
    print("=" * 60)

    # Step 1: Create color bars video for hacktv
    print("\n1. Creating color bars video...")
    colorbars = Image.open('/tmp/color_test_patterns/colorbars_75.png')

    # Create short video (2 seconds = 50 frames)
    frames_dir = f'{output_dir}/frames'
    os.makedirs(frames_dir, exist_ok=True)
    for i in range(50):
        colorbars.save(f'{frames_dir}/frame_{i:04d}.png')

    # Convert to video
    subprocess.run([
        'ffmpeg', '-y', '-framerate', '25',
        '-i', f'{frames_dir}/frame_%04d.png',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        f'{output_dir}/colorbars.mp4'
    ], capture_output=True)
    print("   Created colorbars.mp4")

    # Step 2: Encode through hacktv
    print("\n2. Encoding through hacktv PAL...")
    baseband_file = f'{output_dir}/colorbars_pal.bin'
    result = subprocess.run([
        './hacktv', '-m', 'pal', '-o', baseband_file,
        f'{output_dir}/colorbars.mp4'
    ], capture_output=True, text=True)

    if not os.path.exists(baseband_file):
        print(f"   Error: {result.stderr}")
        return

    print(f"   Created {baseband_file}")

    # Step 3: Decode with PAL-CRT
    print("\n3. Decoding with PAL-CRT...")
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

    baseband = np.fromfile(baseband_file, dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME
    print(f"   Total frames: {total_frames}")

    # Decode frame 25 (middle of video, stable)
    frame_num = 25
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]
    decoded = decode_with_palcrt(lib, frame_data, output_buffer)

    Image.fromarray(decoded).save(f'{output_dir}/decoded_colorbars_raw.png')
    print(f"   Saved decoded_colorbars_raw.png")

    lib.decode_cleanup()

    # Step 4: Sample colors
    print("\n4. Sampling color bar values...")
    measured = sample_color_bars(decoded)
    expected = np.array([c[1] for c in COLOR_BARS_75])
    names = [c[0] for c in COLOR_BARS_75]

    # Analyze error before correction
    print("\nBEFORE CORRECTION:")
    error_before = analyze_error(measured, expected, names)

    # Step 5: Compute correction matrix
    print("\n5. Computing color correction matrix...")
    matrix = compute_color_correction_matrix(measured, expected)
    print("\nColor Correction Matrix:")
    print(matrix)

    # Step 6: Apply correction and verify
    print("\n6. Verifying correction...")
    corrected = np.dot(measured, matrix.T)
    corrected = np.clip(corrected, 0, 255)

    print("\nAFTER CORRECTION:")
    error_after = analyze_error(corrected, expected, names)

    print(f"\nError reduction: {error_before:.1f} → {error_after:.1f} "
          f"({100*(error_before-error_after)/error_before:.1f}% improvement)")

    # Step 7: Apply to full image
    print("\n7. Applying correction to decoded image...")
    decoded_flat = decoded.reshape(-1, 3).astype(np.float32)
    corrected_flat = np.dot(decoded_flat, matrix.T)
    corrected_img = np.clip(corrected_flat, 0, 255).astype(np.uint8).reshape(decoded.shape)

    Image.fromarray(corrected_img).save(f'{output_dir}/decoded_colorbars_corrected.png')
    print(f"   Saved decoded_colorbars_corrected.png")

    # Save matrix for use
    np.save(f'{output_dir}/color_correction_matrix.npy', matrix)
    with open(f'{output_dir}/color_correction_matrix.json', 'w') as f:
        json.dump({
            'matrix': matrix.tolist(),
            'measured_colors': {n: m.tolist() for n, m in zip(names, measured)},
            'expected_colors': {n: e.tolist() for n, e in zip(names, expected)},
            'error_before': error_before,
            'error_after': error_after
        }, f, indent=2)

    print(f"\n{'=' * 60}")
    print("RESULTS SAVED")
    print(f"{'=' * 60}")
    print(f"Matrix: {output_dir}/color_correction_matrix.npy")
    print(f"Report: {output_dir}/color_correction_matrix.json")
    print(f"\nNew matrix to use in decoder:")
    print("COLOR_MATRIX = np.array([")
    for row in matrix:
        print(f"    [{row[0]:10.6f}, {row[1]:10.6f}, {row[2]:10.6f}],")
    print("])")


if __name__ == '__main__':
    main()
