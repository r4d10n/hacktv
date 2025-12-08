#!/usr/bin/env python3
"""
Apply color correction to PAL-CRT decoded images.

PAL-CRT produces stable images but with wrong hue. We can find a color
transformation matrix that maps the wrong colors to correct colors.

Approach:
1. Decode a frame with PAL-CRT
2. Compare with original
3. Find optimal RGB->RGB transformation matrix
4. Apply to all frames
"""

import numpy as np
from scipy import optimize
from PIL import Image
import ctypes
import os

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


def decode_with_palcrt(lib, frame_data, output_buffer):
    """Decode one field with PAL-CRT."""
    field_samples = SAMPLES_PER_LINE * 312
    field_data = frame_data[:field_samples]
    resampled = resample_to_palcrt(field_data)
    signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(resampled), output_buffer)
    return np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()


def apply_color_matrix(img, matrix):
    """Apply 3x3 color transformation matrix to image."""
    flat = img.reshape(-1, 3).astype(np.float32)
    transformed = np.dot(flat, matrix.T)
    return np.clip(transformed, 0, 255).astype(np.uint8).reshape(img.shape)


def find_color_matrix(decoded, original):
    """Find optimal 3x3 matrix to transform decoded colors to original."""
    # Resize to match
    if decoded.shape != original.shape:
        decoded = np.array(Image.fromarray(decoded).resize(
            (original.shape[1], original.shape[0]), Image.LANCZOS))

    # Flatten and sample points (use subset for speed)
    h, w = decoded.shape[:2]
    step = 4
    dec_flat = decoded[::step, ::step].reshape(-1, 3).astype(np.float32)
    orig_flat = original[::step, ::step].reshape(-1, 3).astype(np.float32)

    # Find least-squares solution: orig = dec @ M.T
    # M = (dec.T @ dec)^-1 @ dec.T @ orig
    # Using pseudoinverse for stability
    M, residuals, rank, s = np.linalg.lstsq(dec_flat, orig_flat, rcond=None)

    return M.T  # Return as 3x3 transformation matrix


def compute_psnr(orig, dec):
    if orig.shape != dec.shape:
        dec = np.array(Image.fromarray(dec).resize((orig.shape[1], orig.shape[0]), Image.LANCZOS))
    mse = np.mean((orig.astype(float) - dec.astype(float)) ** 2)
    return 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')


def main():
    print("Loading PAL-CRT library...")
    lib_path = 'external/pal-crt/libpal_decode.so'
    lib = ctypes.CDLL(lib_path)

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int]*6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)  # saturation=30

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    print("Loading baseband...")
    baseband = np.fromfile('/tmp/pal_baseband.bin', dtype=np.int16)

    # Load original frames
    orig_frames = {}
    for f, fname in [(100, 'frame_0101.png'), (250, 'frame_0251.png')]:
        path = f'tools/comparison_results/original/{fname}'
        if os.path.exists(path):
            orig_frames[f] = np.array(Image.open(path))
            print(f"  Loaded original frame {f}")

    os.makedirs('/tmp/color_corrected', exist_ok=True)

    # Step 1: Decode reference frames with PAL-CRT
    print("\nDecoding reference frames...")
    decoded_frames = {}
    for fn in [100, 250]:
        frame_data = baseband[fn * SAMPLES_PER_FRAME:(fn+1) * SAMPLES_PER_FRAME]
        decoded = decode_with_palcrt(lib, frame_data, output_buffer)
        decoded_frames[fn] = decoded

        psnr = compute_psnr(orig_frames[fn], decoded)
        print(f"  Frame {fn}: PSNR before correction = {psnr:.2f} dB")
        Image.fromarray(decoded).save(f'/tmp/color_corrected/frame_{fn:04d}_raw.png')

    # Step 2: Find color correction matrix using frame 250 (more colorful)
    print("\nFinding color correction matrix...")

    # Try using both frames to find matrix
    dec_combined = np.vstack([decoded_frames[100][::4, ::4].reshape(-1, 3),
                              decoded_frames[250][::4, ::4].reshape(-1, 3)])
    orig_100_resized = np.array(Image.fromarray(orig_frames[100]).resize((720, 576), Image.LANCZOS))
    orig_250_resized = np.array(Image.fromarray(orig_frames[250]).resize((720, 576), Image.LANCZOS))
    orig_combined = np.vstack([orig_100_resized[::4, ::4].reshape(-1, 3),
                               orig_250_resized[::4, ::4].reshape(-1, 3)])

    matrix, _, _, _ = np.linalg.lstsq(dec_combined.astype(np.float32),
                                       orig_combined.astype(np.float32), rcond=None)
    color_matrix = matrix.T

    print(f"  Color matrix:\n{color_matrix}")

    # Step 3: Apply correction to decoded frames
    print("\nApplying color correction...")
    for fn in [100, 250]:
        corrected = apply_color_matrix(decoded_frames[fn], color_matrix)

        psnr = compute_psnr(orig_frames[fn], corrected)
        print(f"  Frame {fn}: PSNR after correction = {psnr:.2f} dB")

        Image.fromarray(corrected).save(f'/tmp/color_corrected/frame_{fn:04d}_corrected.png')

    lib.decode_cleanup()

    print("\nDone! Results in /tmp/color_corrected/")


if __name__ == '__main__':
    main()
