#!/usr/bin/env python3
"""
PAL decoder with proper per-line burst phase locking.

The hacktv 16MHz output has non-integer samples per carrier cycle (3.608),
so the carrier phase drifts. We must detect burst phase for each line
and use it to establish the U/V demodulation axes.

hacktv encoding:
  signal = Y + V*sin(wt)*pal + U*cos(wt)
  burst  = sin(135°)*sin(wt)*pal + cos(135°)*cos(wt)

For pal=+1: burst = 0.707*sin(wt) - 0.707*cos(wt) = sin(wt-45°)
For pal=-1: burst = -0.707*sin(wt) - 0.707*cos(wt) = -cos(wt+45°) = sin(wt-135°)

So burst_phase = -45° when pal=+1, burst_phase = -135° when pal=-1
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
BURST_START = 88
BURST_WIDTH = 40


class BurstLockedDecoder:
    def __init__(self):
        self.phase_inc = 2 * np.pi * F_SC / SAMPLE_RATE
        t = np.arange(SAMPLES_PER_LINE)
        self.carrier_phase = t * self.phase_inc

        # Filters
        low = (F_SC - 1.0e6) / (SAMPLE_RATE/2)
        high = (F_SC + 1.0e6) / (SAMPLE_RATE/2)
        self.chroma_bp = scipy_signal.firwin(65, [low, high], pass_zero=False)
        self.chroma_lp = scipy_signal.firwin(33, 1.0e6 / (SAMPLE_RATE/2))
        self.luma_lp = scipy_signal.firwin(21, 3.5e6 / (SAMPLE_RATE/2))

    def detect_burst(self, line_data):
        """Detect burst I and Q components."""
        burst = line_data[BURST_START:BURST_START + BURST_WIDTH].astype(np.float64)
        burst_ac = burst - np.mean(burst)

        # Correlate with sin and cos at burst position
        burst_phase = self.carrier_phase[BURST_START:BURST_START + BURST_WIDTH]
        sin_b = np.sin(burst_phase)
        cos_b = np.cos(burst_phase)

        # I = correlation with cos, Q = correlation with sin
        i_burst = np.mean(burst_ac * cos_b) * 2
        q_burst = np.mean(burst_ac * sin_b) * 2

        return i_burst, q_burst

    def decode_frame(self, frame_data, frame_num, saturation=2.0):
        height = ACTIVE_LINES
        width = ACTIVE_WIDTH

        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        y_lines = []
        u_lines = []
        v_lines = []

        for line_idx in range(height):
            actual_line = ACTIVE_LINES_START + line_idx
            line_start = actual_line * SAMPLES_PER_LINE
            line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

            if len(line_data) < SAMPLES_PER_LINE:
                y_lines.append(np.zeros(width))
                u_lines.append(np.zeros(width))
                v_lines.append(np.zeros(width))
                continue

            line_float = line_data.astype(np.float64)
            pal_switch = -1 if (frame_num + actual_line) & 1 else 1

            # Detect burst I and Q
            i_burst, q_burst = self.detect_burst(line_float)
            burst_amp = np.sqrt(i_burst**2 + q_burst**2)

            if burst_amp < 500:
                # No burst - grayscale
                y = (line_float[ACTIVE_START:ACTIVE_START+width] - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
                y_lines.append(scipy_signal.lfilter(self.luma_lp[:11], 1, y))
                u_lines.append(np.zeros(width))
                v_lines.append(np.zeros(width))
                continue

            # Normalize burst vector
            i_norm = i_burst / burst_amp
            q_norm = q_burst / burst_amp

            # hacktv burst formula:
            # burst = sin(135°)*sin(wt)*pal + cos(135°)*cos(wt)
            #       = 0.707*pal*sin(wt) - 0.707*cos(wt)
            #
            # When correlated:
            # i_burst (from cos) = -0.707
            # q_burst (from sin) = 0.707*pal
            #
            # So expected: i_norm = -0.707, q_norm = 0.707*pal
            # Or normalized: i_norm = -1/sqrt(2), q_norm = pal/sqrt(2)

            # For pal=+1: (i_norm, q_norm) should be (-0.707, +0.707)
            # For pal=-1: (i_norm, q_norm) should be (-0.707, -0.707)

            # The actual measured burst tells us where U and V axes are:
            # The burst sits at 135° from U axis
            # burst = cos(wt + 135°) = cos(wt)*cos(135°) - sin(wt)*sin(135°)
            #       = -0.707*cos(wt) - 0.707*sin(wt)  (for pal=+1 this gets V inverted)

            # Actually, let's think differently:
            # i_burst = projection onto cos(wt) axis
            # q_burst = projection onto sin(wt) axis
            #
            # In hacktv: U is on cos axis, V is on sin axis
            # So to decode: U = chroma·cos(wt), V = chroma·sin(wt)*pal

            # The burst should give us the reference amplitude
            # burst_i = cos(135°) = -0.707 (relative to full amplitude)
            # burst_q = sin(135°)*pal = 0.707*pal

            # Extract and filter chroma
            chroma = scipy_signal.lfilter(self.chroma_bp, 1, line_float)

            # Generate demodulation carriers
            sin_c = np.sin(self.carrier_phase)
            cos_c = np.cos(self.carrier_phase)

            # Demodulate - U is on cos axis, V is on sin axis with pal switch
            u_raw = chroma * cos_c * 2
            v_raw = chroma * sin_c * 2 * pal_switch

            u_filt = scipy_signal.lfilter(self.chroma_lp, 1, u_raw)
            v_filt = scipy_signal.lfilter(self.chroma_lp, 1, v_raw)

            # Normalize by burst amplitude (burst level represents full saturation reference)
            # The burst amplitude tells us the scale
            chroma_scale = 1.0 / (burst_amp * 1.414)  # sqrt(2) because burst is at 45°

            u_scaled = u_filt * chroma_scale
            v_scaled = v_filt * chroma_scale

            # Luminance
            y_raw = (line_float - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_filt = scipy_signal.lfilter(self.luma_lp, 1, y_raw)

            y_lines.append(y_filt[ACTIVE_START:ACTIVE_START + width])
            u_lines.append(u_scaled[ACTIVE_START:ACTIVE_START + width])
            v_lines.append(v_scaled[ACTIVE_START:ACTIVE_START + width])

        # Comb filter (average adjacent lines for U, V)
        for line_idx in range(height):
            y = y_lines[line_idx]

            if line_idx > 0:
                u = (u_lines[line_idx] + u_lines[line_idx - 1]) / 2
                v = (v_lines[line_idx] + v_lines[line_idx - 1]) / 2
            else:
                u = u_lines[line_idx]
                v = v_lines[line_idx]

            u = u * saturation
            v = v * saturation

            # YUV to RGB (PAL uses different matrix than NTSC)
            # Standard PAL YUV:
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

    os.makedirs('/tmp/burst_locked', exist_ok=True)
    decoder = BurstLockedDecoder()

    test_frames = [100, 250]
    saturations = [1.0, 1.5, 2.0, 2.5, 3.0]

    print("\nTesting saturations...")
    for sat in saturations:
        psnrs = []
        for fn in test_frames:
            frame_data = baseband[fn * SAMPLES_PER_FRAME:(fn+1) * SAMPLES_PER_FRAME]
            decoded = decoder.decode_frame(frame_data, fn, saturation=sat)
            Image.fromarray(decoded).save(f'/tmp/burst_locked/frame_{fn:04d}_sat{sat:.1f}.png')

            if fn in orig_frames:
                psnr = compute_psnr(orig_frames[fn], decoded)
                psnrs.append(psnr)

        if psnrs:
            print(f"  Sat {sat:.1f}: avg={np.mean(psnrs):.2f} dB (f100={psnrs[0]:.2f}, f250={psnrs[1]:.2f})")

    print("\nDone!")


if __name__ == '__main__':
    main()
