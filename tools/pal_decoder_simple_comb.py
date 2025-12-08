#!/usr/bin/env python3
"""
Simple PAL comb decoder using line-to-line subtraction.

In PAL, the V phase alternates each line. So:
- Line N:   Y + U*cos(wt) + V*sin(wt)
- Line N+1: Y + U*cos(wt) - V*sin(wt)

Average: Y + U*cos(wt)  (V cancels)
Diff/2:  V*sin(wt)

This approach extracts chroma without needing burst phase detection.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os

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


class SimplePALComb:
    def __init__(self):
        self.phase_inc = 2 * np.pi * F_SC / SAMPLE_RATE
        t = np.arange(SAMPLES_PER_LINE)
        self.carrier_phase = t * self.phase_inc
        self.sin_carrier = np.sin(self.carrier_phase)
        self.cos_carrier = np.cos(self.carrier_phase)

        # Chroma bandpass
        low = (F_SC - 1.0e6) / (SAMPLE_RATE/2)
        high = (F_SC + 1.0e6) / (SAMPLE_RATE/2)
        self.chroma_bp = scipy_signal.firwin(65, [low, high], pass_zero=False)

        # Lowpass for demodulated chroma
        self.chroma_lp = scipy_signal.firwin(33, 1.0e6 / (SAMPLE_RATE/2))

        # Lowpass for luminance (notch out chroma would be better)
        self.luma_lp = scipy_signal.firwin(21, 3.5e6 / (SAMPLE_RATE/2))

    def decode_frame(self, frame_data, frame_num, phase_offset=0, saturation=2.0):
        height = ACTIVE_LINES
        width = ACTIVE_WIDTH

        # First, extract all lines
        all_lines = []
        for line_idx in range(height + 1):  # Need one extra for differencing
            actual_line = ACTIVE_LINES_START + line_idx
            if actual_line >= 625:
                break
            line_start = actual_line * SAMPLES_PER_LINE
            line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]
            if len(line_data) >= SAMPLES_PER_LINE:
                all_lines.append(line_data.astype(np.float64))
            else:
                all_lines.append(np.zeros(SAMPLES_PER_LINE))

        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        # Carrier for demodulation (with phase offset)
        phase_rad = phase_offset * np.pi / 180
        sin_c = np.sin(self.carrier_phase + phase_rad)
        cos_c = np.cos(self.carrier_phase + phase_rad)

        for line_idx in range(height):
            if line_idx >= len(all_lines) - 1:
                continue

            current = all_lines[line_idx]
            next_line = all_lines[line_idx + 1]

            actual_line = ACTIVE_LINES_START + line_idx
            pal_switch = -1 if (frame_num + actual_line) & 1 else 1

            # PAL comb filter
            # Average cancels V (since V alternates sign)
            # Difference extracts V
            y_comb = (current + next_line) / 2  # Y + U (V cancelled)
            chroma_diff = (current - next_line) / 2  # V only (phase alternates)

            # Bandpass filter the difference to get clean chroma
            v_chroma = scipy_signal.lfilter(self.chroma_bp, 1, chroma_diff)

            # For U, we need a different approach - bandpass the average
            u_chroma = scipy_signal.lfilter(self.chroma_bp, 1, y_comb)

            # Demodulate
            # V component (from difference)
            v_demod = v_chroma * sin_c * 2 * pal_switch
            v_filt = scipy_signal.lfilter(self.chroma_lp, 1, v_demod)

            # U component (from average after Y removal)
            u_demod = u_chroma * cos_c * 2
            u_filt = scipy_signal.lfilter(self.chroma_lp, 1, u_demod)

            # Luminance - lowpass the average
            y_raw = (y_comb - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_filt = scipy_signal.lfilter(self.luma_lp, 1, y_raw)

            # Scale and extract active region
            scale = 1.0 / (WHITE_LEVEL - BLACK_LEVEL)
            y = y_filt[ACTIVE_START:ACTIVE_START + width]
            u = u_filt[ACTIVE_START:ACTIVE_START + width] * scale * saturation
            v = v_filt[ACTIVE_START:ACTIVE_START + width] * scale * saturation

            # YUV to RGB
            r = np.clip(y + 1.140 * v, 0, 1)
            g = np.clip(y - 0.395 * u - 0.581 * v, 0, 1)
            b = np.clip(y + 2.032 * u, 0, 1)

            rgb[line_idx, :, 0] = (r * 255).astype(np.uint8)
            rgb[line_idx, :, 1] = (g * 255).astype(np.uint8)
            rgb[line_idx, :, 2] = (b * 255).astype(np.uint8)

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

    os.makedirs('/tmp/simple_comb', exist_ok=True)
    decoder = SimplePALComb()

    test_frames = [100, 250]
    phase_offsets = list(range(-180, 181, 30))

    print("\nTesting phase offsets with simple comb...")

    best_psnr = 0
    best_offset = 0

    for phase in phase_offsets:
        psnrs = []
        for fn in test_frames:
            frame_data = baseband[fn * SAMPLES_PER_FRAME:(fn+1) * SAMPLES_PER_FRAME]
            decoded = decoder.decode_frame(frame_data, fn, phase_offset=phase)

            Image.fromarray(decoded).save(f'/tmp/simple_comb/frame_{fn:04d}_phase{phase:+04d}.png')

            if fn in orig_frames:
                psnr = compute_psnr(orig_frames[fn], decoded)
                psnrs.append(psnr)

        if psnrs:
            avg = np.mean(psnrs)
            print(f"  Phase {phase:+4d}°: avg={avg:.2f} dB (f100={psnrs[0]:.2f}, f250={psnrs[1]:.2f})")
            if avg > best_psnr:
                best_psnr = avg
                best_offset = phase

    print(f"\nBest: phase={best_offset}° with PSNR={best_psnr:.2f} dB")


if __name__ == '__main__':
    main()
