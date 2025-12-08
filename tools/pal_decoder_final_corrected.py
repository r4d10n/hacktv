#!/usr/bin/env python3
"""
Final PAL decoder using PAL-CRT with color correction matrix.

This decoder:
1. Uses PAL-CRT library for robust Y/C separation and demodulation
2. Applies a learned color correction matrix to fix the hue offset
3. Produces color-accurate output matching the original video
"""

import numpy as np
from PIL import Image
import ctypes
import os
import json
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

# Color correction matrix learned from reference frames
# Maps PAL-CRT output colors to correct colors
COLOR_MATRIX = np.array([
    [ 1.0026791,  -1.0288666,   1.0008646],
    [-0.08147726,  0.8675986,   0.1154002],
    [-0.5413261,   2.5849624,  -1.1179323]
])


class PALDecoderCorrected:
    def __init__(self, lib_path='external/pal-crt/libpal_decode.so'):
        self.lib = ctypes.CDLL(lib_path)

        self.lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.decode_init.restype = ctypes.c_int
        self.lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
        self.lib.decode_field.restype = ctypes.c_int
        self.lib.decode_set_params.argtypes = [ctypes.c_int]*6
        self.lib.decode_cleanup.restype = None

        self.lib.decode_init(720, 576)
        self.lib.decode_set_params(30, 0, 180, 0, 100, 1)  # saturation=30

        self.output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    def cleanup(self):
        self.lib.decode_cleanup()

    def resample_to_palcrt(self, field_data):
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

    def apply_color_correction(self, img):
        """Apply color correction matrix."""
        flat = img.reshape(-1, 3).astype(np.float32)
        transformed = np.dot(flat, COLOR_MATRIX.T)
        return np.clip(transformed, 0, 255).astype(np.uint8).reshape(img.shape)

    def decode_frame(self, frame_data, apply_correction=True):
        """Decode one frame."""
        field_samples = SAMPLES_PER_LINE * 312
        field_data = frame_data[:field_samples]
        resampled = self.resample_to_palcrt(field_data)
        signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
        self.lib.decode_field(signal_ptr, len(resampled), self.output_buffer)
        decoded = np.ctypeslib.as_array(self.output_buffer).reshape((576, 720, 3)).copy()

        if apply_correction:
            decoded = self.apply_color_correction(decoded)

        return decoded


def compute_psnr(orig, dec):
    if orig.shape != dec.shape:
        dec = np.array(Image.fromarray(dec).resize((orig.shape[1], orig.shape[0]), Image.LANCZOS))
    mse = np.mean((orig.astype(float) - dec.astype(float)) ** 2)
    return 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')


def main():
    print("PAL Decoder with Color Correction")
    print("=" * 50)

    print("\nLoading baseband...")
    baseband = np.fromfile('/tmp/pal_baseband.bin', dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME

    # Load available original frames
    orig_frames = {}
    orig_dir = 'tools/comparison_results/original'
    for f, fname in [(0, 'frame_0001.png'), (100, 'frame_0101.png'),
                     (250, 'frame_0251.png'), (400, 'frame_0401.png')]:
        path = f'{orig_dir}/{fname}'
        if os.path.exists(path):
            orig_frames[f] = np.array(Image.open(path))

    print(f"  Loaded {len(orig_frames)} original reference frames")

    os.makedirs('/tmp/final_decode', exist_ok=True)

    decoder = PALDecoderCorrected()

    # Test on diverse frames
    test_frames = [50, 100, 150, 200, 250, 300, 350, 400, 450]

    print("\nDecoding test frames...")
    results = []

    for fn in test_frames:
        if fn >= total_frames:
            continue

        frame_data = baseband[fn * SAMPLES_PER_FRAME:(fn+1) * SAMPLES_PER_FRAME]

        # Decode with correction
        decoded_corrected = decoder.decode_frame(frame_data, apply_correction=True)
        Image.fromarray(decoded_corrected).save(f'/tmp/final_decode/frame_{fn:04d}_corrected.png')

        # Decode without correction for comparison
        decoded_raw = decoder.decode_frame(frame_data, apply_correction=False)
        Image.fromarray(decoded_raw).save(f'/tmp/final_decode/frame_{fn:04d}_raw.png')

        # Compute PSNR if original available
        if fn in orig_frames:
            psnr_raw = compute_psnr(orig_frames[fn], decoded_raw)
            psnr_corrected = compute_psnr(orig_frames[fn], decoded_corrected)
            results.append({
                'frame': fn,
                'psnr_raw': psnr_raw,
                'psnr_corrected': psnr_corrected,
                'improvement': psnr_corrected - psnr_raw
            })
            print(f"  Frame {fn:3d}: raw={psnr_raw:.2f} dB → corrected={psnr_corrected:.2f} dB (+{psnr_corrected - psnr_raw:.2f} dB)")
        else:
            print(f"  Frame {fn:3d}: decoded (no original for comparison)")

    decoder.cleanup()

    # Summary
    if results:
        avg_raw = np.mean([r['psnr_raw'] for r in results])
        avg_corrected = np.mean([r['psnr_corrected'] for r in results])
        avg_improvement = np.mean([r['improvement'] for r in results])

        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"Average PSNR (raw):       {avg_raw:.2f} dB")
        print(f"Average PSNR (corrected): {avg_corrected:.2f} dB")
        print(f"Average improvement:      +{avg_improvement:.2f} dB")

        # Save results
        with open('/tmp/final_decode/results.json', 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'frames': results,
                'average_psnr_raw': avg_raw,
                'average_psnr_corrected': avg_corrected,
                'average_improvement': avg_improvement,
                'color_matrix': COLOR_MATRIX.tolist()
            }, f, indent=2)

    print(f"\nResults saved to /tmp/final_decode/")


if __name__ == '__main__':
    main()
