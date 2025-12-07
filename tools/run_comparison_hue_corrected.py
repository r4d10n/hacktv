#!/usr/bin/env python3
"""
Run comparison with hue-corrected PAL-CRT decoder.
Applies 180-degree hue rotation to fix U/V axis mismatch.
"""

import numpy as np
import ctypes
from PIL import Image
import subprocess
import os
import json
import colorsys
from datetime import datetime

# PAL-CRT constants
PAL_HRES = 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES

# hacktv constants
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

# Signal levels
HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767
SYNC_LEVEL = -40
WHITE_LEVEL = 100


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


def rotate_hue(image, degrees):
    """Rotate hue of RGB image by specified degrees."""
    img = image.astype(np.float32) / 255.0

    # Convert to HSV
    h, w, _ = img.shape
    hsv = np.zeros_like(img)

    for y in range(h):
        for x in range(w):
            r, g, b = img[y, x]
            h_val, s, v = colorsys.rgb_to_hsv(r, g, b)
            h_val = (h_val + degrees / 360.0) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h_val, s, v)
            hsv[y, x] = [r, g, b]

    return (hsv * 255).astype(np.uint8)


def rotate_hue_fast(image, degrees):
    """Fast vectorized hue rotation using matrix transformation."""
    # Convert degrees to radians
    theta = np.radians(degrees)

    # RGB to YIQ-like rotation matrix for hue shift
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)

    # Hue rotation matrix (approximate but fast)
    matrix = np.array([
        [0.299 + 0.701*cos_t + 0.168*sin_t, 0.587 - 0.587*cos_t + 0.330*sin_t, 0.114 - 0.114*cos_t - 0.497*sin_t],
        [0.299 - 0.299*cos_t - 0.328*sin_t, 0.587 + 0.413*cos_t + 0.035*sin_t, 0.114 - 0.114*cos_t + 0.292*sin_t],
        [0.299 - 0.300*cos_t + 1.250*sin_t, 0.587 - 0.588*cos_t - 1.050*sin_t, 0.114 + 0.886*cos_t - 0.203*sin_t]
    ])

    img_float = image.astype(np.float32)
    result = np.dot(img_float, matrix.T)
    return np.clip(result, 0, 255).astype(np.uint8)


def compute_metrics(original, decoded):
    """Compute quality metrics."""
    if original.shape != decoded.shape:
        img = Image.fromarray(decoded)
        img = img.resize((original.shape[1], original.shape[0]), Image.LANCZOS)
        decoded = np.array(img)

    mse = np.mean((original.astype(float) - decoded.astype(float)) ** 2)
    psnr = 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')

    return {'psnr': psnr, 'mse': mse}


