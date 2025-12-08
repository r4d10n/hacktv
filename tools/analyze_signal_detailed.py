#!/usr/bin/env python3
"""
Detailed analysis of hacktv PAL signal to understand actual encoding.
"""

import numpy as np
from scipy import signal as scipy_signal

SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)
SYNC_LEVEL = int(-0.30 * 32767)

# Burst location (in samples at 16MHz)
# Line duration at 64µs = 1024 samples
# H-sync ~4.7µs = ~75 samples
# Back porch starts ~5.6µs = ~90 samples
# Burst at ~5.6µs for ~2.25µs = samples 90-126
BURST_START = 85
BURST_END = 130


def analyze_line(line_data, line_num, frame_num):
    """Detailed analysis of a single line."""
    omega = 2 * np.pi * F_SC / SAMPLE_RATE
    t = np.arange(SAMPLES_PER_LINE)

    # Generate carriers
    sin_carrier = np.sin(t * omega)
    cos_carrier = np.cos(t * omega)

    # Extract burst region
    burst = line_data[BURST_START:BURST_END].astype(np.float64)
    burst_t = t[BURST_START:BURST_END]

    # Measure burst phase
    burst_sin = burst * np.sin(burst_t * omega)
    burst_cos = burst * np.cos(burst_t * omega)

    # Low-pass to get DC component
    burst_sin_mean = np.mean(burst_sin)
    burst_cos_mean = np.mean(burst_cos)
    burst_phase = np.arctan2(burst_sin_mean, burst_cos_mean) * 180 / np.pi
    burst_amp = np.sqrt(burst_sin_mean**2 + burst_cos_mean**2)

    return {
        'burst_phase': burst_phase,
        'burst_amp': burst_amp,
        'burst_sin': burst_sin_mean,
        'burst_cos': burst_cos_mean,
        'line_num': line_num,
        'pal_switch': -1 if (frame_num + line_num) & 1 else 1
    }


def measure_chroma_region(line_data, start, end, burst_phase, omega):
    """Measure chroma in a region using burst-locked demodulation."""
    t = np.arange(len(line_data))

    # Adjust carriers based on burst phase
    # Burst should be at 135° in PAL
    phase_correction = (135 - burst_phase) * np.pi / 180

    sin_carrier = np.sin(t * omega + phase_correction)
    cos_carrier = np.cos(t * omega + phase_correction)

    region = line_data[start:end].astype(np.float64)
    region_t = t[start:end]

    # Demodulate
    i_demod = region * cos_carrier[start:end]
    q_demod = region * sin_carrier[start:end]

    return np.mean(i_demod) * 2, np.mean(q_demod) * 2


