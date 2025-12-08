#!/usr/bin/env python3
"""
PAL decoder using burst to establish U/V axes per line.

The key insight: at 16MHz with 3.609 samples/cycle, the carrier phase
drifts ~270° per line. The burst gives us a reference vector from which
we can compute the U and V demodulation axes for each line.

hacktv encoding:
  Chroma = V*sin(wt)*pal + U*cos(wt)
  Burst = 0.707*sin(wt)*pal - 0.707*cos(wt) (at 135° from U axis)

When we measure burst with our carriers:
  I_burst = integral(burst * cos(wt)) ∝ -0.707 (cos component of burst)
  Q_burst = integral(burst * sin(wt)) ∝ +0.707*pal (sin component of burst)

The burst vector (I_burst, Q_burst) tells us where 135° is in our coordinate system.
From this we can derive where U (0°) and V (90°) axes are.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os

SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

SYNC_LEVEL = int(-0.30 * 32767)
BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)

# Timing
BURST_START = 74
BURST_END = 124
ACTIVE_START = 210
ACTIVE_END = 920

OUT_WIDTH = 702
OUT_HEIGHT = 576
FIRST_ACTIVE_LINE = 23


class PALDecoderBurstAxis:
    def __init__(self):
        self.omega = 2 * np.pi * F_SC / SAMPLE_RATE

        # Pre-compute carriers
        t = np.arange(SAMPLES_PER_LINE)
        self.phase = t * self.omega
        self.sin_carrier = np.sin(self.phase)
        self.cos_carrier = np.cos(self.phase)

        # Filters
        low = 3.5e6 / (SAMPLE_RATE / 2)
        high = 5.4e6 / (SAMPLE_RATE / 2)
        self.chroma_bp = scipy_signal.firwin(65, [low, high], pass_zero=False)
        self.uv_lp = scipy_signal.firwin(33, 1.3e6 / (SAMPLE_RATE / 2))
        self.y_lp = scipy_signal.firwin(21, 4.2e6 / (SAMPLE_RATE / 2))

    def decode_line(self, line_signal, pal_switch):
        sig = line_signal.astype(np.float64)

        # Measure burst
        burst = sig[BURST_START:BURST_END] - np.mean(sig[BURST_START:BURST_END])
        sin_b = self.sin_carrier[BURST_START:BURST_END]
        cos_b = self.cos_carrier[BURST_START:BURST_END]

        # Burst I and Q in our carrier coordinate system
        i_burst = np.sum(burst * cos_b) * 2 / len(burst)
        q_burst = np.sum(burst * sin_b) * 2 / len(burst)
        burst_amp = np.sqrt(i_burst**2 + q_burst**2)

        if burst_amp < 300:
            # No burst - grayscale
            y = (sig[ACTIVE_START:ACTIVE_END] - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_filt = scipy_signal.lfilter(self.y_lp[:11], 1, y)
            y_out = np.interp(np.linspace(0, len(y_filt)-1, OUT_WIDTH),
                              np.arange(len(y_filt)), y_filt)
            return y_out, np.zeros(OUT_WIDTH), np.zeros(OUT_WIDTH)

        # The burst is at 135° from U axis (or -135° = 225° for pal=-1)
        # burst_angle = atan2(q_burst, i_burst) is the angle of burst in our I/Q system
        # U_angle = burst_angle - 135° (for pal=+1) or burst_angle + 135° (for pal=-1)
        burst_angle = np.arctan2(q_burst, i_burst)

        if pal_switch > 0:
            u_angle = burst_angle - 135 * np.pi / 180
        else:
            u_angle = burst_angle + 135 * np.pi / 180

        # V is 90° ahead of U
        v_angle = u_angle + 90 * np.pi / 180

        # Extract chroma
        chroma = scipy_signal.lfilter(self.chroma_bp, 1, sig)

        # Demodulate in I/Q coordinates
        i_demod = chroma * self.cos_carrier * 2
        q_demod = chroma * self.sin_carrier * 2

        i_filt = scipy_signal.lfilter(self.uv_lp, 1, i_demod)
        q_filt = scipy_signal.lfilter(self.uv_lp, 1, q_demod)

        # Rotate I/Q to U/V coordinates
        # U = I*cos(u_angle) + Q*sin(u_angle)
        # V = -I*sin(u_angle) + Q*cos(u_angle) (V is 90° ahead)
        # But we want V multiplied by pal_switch for PAL delay line to work
        cos_u = np.cos(u_angle)
        sin_u = np.sin(u_angle)

        u_raw = i_filt * cos_u + q_filt * sin_u
        v_raw = (-i_filt * sin_u + q_filt * cos_u) * pal_switch

        # Normalize by burst amplitude
        uv_scale = 1.0 / (burst_amp * 0.707)  # burst amplitude is 0.707 of full chroma

        # Luminance
        y_raw = (sig - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
        y_filt = scipy_signal.lfilter(self.y_lp, 1, y_raw)

        # Extract active region
        y_active = y_filt[ACTIVE_START:ACTIVE_END]
        u_active = u_raw[ACTIVE_START:ACTIVE_END] * uv_scale
        v_active = v_raw[ACTIVE_START:ACTIVE_END] * uv_scale

        # Resample to output width
        x_in = np.arange(len(y_active))
        x_out = np.linspace(0, len(y_active)-1, OUT_WIDTH)

        y_out = np.interp(x_out, x_in, y_active)
        u_out = np.interp(x_out, x_in, u_active)
        v_out = np.interp(x_out, x_in, v_active)

        return y_out, u_out, v_out

    def decode_frame(self, frame_data, frame_num, saturation=1.0, use_comb=True):
        rgb = np.zeros((OUT_HEIGHT, OUT_WIDTH, 3), dtype=np.uint8)

        y_lines, u_lines, v_lines = [], [], []

        for line_idx in range(OUT_HEIGHT):
            actual_line = FIRST_ACTIVE_LINE + line_idx
            line_start = actual_line * SAMPLES_PER_LINE
            line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

            if len(line_data) < SAMPLES_PER_LINE:
                y_lines.append(np.zeros(OUT_WIDTH))
                u_lines.append(np.zeros(OUT_WIDTH))
                v_lines.append(np.zeros(OUT_WIDTH))
                continue

            pal_switch = -1 if (frame_num + actual_line) & 1 else 1
            y, u, v = self.decode_line(line_data, pal_switch)

            y_lines.append(y)
            u_lines.append(u)
            v_lines.append(v)

        # Apply comb filter and convert to RGB
        for line_idx in range(OUT_HEIGHT):
            y = y_lines[line_idx]

            if use_comb and line_idx > 0:
                u = (u_lines[line_idx] + u_lines[line_idx - 1]) / 2
                v = (v_lines[line_idx] + v_lines[line_idx - 1]) / 2
            else:
                u = u_lines[line_idx]
                v = v_lines[line_idx]

            u *= saturation
            v *= saturation

            # YUV to RGB (PAL/EBU)
            r = np.clip(y + 1.140 * v, 0, 1)
            g = np.clip(y - 0.396 * u - 0.581 * v, 0, 1)
            b = np.clip(y + 2.029 * u, 0, 1)

            rgb[line_idx, :, 0] = (r * 255).astype(np.uint8)
            rgb[line_idx, :, 1] = (g * 255).astype(np.uint8)
            rgb[line_idx, :, 2] = (b * 255).astype(np.uint8)

        return rgb


def main():
    print("Burst-Axis PAL Decoder Test")
    print("=" * 60)

    baseband_file = '/tmp/color_calibration/colorbars_pal.bin'
    if not os.path.exists(baseband_file):
        print("Run analyze_color_transform.py first!")
        return

    baseband = np.fromfile(baseband_file, dtype=np.int16)
    os.makedirs('/tmp/burst_axis_test', exist_ok=True)

    decoder = PALDecoderBurstAxis()

    frame_num = 15
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]

    print("\nTesting saturation levels...")
    for sat in [0.5, 1.0, 1.5, 2.0]:
        decoded = decoder.decode_frame(frame_data, frame_num, saturation=sat)
        Image.fromarray(decoded).save(f'/tmp/burst_axis_test/colorbars_sat{sat:.1f}.png')
        print(f"  Saved colorbars_sat{sat:.1f}.png")

    # Analyze colors at sat=1.0
    decoded = decoder.decode_frame(frame_data, frame_num, saturation=1.0)

    h, w = decoded.shape[:2]
    bar_width = w // 8
    y_start, y_end = h // 4, 3 * h // 4

    expected = [
        ('white', (191, 191, 191)),
        ('yellow', (191, 191, 0)),
        ('cyan', (0, 191, 191)),
        ('green', (0, 191, 0)),
        ('magenta', (191, 0, 191)),
        ('red', (191, 0, 0)),
        ('blue', (0, 0, 191)),
        ('black', (0, 0, 0)),
    ]

    print("\nColor comparison (sat=1.0):")
    print("-" * 60)
    total_error = 0
    for i, (name, exp) in enumerate(expected):
        x_center = i * bar_width + bar_width // 2
        x_start = x_center - bar_width // 4
        x_end = x_center + bar_width // 4
        region = decoded[y_start:y_end, x_start:x_end]
        meas = np.mean(region, axis=(0, 1))
        error = np.sqrt(np.sum((np.array(exp) - meas) ** 2))
        total_error += error
        print(f"  {name:10s}: exp ({exp[0]:3d},{exp[1]:3d},{exp[2]:3d}) → "
              f"dec ({meas[0]:5.1f},{meas[1]:5.1f},{meas[2]:5.1f})  err={error:.1f}")

    print("-" * 60)
    print(f"Mean error: {total_error / 8:.1f}")


if __name__ == '__main__':
    main()