def main():
    baseband_file = '/tmp/pal_baseband.bin'
    original_video = 'samples/nature_original.mp4'
    output_dir = '/tmp/hue_corrected_comparison'

    os.makedirs(output_dir, exist_ok=True)

    # Load PAL-CRT library
    lib_path = 'external/pal-crt/libpal_decode.so'
    lib = ctypes.CDLL(lib_path)

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int]*6
    lib.decode_cleanup.restype = None

    # Initialize decoder
    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    # Load baseband
    print("Loading baseband...")
    baseband = np.fromfile(baseband_file, dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME
    frames_to_process = min(500, total_frames)
    print(f"Total frames: {total_frames}, processing: {frames_to_process}")

    # Extract original frames
    print("Extracting original frames...")
    orig_dir = f'{output_dir}/original'
    os.makedirs(orig_dir, exist_ok=True)

    subprocess.run([
        'ffmpeg', '-y', '-i', original_video,
        '-vframes', str(frames_to_process),
        '-pix_fmt', 'rgb24',
        f'{orig_dir}/frame_%04d.png'
    ], capture_output=True)

    # Load original frames
    original_frames = []
    for i in range(1, frames_to_process + 1):
        path = f'{orig_dir}/frame_{i:04d}.png'
        if os.path.exists(path):
            img = Image.open(path).resize((720, 576), Image.LANCZOS)
            original_frames.append(np.array(img))

    print(f"Loaded {len(original_frames)} original frames")

    # Test different hue rotations
    hue_rotations = [0, 90, 120, 150, 180, 210, 240, 270]

    print("\nTesting hue rotations on frame 250...")
    frame_num = 250
    frame_start = frame_num * SAMPLES_PER_FRAME
    field_samples = SAMPLES_PER_LINE * 312
    field_data = baseband[frame_start:frame_start + field_samples]
    resampled = resample_to_palcrt(field_data)
    signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(resampled), output_buffer)
    decoded_base = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()

    best_hue = 0
    best_psnr = 0

    for hue in hue_rotations:
        if hue == 0:
            decoded = decoded_base.copy()
        else:
            decoded = rotate_hue_fast(decoded_base, hue)

        metrics = compute_metrics(original_frames[frame_num], decoded)
        print(f"  Hue {hue:3d}°: PSNR = {metrics['psnr']:.2f} dB")

        if metrics['psnr'] > best_psnr:
            best_psnr = metrics['psnr']
            best_hue = hue

        # Save sample
        img = Image.fromarray(decoded)
        img.save(f'{output_dir}/hue_{hue:03d}_frame250.png')

    print(f"\nBest hue rotation: {best_hue}° with PSNR {best_psnr:.2f} dB")

    # Run full comparison with best hue
    print(f"\nRunning full comparison with hue rotation = {best_hue}°...")
    results = []

    for frame_num in range(min(frames_to_process, len(original_frames))):
        if (frame_num + 1) % 50 == 0:
            print(f"  Frame {frame_num + 1}/{frames_to_process}")

        frame_start = frame_num * SAMPLES_PER_FRAME
        field_data = baseband[frame_start:frame_start + field_samples]
        resampled = resample_to_palcrt(field_data)
        signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
        lib.decode_field(signal_ptr, len(resampled), output_buffer)
        decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()

        if best_hue != 0:
            decoded = rotate_hue_fast(decoded, best_hue)

        metrics = compute_metrics(original_frames[frame_num], decoded)
        results.append(metrics)

        if frame_num in [0, 100, 250, 400]:
            img = Image.fromarray(decoded)
            img.save(f'{output_dir}/corrected_frame_{frame_num:04d}.png')

    lib.decode_cleanup()

    # Calculate statistics
    psnr_values = [r['psnr'] for r in results]
    mse_values = [r['mse'] for r in results]

    stats = {
        'timestamp': datetime.now().isoformat(),
        'frames_processed': len(results),
        'decoder': f'PAL-CRT with saturation=30, hue_correction={best_hue}',
        'hue_correction_degrees': best_hue,
        'psnr': {
            'mean': float(np.mean(psnr_values)),
            'std': float(np.std(psnr_values)),
            'min': float(np.min(psnr_values)),
            'max': float(np.max(psnr_values))
        },
        'mse': {
            'mean': float(np.mean(mse_values)),
            'std': float(np.std(mse_values)),
            'min': float(np.min(mse_values)),
            'max': float(np.max(mse_values))
        }
    }

    with open(f'{output_dir}/results.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print()
    print("=" * 60)
    print("RESULTS WITH HUE CORRECTION")
    print("=" * 60)
    print(f"Frames processed: {stats['frames_processed']}")
    print(f"Hue correction: {best_hue}°")
    print(f"Mean PSNR: {stats['psnr']['mean']:.2f} dB")
    print(f"PSNR range: {stats['psnr']['min']:.2f} - {stats['psnr']['max']:.2f} dB")
    print(f"Mean MSE: {stats['mse']['mean']:.2f}")
    print(f"Results saved to {output_dir}/results.json")


if __name__ == '__main__':
    main()
