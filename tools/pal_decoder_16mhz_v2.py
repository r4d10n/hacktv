#!/usr/bin/env python3
"""
Proper 16MHz PAL decoder for hacktv baseband.

This decoder works directly at 16MHz sample rate without resampling,
matching the exact hacktv encoding formula:

    Chroma = V * sin(wt) * pal_switch + U * cos(wt)
    where pal_switch = -1 if (frame + line) & 1 else +1
    Burst phase = 135° (cos(135°), sin(135°)) = (-0.707, +0.707)

The burst signal is: sin(135°)*sin(wt)*pal + cos(135°)*cos(wt)
                   = 0.707*sin(wt)*pal - 0.707*cos(wt)
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os

# Constants
SAMPLE_RATE = 16e6  # 16 MHz
F_SC = 4433618.75   # PAL subcarrier frequency
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * LINES_PER_FRAME

# Signal levels (hacktv int16)
SYNC_LEVEL = int(-0.30 * 32767)  # -9830
BLACK_LEVEL = 0
WHITE_LEVEL = int(0.70 * 32767)  # 22937

# Video timing (approximate, in samples at 16MHz)
LINE_SYNC_START = 0
LINE_SYNC_END = 75
BURST_START = 85
BURST_END = 130
ACTIVE_START = 210
ACTIVE_END = 925  # ~715 active samples

# Output dimensions
OUT_WIDTH = 702
OUT_HEIGHT = 576
FIRST_ACTIVE_LINE = 23


class PALDecoder16MHz:
    def __init__(self):
        # Phase per sample
        self.omega = 2 * np.pi * F_SC / SAMPLE_RATE  # ~1.742 rad/sample

        # Pre-compute carriers for one line
        t = np.arange(SAMPLES_PER_LINE)
        self.phase = t * self.omega
        self.sin_carrier = np.sin(self.phase)
        self.cos_carrier = np.cos(self.phase)

        # Bandpass filter for chroma extraction (~3.5 to 5.4 MHz)
        low = 3.5e6 / (SAMPLE_RATE / 2)
        high = 5.4e6 / (SAMPLE_RATE / 2)
        self.chroma_bp = scipy_signal.firwin(65, [low, high], pass_zero=False)

        # Lowpass filter for demodulated U/V (~1.3 MHz)
        self.uv_lp = scipy_signal.firwin(33, 1.3e6 / (SAMPLE_RATE / 2))

        # Lowpass filter for luminance (~4.2 MHz)
        self.y_lp = scipy_signal.firwin(21, 4.2e6 / (SAMPLE_RATE / 2))

    def detect_burst(self, line_signal):
        """
        Detect burst phase and amplitude.

        hacktv burst: sin(135°)*sin(wt)*pal + cos(135°)*cos(wt)
                    = 0.707*sin(wt)*pal - 0.707*cos(wt)

        For pal=+1: burst = 0.707*(sin(wt) - cos(wt))
        For pal=-1: burst = 0.707*(-sin(wt) - cos(wt))
        """
        burst = line_signal[BURST_START:BURST_END].astype(np.float64)
        burst = burst - np.mean(burst)  # Remove DC

        # Reference carriers at burst position
        sin_b = self.sin_carrier[BURST_START:BURST_END]
        cos_b = self.cos_carrier[BURST_START:BURST_END]

        # Correlate to get I (cos) and Q (sin) components
        i_comp = np.sum(burst * cos_b) * 2 / len(burst)
        q_comp = np.sum(burst * sin_b) * 2 / len(burst)

        amplitude = np.sqrt(i_comp**2 + q_comp**2)
        phase = np.arctan2(q_comp, i_comp)

        return phase, amplitude, i_comp, q_comp

    def decode_line(self, line_signal, pal_switch):
        """
        Decode one line of PAL signal.

        hacktv encoding: V*sin(wt)*pal + U*cos(wt)

        Demodulation:
        - Multiply by cos(wt) and lowpass → U
        - Multiply by sin(wt)*pal and lowpass → V
        """
        sig = line_signal.astype(np.float64)

        # Detect burst to lock phase
        burst_phase, burst_amp, i_burst, q_burst = self.detect_burst(sig)

        if burst_amp < 300:
            # No burst - return grayscale
            y = (sig[ACTIVE_START:ACTIVE_END] - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_filt = scipy_signal.lfilter(self.y_lp[:11], 1, y)
            # Resample to output width
            y_out = np.interp(np.linspace(0, len(y_filt)-1, OUT_WIDTH),
                              np.arange(len(y_filt)), y_filt)
            return y_out, np.zeros(OUT_WIDTH), np.zeros(OUT_WIDTH)

        # hacktv burst is at 135° = -0.707*cos + 0.707*sin*pal
        # Expected: i_burst ≈ -0.707 * amplitude, q_burst ≈ 0.707 * amplitude * pal
        # The burst tells us the carrier phase reference

        # Calculate phase correction needed
        # Burst should be at 135° relative to U axis (cos)
        # i_burst/amplitude = cos(burst_angle)
        # q_burst/amplitude = sin(burst_angle) * pal
        expected_burst_angle = 135 * np.pi / 180  # 135°

        # Detected burst phase relative to our carrier
        detected_angle = np.arctan2(q_burst * pal_switch, i_burst)

        # Phase correction to align with hacktv's reference
        phase_correction = detected_angle - expected_burst_angle

        # Generate corrected carriers
        corrected_phase = self.phase - phase_correction
        sin_c = np.sin(corrected_phase)
        cos_c = np.cos(corrected_phase)

        # Extract chroma by bandpass filtering
        chroma = scipy_signal.lfilter(self.chroma_bp, 1, sig)

        # Demodulate U and V
        # U = chroma * cos(wt) * 2 (lowpassed)
        # V = chroma * sin(wt) * pal_switch * 2 (lowpassed)
        u_raw = chroma * cos_c * 2
        v_raw = chroma * sin_c * 2 * pal_switch

        u_filt = scipy_signal.lfilter(self.uv_lp, 1, u_raw)
        v_filt = scipy_signal.lfilter(self.uv_lp, 1, v_raw)

        # Extract luminance
        y_raw = (sig - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
        y_filt = scipy_signal.lfilter(self.y_lp, 1, y_raw)

        # Scale U, V to proper range
        uv_scale = 1.0 / (burst_amp * 1.414)  # Normalize by burst amplitude

        # Extract active region and resample to output width
        y_active = y_filt[ACTIVE_START:ACTIVE_END]
        u_active = u_filt[ACTIVE_START:ACTIVE_END] * uv_scale
        v_active = v_filt[ACTIVE_START:ACTIVE_END] * uv_scale

        x_in = np.arange(len(y_active))
        x_out = np.linspace(0, len(y_active)-1, OUT_WIDTH)

        y_out = np.interp(x_out, x_in, y_active)
        u_out = np.interp(x_out, x_in, u_active)
        v_out = np.interp(x_out, x_in, v_active)

        return y_out, u_out, v_out

    def yuv_to_rgb(self, y, u, v, saturation=1.0):
        """
        Convert YUV to RGB using standard PAL matrix.

        PAL uses EBU standard:
        R = Y + 1.140 * V
        G = Y - 0.396 * U - 0.581 * V
        B = Y + 2.029 * U
        """
        u = u * saturation
        v = v * saturation

        r = y + 1.140 * v
        g = y - 0.396 * u - 0.581 * v
        b = y + 2.029 * u

        return (np.clip(r, 0, 1) * 255).astype(np.uint8), \
               (np.clip(g, 0, 1) * 255).astype(np.uint8), \
               (np.clip(b, 0, 1) * 255).astype(np.uint8)

    def decode_frame(self, frame_data, frame_num, saturation=1.5, use_comb=True):
        """
        Decode one complete frame.
        """
        rgb = np.zeros((OUT_HEIGHT, OUT_WIDTH, 3), dtype=np.uint8)

        y_lines = []
        u_lines = []
        v_lines = []

        for line_idx in range(OUT_HEIGHT):
            actual_line = FIRST_ACTIVE_LINE + line_idx
            line_start = actual_line * SAMPLES_PER_LINE
            line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

            if len(line_data) < SAMPLES_PER_LINE:
                y_lines.append(np.zeros(OUT_WIDTH))
                u_lines.append(np.zeros(OUT_WIDTH))
                v_lines.append(np.zeros(OUT_WIDTH))
                continue

            # PAL switch based on hacktv convention
            pal_switch = -1 if (frame_num + actual_line) & 1 else 1

            y, u, v = self.decode_line(line_data, pal_switch)

            y_lines.append(y)
            u_lines.append(u)
            v_lines.append(v)

        # Apply PAL delay line (comb filter) if requested
        for line_idx in range(OUT_HEIGHT):
            y = y_lines[line_idx]

            if use_comb and line_idx > 0:
                # PAL delay line: average adjacent lines
                # This helps cancel crosstalk between U and V
                u = (u_lines[line_idx] + u_lines[line_idx - 1]) / 2
                v = (v_lines[line_idx] + v_lines[line_idx - 1]) / 2
            else:
                u = u_lines[line_idx]
                v = v_lines[line_idx]

            r, g, b = self.yuv_to_rgb(y, u, v, saturation)

            rgb[line_idx, :, 0] = r
            rgb[line_idx, :, 1] = g
            rgb[line_idx, :, 2] = b

        return rgb


def main():
    print("16MHz PAL Decoder Test")
    print("=" * 60)

    # Test with color bars
    baseband_file = '/tmp/color_calibration/colorbars_pal.bin'
    if not os.path.exists(baseband_file):
        print("Run analyze_color_transform.py first to generate color bars!")
        return

    print("\nLoading color bars baseband...")
    baseband = np.fromfile(baseband_file, dtype=np.int16)

    os.makedirs('/tmp/decoder_16mhz_test', exist_ok=True)
    decoder = PALDecoder16MHz()

    # Decode middle frame
    frame_num = 15
    frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num + 1) * SAMPLES_PER_FRAME]

    print("\nTesting saturation levels...")
    for sat in [1.0, 1.5, 2.0, 2.5, 3.0]:
        decoded = decoder.decode_frame(frame_data, frame_num, saturation=sat)
        Image.fromarray(decoded).save(f'/tmp/decoder_16mhz_test/colorbars_sat{sat:.1f}.png')
        print(f"  Saved colorbars_sat{sat:.1f}.png")

    # Sample colors from best saturation
    print("\nAnalyzing color accuracy...")
    decoded = decoder.decode_frame(frame_data, frame_num, saturation=2.0)

    # Sample color bars
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

    print("\nColor comparison:")
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
    print(f"\nResults saved to /tmp/decoder_16mhz_test/")


if __name__ == '__main__':
    main()
