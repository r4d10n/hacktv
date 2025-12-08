#!/usr/bin/env python3
"""
Fixed PAL decoder for hacktv 16MHz baseband.
Properly handles burst phase detection and U/V demodulation.

hacktv encoding formula:
  Composite = Y + V*sin(wt)*pal_switch + U*cos(wt)
  where pal_switch = -1 if (frame + line) & 1 else +1

Burst phase = 135° means burst = cos(wt - 135°)
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os
import json
from datetime import datetime

# hacktv constants
SAMPLE_RATE = 16e6  # 16 MHz
F_SC = 4433618.75   # PAL subcarrier frequency
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * LINES_PER_FRAME

# Signal levels (int16)
SYNC_LEVEL = int(-0.30 * 32767)  # -9830
BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)  # 22937

# Active video region
ACTIVE_START = 264
ACTIVE_WIDTH = 702
ACTIVE_LINES_START = 23
ACTIVE_LINES = 576

# Burst position
BURST_START = 88
BURST_WIDTH = 40


def create_bandpass_filter(center_freq, bandwidth, sample_rate, numtaps=65):
    """Create bandpass filter for chroma extraction."""
    low = (center_freq - bandwidth/2) / (sample_rate/2)
    high = (center_freq + bandwidth/2) / (sample_rate/2)
    return scipy_signal.firwin(numtaps, [low, high], pass_zero=False)


def create_lowpass_filter(cutoff, sample_rate, numtaps=33):
    """Create lowpass filter for demodulated chroma."""
    return scipy_signal.firwin(numtaps, cutoff / (sample_rate/2))


class PALDecoder:
    def __init__(self):
        # Phase increment per sample
        self.phase_inc = 2 * np.pi * F_SC / SAMPLE_RATE

        # Pre-generate carrier for one line
        t = np.arange(SAMPLES_PER_LINE)
        self.carrier_phase = t * self.phase_inc
        self.sin_carrier = np.sin(self.carrier_phase)
        self.cos_carrier = np.cos(self.carrier_phase)

        # Bandpass filter to extract chroma (around 4.43 MHz, ~1.3 MHz bandwidth)
        self.chroma_bp = create_bandpass_filter(F_SC, 1.3e6, SAMPLE_RATE, numtaps=65)

        # Lowpass filter for demodulated U, V (~1.3 MHz cutoff)
        self.chroma_lp = create_lowpass_filter(1.3e6, SAMPLE_RATE, numtaps=33)

        # Lowpass filter for luminance
        self.luma_lp = create_lowpass_filter(5e6, SAMPLE_RATE, numtaps=17)

    def detect_burst(self, line_signal):
        """Detect burst phase and amplitude."""
        burst_region = line_signal[BURST_START:BURST_START + BURST_WIDTH].astype(np.float64)
        burst_region = burst_region - np.mean(burst_region)  # Remove DC

        sin_burst = self.sin_carrier[BURST_START:BURST_START + BURST_WIDTH]
        cos_burst = self.cos_carrier[BURST_START:BURST_START + BURST_WIDTH]

        # Correlate with reference carriers
        i_corr = np.sum(burst_region * cos_burst) * 2 / BURST_WIDTH
        q_corr = np.sum(burst_region * sin_burst) * 2 / BURST_WIDTH

        amplitude = np.sqrt(i_corr**2 + q_corr**2)
        phase = np.arctan2(q_corr, i_corr)

        return phase, amplitude, i_corr, q_corr

    def decode_line(self, line_signal, pal_switch, burst_phase):
        """Decode one line with proper phase-locked demodulation."""
        sig = line_signal.astype(np.float64)

        # hacktv burst is at 135° = cos(135°)*cos(wt) + sin(135°)*sin(wt)
        # = -0.707*cos(wt) + 0.707*sin(wt) = cos(wt - 135°)
        # So burst_phase detected should be around -135° = -2.356 rad or +225° = 3.927 rad
        burst_ref = 135 * np.pi / 180  # Expected burst phase

        # Phase correction to align with hacktv's reference
        # The detected burst phase tells us where cos(wt - 135°) is
        # We need carriers aligned with hacktv's U (cos) and V (sin) axes
        phase_correction = burst_phase + burst_ref  # Align to 0°

        # Generate phase-corrected carriers
        corrected_phase = self.carrier_phase - phase_correction
        sin_corr = np.sin(corrected_phase)
        cos_corr = np.cos(corrected_phase)

        # Extract chroma by bandpass filtering
        chroma = scipy_signal.lfilter(self.chroma_bp, 1, sig)

        # Demodulate U and V
        # hacktv encodes: V*sin(wt)*pal + U*cos(wt)
        # Demodulate: multiply by cos gives U, multiply by sin*pal gives V
        u_demod = chroma * cos_corr * 2
        v_demod = chroma * sin_corr * 2 * pal_switch

        # Lowpass filter U and V
        u_filt = scipy_signal.lfilter(self.chroma_lp, 1, u_demod)
        v_filt = scipy_signal.lfilter(self.chroma_lp, 1, v_demod)

        # Extract luminance
        # Simple approach: lowpass the signal
        y_raw = (sig - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
        y_filt = scipy_signal.lfilter(self.luma_lp, 1, y_raw)

        # Scale U, V appropriately
        uv_scale = 1.0 / (WHITE_LEVEL - BLACK_LEVEL)
        u_filt = u_filt * uv_scale
        v_filt = v_filt * uv_scale

        return y_filt, u_filt, v_filt

    def yuv_to_rgb(self, y, u, v, saturation=1.0):
        """Convert YUV to RGB."""
        u = u * saturation
        v = v * saturation

        # PAL YUV to RGB matrix (BT.601)
        r = y + 1.140 * v
        g = y - 0.395 * u - 0.581 * v
        b = y + 2.032 * u

        return np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b, 0, 1)

    def decode_frame(self, frame_data, frame_num, use_comb=True, saturation=1.5):
        """Decode a complete frame."""
        height = ACTIVE_LINES
        width = ACTIVE_WIDTH

        # Store decoded lines for comb filtering
        y_lines = []
        u_lines = []
        v_lines = []
        burst_phases = []

        for line_idx in range(height):
            actual_line = ACTIVE_LINES_START + line_idx
            line_start = actual_line * SAMPLES_PER_LINE
            line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

            if len(line_data) < SAMPLES_PER_LINE:
                y_lines.append(np.zeros(width))
                u_lines.append(np.zeros(width))
                v_lines.append(np.zeros(width))
                burst_phases.append(0)
                continue

            # PAL switch
            pal_switch = -1 if (frame_num + actual_line) & 1 else 1

            # Detect burst
            burst_phase, burst_amp, _, _ = self.detect_burst(line_data)
            burst_phases.append(burst_phase)

            if burst_amp < 300:
                # No color - decode as mono
                y = (line_data[ACTIVE_START:ACTIVE_START + width].astype(np.float64) - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
                y_lines.append(scipy_signal.lfilter(self.luma_lp[:17], 1, y))
                u_lines.append(np.zeros(width))
                v_lines.append(np.zeros(width))
            else:
                # Decode with color
                y, u, v = self.decode_line(line_data, pal_switch, burst_phase)
                y_lines.append(y[ACTIVE_START:ACTIVE_START + width])
                u_lines.append(u[ACTIVE_START:ACTIVE_START + width])
                v_lines.append(v[ACTIVE_START:ACTIVE_START + width])

        # Apply PAL delay line (comb filter) if requested
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        for line_idx in range(height):
            y = y_lines[line_idx]

            if use_comb and line_idx > 0:
                # PAL delay line averaging
                # U: add current and previous (V components cancel due to PAL switch)
                # V: subtract previous from current, divide by 2
                u = (u_lines[line_idx] + u_lines[line_idx - 1]) / 2
                v = (v_lines[line_idx] + v_lines[line_idx - 1]) / 2
            else:
                u = u_lines[line_idx]
                v = v_lines[line_idx]

            r, g, b = self.yuv_to_rgb(y, u, v, saturation)

            rgb[line_idx, :, 0] = (r * 255).astype(np.uint8)
            rgb[line_idx, :, 1] = (g * 255).astype(np.uint8)
            rgb[line_idx, :, 2] = (b * 255).astype(np.uint8)

        return rgb


def compute_psnr(original, decoded):
    """Compute PSNR between images."""
    if original.shape != decoded.shape:
        img = Image.fromarray(decoded)
        img = img.resize((original.shape[1], original.shape[0]), Image.LANCZOS)
        decoded = np.array(img)

    mse = np.mean((original.astype(float) - decoded.astype(float)) ** 2)
    if mse == 0:
        return float('inf')
    return 10 * np.log10(255**2 / mse)


def main():
    baseband_file = '/tmp/pal_baseband.bin'
    output_dir = '/tmp/fixed_decode'
    os.makedirs(output_dir, exist_ok=True)

    print("Loading baseband...")
    baseband = np.fromfile(baseband_file, dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME
    print(f"Total frames: {total_frames}")

    # Test frames
    test_frames = [100, 250, 400]

    # Load original reference frames
    orig_frames = {}
    orig_dir = 'tools/comparison_results/original'
    for f in test_frames:
        path = f'{orig_dir}/frame_{f+1:04d}.png'
        if os.path.exists(path):
            img = Image.open(path)
            orig_frames[f] = np.array(img)
            print(f"Loaded original frame {f+1}")

    decoder = PALDecoder()

    # Test different saturation levels
    saturations = [1.0, 1.5, 2.0, 2.5, 3.0]

    print("\nDecoding test frames with different saturation levels...")

    for frame_num in test_frames:
        print(f"\n=== Frame {frame_num} ===")

        frame_start = frame_num * SAMPLES_PER_FRAME
        frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

        if len(frame_data) < SAMPLES_PER_FRAME:
            print(f"  Skipped (insufficient data)")
            continue

        for sat in saturations:
            decoded = decoder.decode_frame(frame_data, frame_num, use_comb=True, saturation=sat)

            # Save decoded frame
            img = Image.fromarray(decoded)
            img.save(f'{output_dir}/frame_{frame_num:04d}_sat{sat:.1f}.png')

            # Compare with original if available
            if frame_num in orig_frames:
                orig = orig_frames[frame_num]
                # Resize decoded to match original
                decoded_resized = np.array(Image.fromarray(decoded).resize(
                    (orig.shape[1], orig.shape[0]), Image.LANCZOS))
                psnr = compute_psnr(orig, decoded_resized)
                print(f"  Saturation {sat:.1f}: PSNR = {psnr:.2f} dB")

    print(f"\nResults saved to {output_dir}/")


if __name__ == '__main__':
    main()
