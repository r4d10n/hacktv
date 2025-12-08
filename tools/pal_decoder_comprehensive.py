#!/usr/bin/env python3
"""
Comprehensive PAL decoder test - combine phase offsets with U/V manipulations.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os
from itertools import product

SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)

ACTIVE_START = 264
ACTIVE_WIDTH = 702
ACTIVE_LINES_START = 23
ACTIVE_LINES = 576
BURST_START = 88
BURST_WIDTH = 40


class PALDecoder:
    def __init__(self):
        self.phase_inc = 2 * np.pi * F_SC / SAMPLE_RATE
        t = np.arange(SAMPLES_PER_LINE)
        self.carrier_phase = t * self.phase_inc
        self.sin_carrier = np.sin(self.carrier_phase)
        self.cos_carrier = np.cos(self.carrier_phase)

        # Filters
        low = (F_SC - 0.65e6) / (SAMPLE_RATE/2)
        high = (F_SC + 0.65e6) / (SAMPLE_RATE/2)
        self.chroma_bp = scipy_signal.firwin(65, [low, high], pass_zero=False)
        self.chroma_lp = scipy_signal.firwin(33, 1.3e6 / (SAMPLE_RATE/2))
        self.luma_lp = scipy_signal.firwin(17, 4.0e6 / (SAMPLE_RATE/2))

    def detect_burst(self, line_signal):
        burst = line_signal[BURST_START:BURST_START + BURST_WIDTH].astype(np.float64)
        burst = burst - np.mean(burst)
        sin_b = self.sin_carrier[BURST_START:BURST_START + BURST_WIDTH]
        cos_b = self.cos_carrier[BURST_START:BURST_START + BURST_WIDTH]
        i = np.sum(burst * cos_b) * 2 / BURST_WIDTH
        q = np.sum(burst * sin_b) * 2 / BURST_WIDTH
        return np.arctan2(q, i), np.sqrt(i**2 + q**2)

    def decode_frame(self, frame_data, frame_num, phase_offset=0, swap_uv=False,
                     neg_u=False, neg_v=False, saturation=1.5):
        height = ACTIVE_LINES
        width = ACTIVE_WIDTH

        y_lines, u_lines, v_lines = [], [], []

        for line_idx in range(height):
            actual_line = ACTIVE_LINES_START + line_idx
            line_start = actual_line * SAMPLES_PER_LINE
            line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

            if len(line_data) < SAMPLES_PER_LINE:
                y_lines.append(np.zeros(width))
                u_lines.append(np.zeros(width))
                v_lines.append(np.zeros(width))
                continue

            pal_switch = -1 if (frame_num + actual_line) & 1 else 1
            burst_phase, burst_amp = self.detect_burst(line_data)

            sig = line_data.astype(np.float64)

            # Phase correction with offset
            burst_ref = (135 + phase_offset) * np.pi / 180
            phase_corr = burst_phase + burst_ref

            sin_c = np.sin(self.carrier_phase - phase_corr)
            cos_c = np.cos(self.carrier_phase - phase_corr)

            # Extract and demodulate chroma
            chroma = scipy_signal.lfilter(self.chroma_bp, 1, sig)

            u_raw = chroma * cos_c * 2
            v_raw = chroma * sin_c * 2 * pal_switch

            u_filt = scipy_signal.lfilter(self.chroma_lp, 1, u_raw)
            v_filt = scipy_signal.lfilter(self.chroma_lp, 1, v_raw)

            # Apply modifications
            if swap_uv:
                u_filt, v_filt = v_filt, u_filt
            if neg_u:
                u_filt = -u_filt
            if neg_v:
                v_filt = -v_filt

            # Luminance
            y_raw = (sig - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_filt = scipy_signal.lfilter(self.luma_lp, 1, y_raw)

            scale = 1.0 / (WHITE_LEVEL - BLACK_LEVEL)

            y_lines.append(y_filt[ACTIVE_START:ACTIVE_START + width])
            u_lines.append(u_filt[ACTIVE_START:ACTIVE_START + width] * scale)
            v_lines.append(v_filt[ACTIVE_START:ACTIVE_START + width] * scale)

        # Comb filter and RGB conversion
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        for i in range(height):
            y = y_lines[i]
            if i > 0:
                u = (u_lines[i] + u_lines[i-1]) / 2
                v = (v_lines[i] + v_lines[i-1]) / 2
            else:
                u, v = u_lines[i], v_lines[i]

            u *= saturation
            v *= saturation

            # YUV to RGB
            r = np.clip(y + 1.140 * v, 0, 1)
            g = np.clip(y - 0.395 * u - 0.581 * v, 0, 1)
            b = np.clip(y + 2.032 * u, 0, 1)

            rgb[i, :, 0] = (r * 255).astype(np.uint8)
            rgb[i, :, 1] = (g * 255).astype(np.uint8)
            rgb[i, :, 2] = (b * 255).astype(np.uint8)

        return rgb


def compute_psnr(orig, dec):
    if orig.shape != dec.shape:
        dec = np.array(Image.fromarray(dec).resize((orig.shape[1], orig.shape[0]), Image.LANCZOS))
    mse = np.mean((orig.astype(float) - dec.astype(float)) ** 2)
    return 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')


def main():
    print("Loading data...")
    baseband = np.fromfile('/tmp/pal_baseband.bin', dtype=np.int16)

    orig_frames = {}
    for f, fname in [(100, 'frame_0101.png'), (250, 'frame_0251.png')]:
        path = f'tools/comparison_results/original/{fname}'
        if os.path.exists(path):
            orig_frames[f] = np.array(Image.open(path))

    os.makedirs('/tmp/comprehensive', exist_ok=True)
    decoder = PALDecoder()

    # Test combinations
    phase_offsets = [-90, -60, -45, -30, 0, 30, 45, 60, 90]
    uv_options = [
        (False, False, False, "normal"),
        (True, False, False, "swap"),
        (False, True, False, "neg_u"),
        (False, False, True, "neg_v"),
        (True, True, False, "swap_neg_u"),
        (True, False, True, "swap_neg_v"),
    ]

    test_frames = [100, 250]

    print("\nTesting combinations...")
    results = []

    for phase in phase_offsets:
        for swap, neg_u, neg_v, uv_name in uv_options:
            psnrs = []
            for fn in test_frames:
                frame_data = baseband[fn * SAMPLES_PER_FRAME:(fn+1) * SAMPLES_PER_FRAME]
                decoded = decoder.decode_frame(frame_data, fn, phase, swap, neg_u, neg_v, 1.5)

                if fn in orig_frames:
                    psnr = compute_psnr(orig_frames[fn], decoded)
                    psnrs.append(psnr)

            if psnrs:
                avg = np.mean(psnrs)
                results.append((avg, phase, uv_name, psnrs))

    # Sort by PSNR
    results.sort(reverse=True)

    print("\nTop 10 combinations:")
    for i, (avg, phase, uv_name, psnrs) in enumerate(results[:10]):
        print(f"{i+1}. Phase {phase:+3d}° + {uv_name:12s}: avg={avg:.2f} dB (f100={psnrs[0]:.2f}, f250={psnrs[1]:.2f})")

    # Save best result frames
    best_avg, best_phase, best_uv, _ = results[0]
    print(f"\nSaving best combination: phase={best_phase}°, uv={best_uv}")

    swap = 'swap' in best_uv
    neg_u = 'neg_u' in best_uv
    neg_v = 'neg_v' in best_uv

    for fn in test_frames:
        frame_data = baseband[fn * SAMPLES_PER_FRAME:(fn+1) * SAMPLES_PER_FRAME]
        decoded = decoder.decode_frame(frame_data, fn, best_phase, swap, neg_u, neg_v, 1.5)
        Image.fromarray(decoded).save(f'/tmp/comprehensive/best_frame_{fn:04d}.png')

    print("Done!")


if __name__ == '__main__':
    main()
