#!/usr/bin/env python3
"""
Test different U/V axis combinations to find correct color mapping.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os

# hacktv constants
SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * LINES_PER_FRAME

SYNC_LEVEL = int(-0.30 * 32767)
BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)

ACTIVE_START = 264
ACTIVE_WIDTH = 702
ACTIVE_LINES_START = 23
ACTIVE_LINES = 576

BURST_START = 88
BURST_WIDTH = 40


def create_lowpass_filter(cutoff, sample_rate, numtaps=33):
    return scipy_signal.firwin(numtaps, cutoff / (sample_rate/2))


def create_bandpass_filter(center_freq, bandwidth, sample_rate, numtaps=65):
    low = (center_freq - bandwidth/2) / (sample_rate/2)
    high = (center_freq + bandwidth/2) / (sample_rate/2)
    return scipy_signal.firwin(numtaps, [low, high], pass_zero=False)


class PALDecoderTest:
    def __init__(self):
        self.phase_inc = 2 * np.pi * F_SC / SAMPLE_RATE
        t = np.arange(SAMPLES_PER_LINE)
        self.carrier_phase = t * self.phase_inc
        self.sin_carrier = np.sin(self.carrier_phase)
        self.cos_carrier = np.cos(self.carrier_phase)
        self.chroma_bp = create_bandpass_filter(F_SC, 1.3e6, SAMPLE_RATE, numtaps=65)
        self.chroma_lp = create_lowpass_filter(1.3e6, SAMPLE_RATE, numtaps=33)
        self.luma_lp = create_lowpass_filter(5e6, SAMPLE_RATE, numtaps=17)

    def detect_burst(self, line_signal):
        burst_region = line_signal[BURST_START:BURST_START + BURST_WIDTH].astype(np.float64)
        burst_region = burst_region - np.mean(burst_region)
        sin_burst = self.sin_carrier[BURST_START:BURST_START + BURST_WIDTH]
        cos_burst = self.cos_carrier[BURST_START:BURST_START + BURST_WIDTH]
        i_corr = np.sum(burst_region * cos_burst) * 2 / BURST_WIDTH
        q_corr = np.sum(burst_region * sin_burst) * 2 / BURST_WIDTH
        amplitude = np.sqrt(i_corr**2 + q_corr**2)
        phase = np.arctan2(q_corr, i_corr)
        return phase, amplitude

    def decode_frame(self, frame_data, frame_num, uv_mode='normal', saturation=1.5):
        """
        uv_mode options:
        - 'normal': U=cos, V=sin*pal (standard)
        - 'swap': U=sin*pal, V=cos
        - 'neg_u': U=-cos, V=sin*pal
        - 'neg_v': U=cos, V=-sin*pal
        - 'neg_both': U=-cos, V=-sin*pal
        - 'swap_neg': U=-sin*pal, V=-cos
        """
        height = ACTIVE_LINES
        width = ACTIVE_WIDTH

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

            pal_switch = -1 if (frame_num + actual_line) & 1 else 1
            burst_phase, burst_amp = self.detect_burst(line_data)

            sig = line_data.astype(np.float64)

            # Phase correction based on burst
            burst_ref = 135 * np.pi / 180
            phase_correction = burst_phase + burst_ref

            corrected_phase = self.carrier_phase - phase_correction
            sin_corr = np.sin(corrected_phase)
            cos_corr = np.cos(corrected_phase)

            # Extract chroma
            chroma = scipy_signal.lfilter(self.chroma_bp, 1, sig)

            # Demodulate based on mode
            if uv_mode == 'normal':
                u_demod = chroma * cos_corr * 2
                v_demod = chroma * sin_corr * 2 * pal_switch
            elif uv_mode == 'swap':
                u_demod = chroma * sin_corr * 2 * pal_switch
                v_demod = chroma * cos_corr * 2
            elif uv_mode == 'neg_u':
                u_demod = -chroma * cos_corr * 2
                v_demod = chroma * sin_corr * 2 * pal_switch
            elif uv_mode == 'neg_v':
                u_demod = chroma * cos_corr * 2
                v_demod = -chroma * sin_corr * 2 * pal_switch
            elif uv_mode == 'neg_both':
                u_demod = -chroma * cos_corr * 2
                v_demod = -chroma * sin_corr * 2 * pal_switch
            elif uv_mode == 'swap_neg':
                u_demod = -chroma * sin_corr * 2 * pal_switch
                v_demod = -chroma * cos_corr * 2
            elif uv_mode == 'swap_neg_u':
                u_demod = -chroma * sin_corr * 2 * pal_switch
                v_demod = chroma * cos_corr * 2
            elif uv_mode == 'swap_neg_v':
                u_demod = chroma * sin_corr * 2 * pal_switch
                v_demod = -chroma * cos_corr * 2
            else:
                u_demod = chroma * cos_corr * 2
                v_demod = chroma * sin_corr * 2 * pal_switch

            u_filt = scipy_signal.lfilter(self.chroma_lp, 1, u_demod)
            v_filt = scipy_signal.lfilter(self.chroma_lp, 1, v_demod)

            y_raw = (sig - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_filt = scipy_signal.lfilter(self.luma_lp, 1, y_raw)

            uv_scale = 1.0 / (WHITE_LEVEL - BLACK_LEVEL)
            u_filt = u_filt * uv_scale
            v_filt = v_filt * uv_scale

            y_lines.append(y_filt[ACTIVE_START:ACTIVE_START + width])
            u_lines.append(u_filt[ACTIVE_START:ACTIVE_START + width])
            v_lines.append(v_filt[ACTIVE_START:ACTIVE_START + width])

        # Apply comb filter and convert to RGB
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

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

            # YUV to RGB (BT.601)
            r = y + 1.140 * v
            g = y - 0.395 * u - 0.581 * v
            b = y + 2.032 * u

            r = np.clip(r, 0, 1)
            g = np.clip(g, 0, 1)
            b = np.clip(b, 0, 1)

            rgb[line_idx, :, 0] = (r * 255).astype(np.uint8)
            rgb[line_idx, :, 1] = (g * 255).astype(np.uint8)
            rgb[line_idx, :, 2] = (b * 255).astype(np.uint8)

        return rgb


def compute_psnr(original, decoded):
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
    output_dir = '/tmp/uv_test'
    os.makedirs(output_dir, exist_ok=True)

    print("Loading baseband...")
    baseband = np.fromfile(baseband_file, dtype=np.int16)

    # Load originals
    orig_frames = {}
    orig_dir = 'tools/comparison_results/original'
    for f, fname in [(100, 'frame_0101.png'), (250, 'frame_0251.png'), (400, 'frame_0401.png')]:
        path = f'{orig_dir}/{fname}'
        if os.path.exists(path):
            orig_frames[f] = np.array(Image.open(path))

    decoder = PALDecoderTest()

    uv_modes = ['normal', 'swap', 'neg_u', 'neg_v', 'neg_both', 'swap_neg', 'swap_neg_u', 'swap_neg_v']
    test_frames = [100, 250]

    print("\nTesting U/V combinations...")

    results = {}
    for mode in uv_modes:
        results[mode] = []
        for frame_num in test_frames:
            frame_start = frame_num * SAMPLES_PER_FRAME
            frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

            decoded = decoder.decode_frame(frame_data, frame_num, uv_mode=mode, saturation=1.5)

            # Save
            img = Image.fromarray(decoded)
            img.save(f'{output_dir}/frame_{frame_num:04d}_{mode}.png')

            # PSNR
            if frame_num in orig_frames:
                orig = orig_frames[frame_num]
                decoded_resized = np.array(Image.fromarray(decoded).resize(
                    (orig.shape[1], orig.shape[0]), Image.LANCZOS))
                psnr = compute_psnr(orig, decoded_resized)
                results[mode].append(psnr)

        if results[mode]:
            avg_psnr = np.mean(results[mode])
            print(f"  {mode:12s}: avg PSNR = {avg_psnr:.2f} dB  (f100={results[mode][0]:.2f}, f250={results[mode][1]:.2f})")

    # Find best mode
    best_mode = max(results.keys(), key=lambda m: np.mean(results[m]) if results[m] else 0)
    print(f"\nBest mode: {best_mode} with avg PSNR = {np.mean(results[best_mode]):.2f} dB")

    print(f"\nResults saved to {output_dir}/")


if __name__ == '__main__':
    main()
