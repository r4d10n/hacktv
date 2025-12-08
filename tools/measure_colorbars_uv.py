#!/usr/bin/env python3
"""
Empirically measure the U/V values for each color bar in the hacktv signal.
This will help us understand the actual encoding and derive correct decoding.
"""

import numpy as np
from scipy import signal as scipy_signal
import os

SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)

# Color bar positions (approximate sample ranges for each bar)
# 720 pixels active, 8 bars = 90 pixels each
# At 16MHz with ~715 active samples, each bar is ~89 samples
ACTIVE_START = 210
BAR_WIDTH = 89

# Expected YUV values for 75% color bars (normalized to 0-1)
# Y, U, V
EXPECTED_YUV = {
    'white':   (0.75, 0.0, 0.0),
    'yellow':  (0.664, -0.264, 0.375),
    'cyan':    (0.586, 0.264, -0.375),
    'green':   (0.500, 0.0, 0.0),  # Actually has U=-0.264+0.264=0, V=0.375-0.375=0 in 75%
    'magenta': (0.250, 0.0, 0.0),  # Similar
    'red':     (0.164, -0.264, 0.375),
    'blue':    (0.086, 0.264, -0.375),
    'black':   (0.0, 0.0, 0.0),
}

# Actually, let me compute correct YUV for 75% bars
# RGB to YUV: Y = 0.299R + 0.587G + 0.114B
#             U = 0.492(B-Y)
#             V = 0.877(R-Y)

def rgb_to_yuv(r, g, b):
    """Convert RGB (0-255) to YUV (Y:0-1, U/V: roughly -0.5 to 0.5)"""
    r, g, b = r/255, g/255, b/255
    y = 0.299*r + 0.587*g + 0.114*b
    u = 0.492 * (b - y)
    v = 0.877 * (r - y)
    return y, u, v


def main():
    print("Color Bar U/V Measurement")
    print("=" * 60)

    # First, compute expected YUV for 75% bars
    bars_rgb = [
        ('white', 191, 191, 191),
        ('yellow', 191, 191, 0),
        ('cyan', 0, 191, 191),
        ('green', 0, 191, 0),
        ('magenta', 191, 0, 191),
        ('red', 191, 0, 0),
        ('blue', 0, 0, 191),
        ('black', 0, 0, 0),
    ]

    print("\nExpected YUV values (75% bars):")
    expected_yuv = {}
    for name, r, g, b in bars_rgb:
        y, u, v = rgb_to_yuv(r, g, b)
        expected_yuv[name] = (y, u, v)
        print(f"  {name:10s}: Y={y:.3f}, U={u:+.3f}, V={v:+.3f}")

    # Load color bars baseband
    baseband_file = '/tmp/color_calibration/colorbars_pal.bin'
    baseband = np.fromfile(baseband_file, dtype=np.int16)

    frame_num = 15
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]

    # Prepare carriers and filters
    omega = 2 * np.pi * F_SC / SAMPLE_RATE
    t = np.arange(SAMPLES_PER_LINE)
    sin_carrier = np.sin(t * omega)
    cos_carrier = np.cos(t * omega)

    low = 3.5e6 / (SAMPLE_RATE / 2)
    high = 5.4e6 / (SAMPLE_RATE / 2)
    bp = scipy_signal.firwin(65, [low, high], pass_zero=False)
    lp = scipy_signal.firwin(33, 1.0e6 / (SAMPLE_RATE / 2))

    # Analyze a line in the middle of the frame
    print(f"\n\nMeasuring signal on line 200 (frame {frame_num}):")

    line_num = 200
    line_start = line_num * SAMPLES_PER_LINE
    line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

    pal_switch = -1 if (frame_num + line_num) & 1 else 1
    print(f"  PAL switch: {pal_switch:+d}")

    # Extract chroma
    chroma = scipy_signal.lfilter(bp, 1, line_data)

    # Demodulate with both carriers
    i_demod = chroma * cos_carrier * 2
    q_demod = chroma * sin_carrier * 2

    i_filt = scipy_signal.lfilter(lp, 1, i_demod)
    q_filt = scipy_signal.lfilter(lp, 1, q_demod)

    # Measure Y, I, Q for each color bar
    print("\n  Measured values (raw I/Q demodulation):")
    print("-" * 70)
    bar_names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']

    measured = []
    for i, name in enumerate(bar_names):
        bar_start = ACTIVE_START + i * BAR_WIDTH + BAR_WIDTH // 4
        bar_end = bar_start + BAR_WIDTH // 2

        y_region = line_data[bar_start:bar_end]
        i_region = i_filt[bar_start:bar_end]
        q_region = q_filt[bar_start:bar_end]

        y_mean = (np.mean(y_region) - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
        i_mean = np.mean(i_region)
        q_mean = np.mean(q_region)

        measured.append((name, y_mean, i_mean, q_mean))

        exp_y, exp_u, exp_v = expected_yuv[name]
        print(f"  {name:10s}: Y={y_mean:.3f} (exp {exp_y:.3f}), "
              f"I={i_mean:+8.0f}, Q={q_mean:+8.0f}")

    # Now try to find the transformation from (I,Q) to (U,V)
    # We have: I = a*U + b*V, Q = c*U + d*V
    # So: [I] = [a b] [U]
    #     [Q]   [c d] [V]
    # We can solve for [a,b,c,d] using least squares

    print("\n\nFinding I/Q to U/V transformation...")

    # Build matrices for least squares
    # For each color bar: [I, Q] = M @ [U, V]
    measured_iq = []
    expected_uv = []

    for name, y_meas, i_meas, q_meas in measured:
        if name not in ['white', 'black']:  # Skip achromatic
            exp_y, exp_u, exp_v = expected_yuv[name]
            measured_iq.append([i_meas, q_meas])
            expected_uv.append([exp_u * 10000, exp_v * 10000])  # Scale up for numerical stability

    measured_iq = np.array(measured_iq)
    expected_uv = np.array(expected_uv)

    # Solve: measured_iq = expected_uv @ M.T
    # M.T = pinv(expected_uv) @ measured_iq
    M_T, residuals, rank, s = np.linalg.lstsq(expected_uv, measured_iq, rcond=None)
    M = M_T.T

    print(f"\n  Transformation matrix (I,Q) = M @ (U,V):")
    print(f"    [{M[0,0]:+10.2f} {M[0,1]:+10.2f}]")
    print(f"    [{M[1,0]:+10.2f} {M[1,1]:+10.2f}]")

    # Inverse to get (U,V) from (I,Q)
    M_inv = np.linalg.inv(M)
    print(f"\n  Inverse (U,V) = M_inv @ (I,Q):")
    print(f"    [{M_inv[0,0]:+10.6f} {M_inv[0,1]:+10.6f}]")
    print(f"    [{M_inv[1,0]:+10.6f} {M_inv[1,1]:+10.6f}]")

    # Verify
    print("\n  Verification (using inverse transform):")
    print("-" * 70)
    for name, y_meas, i_meas, q_meas in measured:
        iq = np.array([i_meas, q_meas])
        uv_recovered = M_inv @ iq / 10000  # Unscale

        exp_y, exp_u, exp_v = expected_yuv[name]

        print(f"  {name:10s}: U={uv_recovered[0]:+.3f} (exp {exp_u:+.3f}), "
              f"V={uv_recovered[1]:+.3f} (exp {exp_v:+.3f})")


if __name__ == '__main__':
    main()
