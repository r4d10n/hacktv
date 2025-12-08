#!/usr/bin/env python3
"""
Analyze the burst signal in hacktv PAL baseband to understand phase relationships.
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


def main():
    print("Burst Signal Analysis")
    print("=" * 60)

    baseband_file = '/tmp/color_calibration/colorbars_pal.bin'
    baseband = np.fromfile(baseband_file, dtype=np.int16)

    # Get a frame
    frame_num = 15
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]

    # Analyze several lines
    print("\n1. Finding sync and burst positions...")

    # Look at line 100 (should be in active video with yellow bar)
    for line_num in [50, 100, 150, 200]:
        line_start = line_num * SAMPLES_PER_LINE
        line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

        # Find sync pulse (minimum value)
        sync_pos = np.argmin(line_data[:200])
        sync_val = line_data[sync_pos]

        # Find burst region (oscillation after sync)
        # Burst typically starts ~5.6us after sync start
        # At 16MHz, 5.6us = 90 samples
        burst_start = sync_pos + 70
        burst_end = burst_start + 50

        burst = line_data[burst_start:burst_end]
        burst_ac = burst - np.mean(burst)

        # Measure burst amplitude
        burst_pp = burst_ac.max() - burst_ac.min()

        # Generate carriers at burst position
        t = np.arange(burst_start, burst_end)
        phase = t * 2 * np.pi * F_SC / SAMPLE_RATE
        sin_b = np.sin(phase)
        cos_b = np.cos(phase)

        # Correlate to get I and Q
        i_burst = np.mean(burst_ac * cos_b) * 2
        q_burst = np.mean(burst_ac * sin_b) * 2

        burst_amp = np.sqrt(i_burst**2 + q_burst**2)
        burst_phase = np.arctan2(q_burst, i_burst) * 180 / np.pi

        # PAL switch for this line
        actual_line = line_num
        pal_switch = -1 if (frame_num + actual_line) & 1 else 1

        print(f"\n  Line {line_num}:")
        print(f"    Sync at sample {sync_pos}, value {sync_val:.0f}")
        print(f"    Burst region: {burst_start}-{burst_end}")
        print(f"    Burst p-p: {burst_pp:.0f}")
        print(f"    Burst I={i_burst:.0f}, Q={q_burst:.0f}")
        print(f"    Burst amplitude: {burst_amp:.0f}")
        print(f"    Burst phase: {burst_phase:.1f}°")
        print(f"    PAL switch: {pal_switch:+d}")

        # Expected burst for hacktv:
        # burst = 0.707*sin(wt)*pal - 0.707*cos(wt)
        # I = -0.707 * amplitude, Q = 0.707 * amplitude * pal
        expected_i = -0.707 * burst_amp
        expected_q = 0.707 * burst_amp * pal_switch
        expected_phase = np.arctan2(expected_q, expected_i) * 180 / np.pi
        print(f"    Expected phase (135° for pal=+1, -135° for pal=-1): {expected_phase:.1f}°")

    # Now analyze what happens across a full line
    print("\n\n2. Analyzing phase across line 100...")
    line_num = 100
    line_start = line_num * SAMPLES_PER_LINE
    line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

    # Bandpass filter to extract chroma
    low = 3.5e6 / (SAMPLE_RATE / 2)
    high = 5.4e6 / (SAMPLE_RATE / 2)
    bp = scipy_signal.firwin(65, [low, high], pass_zero=False)
    chroma = scipy_signal.lfilter(bp, 1, line_data)

    # Sample phase at different positions along the line
    positions = [100, 200, 300, 400, 500, 600, 700, 800, 900]
    print("\n  Chroma phase at different positions:")
    for pos in positions:
        window = 30
        chunk = chroma[pos:pos+window]

        t = np.arange(pos, pos+window)
        phase = t * 2 * np.pi * F_SC / SAMPLE_RATE
        sin_c = np.sin(phase)
        cos_c = np.cos(phase)

        i_comp = np.mean(chunk * cos_c) * 2
        q_comp = np.mean(chunk * sin_c) * 2

        amp = np.sqrt(i_comp**2 + q_comp**2)
        ph = np.arctan2(q_comp, i_comp) * 180 / np.pi

        print(f"    Pos {pos:4d}: amplitude={amp:6.0f}, phase={ph:+7.1f}°")

    # The key insight: phase rotates continuously across the line
    # because we have ~3.608 samples per carrier cycle
    print("\n3. Carrier phase drift analysis:")
    samples_per_cycle = SAMPLE_RATE / F_SC
    print(f"  Samples per carrier cycle: {samples_per_cycle:.3f}")
    phase_per_sample = 360 / samples_per_cycle
    print(f"  Phase rotation per sample: {phase_per_sample:.2f}°")
    phase_per_line = (SAMPLES_PER_LINE * 360 / samples_per_cycle) % 360
    print(f"  Phase rotation per line (mod 360°): {phase_per_line:.2f}°")


if __name__ == '__main__':
    main()
