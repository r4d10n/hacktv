#!/usr/bin/env python3
"""
Run full 500-frame comparison using PAL-CRT decoder with optimized settings.
"""

import numpy as np
import ctypes
from PIL import Image
import subprocess
import os
import json
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
    output_dir = '/tmp/full_comparison'

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

    # Initialize decoder with optimized settings
    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)  # Higher saturation

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

    # Process frames
    results = []
    print("Processing frames...")

    for frame_num in range(min(frames_to_process, len(original_frames))):
        if (frame_num + 1) % 50 == 0:
            print(f"  Frame {frame_num + 1}/{frames_to_process}")

        # Extract field
        frame_start = frame_num * SAMPLES_PER_FRAME
        field_samples = SAMPLES_PER_LINE * 312
        field_data = baseband[frame_start:frame_start + field_samples]

        # Resample
        resampled = resample_to_palcrt(field_data)

        # Decode
        signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
        lib.decode_field(signal_ptr, len(resampled), output_buffer)

        decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()

        # Compute metrics
        metrics = compute_metrics(original_frames[frame_num], decoded)
        results.append(metrics)

        # Save sample frames
        if frame_num in [0, 100, 250, 400]:
            img = Image.fromarray(decoded)
            img.save(f'{output_dir}/decoded_frame_{frame_num:04d}.png')

    lib.decode_cleanup()

    # Calculate statistics
    psnr_values = [r['psnr'] for r in results]
    mse_values = [r['mse'] for r in results]

    stats = {
        'timestamp': datetime.now().isoformat(),
        'frames_processed': len(results),
        'decoder': 'PAL-CRT with saturation=30',
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

    # Save results
    with open(f'{output_dir}/results.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Frames processed: {stats['frames_processed']}")
    print(f"Mean PSNR: {stats['psnr']['mean']:.2f} dB")
    print(f"PSNR range: {stats['psnr']['min']:.2f} - {stats['psnr']['max']:.2f} dB")
    print(f"Mean MSE: {stats['mse']['mean']:.2f}")
    print(f"Results saved to {output_dir}/results.json")


if __name__ == '__main__':
    main()