def main():
    print("Detailed PAL Signal Analysis")
    print("=" * 60)

    # Load color bars baseband
    baseband_file = '/tmp/color_calibration/colorbars_pal.bin'
    baseband = np.fromfile(baseband_file, dtype=np.int16)

    frame_num = 15
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]

    omega = 2 * np.pi * F_SC / SAMPLE_RATE

    # Analyze burst phase across multiple lines
    print("\nBurst phase analysis (lines 100-110):")
    print("-" * 50)
    for line in range(100, 111):
        line_start = line * SAMPLES_PER_LINE
        line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]
        info = analyze_line(line_data, line, frame_num)
        print(f"  Line {line}: burst_phase={info['burst_phase']:+7.1f}°, "
              f"amp={info['burst_amp']:.0f}, pal_sw={info['pal_switch']:+d}")

    # Analyze color bars on a specific line
    print("\n\nColor bar analysis on line 200:")
    print("-" * 60)

    line_num = 200
    line_start = line_num * SAMPLES_PER_LINE
    line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

    info = analyze_line(line_data, line_num, frame_num)
    print(f"Burst phase: {info['burst_phase']:.1f}°")
    print(f"PAL switch: {info['pal_switch']:+d}")

    # Color bar regions
    ACTIVE_START = 210
    BAR_WIDTH = 89
    bar_names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']

    # Expected YUV (75% bars)
    expected = {
        'white':   (0.749, 0.0, 0.0),
        'yellow':  (0.664, -0.327, +0.075),
        'cyan':    (0.525, +0.110, -0.460),
        'green':   (0.440, -0.216, -0.386),
        'magenta': (0.309, +0.216, +0.386),
        'red':     (0.224, -0.110, +0.460),
        'blue':    (0.085, +0.327, -0.075),
        'black':   (0.0, 0.0, 0.0),
    }

    print("\nMeasured chroma (burst-locked):")
    print("-" * 60)

    measurements = []
    for i, name in enumerate(bar_names):
        bar_start = ACTIVE_START + i * BAR_WIDTH + BAR_WIDTH // 4
        bar_end = bar_start + BAR_WIDTH // 2

        # Measure Y
        y_region = line_data[bar_start:bar_end].astype(np.float64)
        y_mean = (np.mean(y_region) - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)

        # Measure chroma
        i_val, q_val = measure_chroma_region(line_data, bar_start, bar_end,
                                             info['burst_phase'], omega)

        exp_y, exp_u, exp_v = expected[name]

        # Calculate chroma amplitude and phase
        chroma_amp = np.sqrt(i_val**2 + q_val**2)
        chroma_phase = np.arctan2(q_val, i_val) * 180 / np.pi

        measurements.append({
            'name': name, 'y': y_mean, 'i': i_val, 'q': q_val,
            'amp': chroma_amp, 'phase': chroma_phase,
            'exp_u': exp_u, 'exp_v': exp_v
        })

        print(f"  {name:10s}: Y={y_mean:.3f}, I={i_val:+8.0f}, Q={q_val:+8.0f}, "
              f"amp={chroma_amp:6.0f}, phase={chroma_phase:+7.1f}°")

    # Analyze what the expected chroma should look like
    print("\n\nExpected chroma (if encoded as V*sin + U*cos):")
    print("-" * 60)
    for name in bar_names:
        exp_y, exp_u, exp_v = expected[name]
        # Scale to signal level (rough)
        scale = 20000  # Approximate chroma amplitude scale
        exp_i = exp_u * scale  # I ≈ U
        exp_q = exp_v * scale  # Q ≈ V
        exp_amp = np.sqrt(exp_i**2 + exp_q**2)
        exp_phase = np.arctan2(exp_q, exp_i) * 180 / np.pi if exp_amp > 0 else 0
        print(f"  {name:10s}: exp_U={exp_u:+.3f}, exp_V={exp_v:+.3f}, "
              f"amp={exp_amp:6.0f}, phase={exp_phase:+7.1f}°")

    # Try to find correlation between measured and expected
    print("\n\nCorrelation analysis:")
    print("-" * 60)

    # Build data for colored bars only
    meas_data = []
    exp_data = []
    for m in measurements:
        if m['name'] not in ['white', 'black']:  # Skip achromatic
            meas_data.append([m['i'], m['q']])
            exp_data.append([m['exp_u'], m['exp_v']])

    meas_data = np.array(meas_data)
    exp_data = np.array(exp_data)

    # Scale expected data
    exp_scaled = exp_data * 20000

    print("Measured I/Q vs scaled expected U/V (×20000):")
    for i, name in enumerate([n for n in bar_names if n not in ['white', 'black']]):
        print(f"  {name:10s}: meas=({meas_data[i,0]:+8.0f}, {meas_data[i,1]:+8.0f}) "
              f"exp=({exp_scaled[i,0]:+8.0f}, {exp_scaled[i,1]:+8.0f})")

    # Calculate angle between expected and measured for each color
    print("\n\nPhase relationship:")
    print("-" * 60)
    for i, name in enumerate([n for n in bar_names if n not in ['white', 'black']]):
        meas_phase = np.arctan2(meas_data[i,1], meas_data[i,0]) * 180 / np.pi
        exp_phase = np.arctan2(exp_scaled[i,1], exp_scaled[i,0]) * 180 / np.pi
        phase_diff = (meas_phase - exp_phase + 180) % 360 - 180
        meas_amp = np.sqrt(meas_data[i,0]**2 + meas_data[i,1]**2)
        exp_amp = np.sqrt(exp_scaled[i,0]**2 + exp_scaled[i,1]**2)
        amp_ratio = meas_amp / exp_amp if exp_amp > 0 else 0
        print(f"  {name:10s}: meas_phase={meas_phase:+7.1f}°, exp_phase={exp_phase:+7.1f}°, "
              f"diff={phase_diff:+6.1f}°, amp_ratio={amp_ratio:.2f}")


if __name__ == '__main__':
    main()
