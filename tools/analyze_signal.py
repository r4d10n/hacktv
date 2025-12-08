#!/usr/bin/env python3
"""
Analyze the PAL baseband signal to understand chroma levels and structure.
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

BURST_START = 88
BURST_WIDTH = 40
ACTIVE_START = 264


def main():
    print("Loading baseband...")
    baseband = np.fromfile('/tmp/pal_baseband.bin', dtype=np.int16)

    # Analyze frame 250 (orange sunset - should have strong chroma)
    frame_num = 250
    frame_start = frame_num * SAMPLES_PER_FRAME
    frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

    print(f"\nFrame {frame_num} analysis:")
    print(f"  Min value: {frame_data.min()}")
    print(f"  Max value: {frame_data.max()}")
    print(f"  Mean: {frame_data.mean():.1f}")
    print(f"  Expected sync: {SYNC_LEVEL}, black: {BLACK_LEVEL}, white: {WHITE_LEVEL}")

    # Analyze burst on several lines
    print("\n=== BURST ANALYSIS ===")
    t = np.arange(SAMPLES_PER_LINE)
    phase = t * 2 * np.pi * F_SC / SAMPLE_RATE
    sin_c = np.sin(phase)
    cos_c = np.cos(phase)

    for line_num in [100, 150, 200, 250, 300]:
        line_start = line_num * SAMPLES_PER_LINE
        line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

        burst = line_data[BURST_START:BURST_START + BURST_WIDTH]
        burst_ac = burst - np.mean(burst)

        # Correlate with carriers
        sin_burst = sin_c[BURST_START:BURST_START + BURST_WIDTH]
        cos_burst = cos_c[BURST_START:BURST_START + BURST_WIDTH]

        i_corr = np.mean(burst_ac * cos_burst) * 2
        q_corr = np.mean(burst_ac * sin_burst) * 2

        burst_amp = np.sqrt(i_corr**2 + q_corr**2)
        burst_phase = np.arctan2(q_corr, i_corr) * 180 / np.pi

        actual_line = line_num
        pal_switch = -1 if (frame_num + actual_line) & 1 else 1

        print(f"  Line {line_num}: amp={burst_amp:.0f}, phase={burst_phase:+.1f}°, pal={pal_switch:+d}")

    # Analyze chroma in active video
    print("\n=== CHROMA ANALYSIS (Line 200) ===")
    line_num = 200
    line_start = line_num * SAMPLES_PER_LINE
    line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

    actual_line = line_num
    pal_switch = -1 if (frame_num + actual_line) & 1 else 1

    # Bandpass to extract chroma
    low = (F_SC - 1.0e6) / (SAMPLE_RATE/2)
    high = (F_SC + 1.0e6) / (SAMPLE_RATE/2)
    bp = scipy_signal.firwin(65, [low, high], pass_zero=False)
    chroma = scipy_signal.lfilter(bp, 1, line_data)

    # Measure chroma amplitude in active region
    chroma_active = chroma[ACTIVE_START:ACTIVE_START + 500]
    chroma_rms = np.sqrt(np.mean(chroma_active**2))
    chroma_pp = chroma_active.max() - chroma_active.min()

    print(f"  Chroma RMS: {chroma_rms:.1f}")
    print(f"  Chroma peak-peak: {chroma_pp:.1f}")

    # Demodulate
    u_raw = chroma * cos_c * 2
    v_raw = chroma * sin_c * 2 * pal_switch

    lp = scipy_signal.firwin(33, 1.0e6 / (SAMPLE_RATE/2))
    u_filt = scipy_signal.lfilter(lp, 1, u_raw)
    v_filt = scipy_signal.lfilter(lp, 1, v_raw)

    u_active = u_filt[ACTIVE_START:ACTIVE_START + 500]
    v_active = v_filt[ACTIVE_START:ACTIVE_START + 500]

    print(f"\n  Demodulated U: min={u_active.min():.0f}, max={u_active.max():.0f}, mean={u_active.mean():.0f}")
    print(f"  Demodulated V: min={v_active.min():.0f}, max={v_active.max():.0f}, mean={v_active.mean():.0f}")

    # Expected for orange (in YUV):
    # Orange = high R, medium G, low B
    # Y = 0.299R + 0.587G + 0.114B
    # U = 0.492(B-Y) -> negative for orange
    # V = 0.877(R-Y) -> positive for orange
    print(f"\n  For orange: expect U<0, V>0")

    # Now compare with blue ocean (frame 100)
    print("\n=== CHROMA ANALYSIS (Frame 100, Line 200 - ocean) ===")
    frame_num = 100
    frame_start = frame_num * SAMPLES_PER_FRAME
    frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

    line_num = 200
    line_start = line_num * SAMPLES_PER_LINE
    line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

    actual_line = line_num
    pal_switch = -1 if (frame_num + actual_line) & 1 else 1

    chroma = scipy_signal.lfilter(bp, 1, line_data)

    u_raw = chroma * cos_c * 2
    v_raw = chroma * sin_c * 2 * pal_switch

    u_filt = scipy_signal.lfilter(lp, 1, u_raw)
    v_filt = scipy_signal.lfilter(lp, 1, v_raw)

    u_active = u_filt[ACTIVE_START:ACTIVE_START + 500]
    v_active = v_filt[ACTIVE_START:ACTIVE_START + 500]

    print(f"  Demodulated U: min={u_active.min():.0f}, max={u_active.max():.0f}, mean={u_active.mean():.0f}")
    print(f"  Demodulated V: min={v_active.min():.0f}, max={v_active.max():.0f}, mean={v_active.mean():.0f}")

    # Expected for cyan/blue ocean (in YUV):
    # Blue = low R, medium G, high B
    # U = 0.492(B-Y) -> positive for blue
    # V = 0.877(R-Y) -> negative for cyan
    print(f"\n  For cyan/blue: expect U>0, V<0")

    print("\n=== COMPARISON ===")
    print("If demodulated signs match expectations, color axes are correct.")
    print("If swapped, U/V axes need swapping.")
    print("If both wrong sign, phase is 180° off.")


if __name__ == '__main__':
    main()
