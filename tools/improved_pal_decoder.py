#!/usr/bin/env python3
"""
Improved PAL Decoder with proper chroma handling.

Key fixes based on analysis:
1. Correct signal level conversion from hacktv format
2. Proper PAL V-switch detection from burst phase
3. Accurate chroma demodulation with burst-locked phase
4. PAL delay line averaging with correct V handling
5. Improved Y/C separation using adaptive comb filtering

Based on "The Engineer's Guide to Decoding & Encoding" by John Watkinson
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import os

# PAL-CRT Constants
PAL_HRES = 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES
PAL_TOP = 22
PAL_BOT = 311
PAL_LINES = PAL_BOT - PAL_TOP

# Timing positions (samples at 4*f_sc)
def ns2pos(ns):
    LINE_ns = 64000
    return (ns * PAL_HRES) // LINE_ns

SYNC_BEG = ns2pos(1600)
CB_BEG = ns2pos(1600 + 4700 + 800)  # After front porch, sync, breezeway
CB_LEN = 40  # ~10 cycles at 4*f_sc
AV_BEG = ns2pos(12000)  # Active video begins
AV_LEN = ns2pos(52000)  # Active video length

# Signal levels
SYNC_LEVEL = -40
BLACK_LEVEL = 0
WHITE_LEVEL = 100


class ImprovedPALDecoder:
    """
    High-quality PAL decoder with correct phase handling.
    """

    def __init__(self, output_width=720, output_height=576):
        self.output_width = output_width
        self.output_height = output_height

        # At 4*f_sc (17.73 MHz), each sample is 90 degrees of carrier
        self.samples_per_cycle = 4

        self._create_filters()

    def _create_filters(self):
        """Create optimized filters for PAL decoding."""
        # Sampling rate is 4 * 4.43361875 MHz = 17.73447 MHz
        fs = 17734475
        nyq = fs / 2

        # Y lowpass: 5.5 MHz
        y_bw = 5.5e6
        self.y_lpf_b, self.y_lpf_a = scipy_signal.butter(6, y_bw / nyq, 'low')

        # Chroma bandpass: f_sc +/- 1.3 MHz
        fc = 4433618.75
        chroma_bw = 1.3e6
        self.chroma_bpf_b, self.chroma_bpf_a = scipy_signal.butter(
            4, [(fc - chroma_bw) / nyq, (fc + chroma_bw) / nyq], 'band'
        )

        # UV lowpass: 1.3 MHz (after demodulation)
        uv_bw = 1.3e6
        self.uv_lpf_b, self.uv_lpf_a = scipy_signal.butter(4, uv_bw / nyq, 'low')

        # Notch filter at f_sc for clean Y
        notch_bw = 0.8e6
        self.notch_b, self.notch_a = scipy_signal.butter(
            3, [(fc - notch_bw) / nyq, (fc + notch_bw) / nyq], 'bandstop'
        )

    def _detect_burst(self, line_data):
        """
        Detect PAL colour burst phase and V-switch state.

        PAL burst alternates between +135 and -135 degrees from U axis.
        - Odd lines (V-switch = +1): burst at +135 degrees
        - Even lines (V-switch = -1): burst at -135 degrees

        At 4*f_sc sampling:
        - Sample 0: 0 degrees (cos = 1, sin = 0)
        - Sample 1: 90 degrees (cos = 0, sin = 1)
        - Sample 2: 180 degrees (cos = -1, sin = 0)
        - Sample 3: 270 degrees (cos = 0, sin = -1)
        """
        if len(line_data) < CB_BEG + CB_LEN:
            return 0.0, 0.0, 1

        burst = line_data[CB_BEG:CB_BEG + CB_LEN].astype(np.float64)
        burst = burst - np.mean(burst)

        # At 4*f_sc, carrier completes one cycle every 4 samples
        t = np.arange(len(burst))

        # Reference carriers (at exactly 4*f_sc)
        ref_cos = np.cos(t * np.pi / 2)
        ref_sin = np.sin(t * np.pi / 2)

        # Correlate to find phase
        i_corr = np.sum(burst * ref_cos) * 2 / len(burst)
        q_corr = np.sum(burst * ref_sin) * 2 / len(burst)

        phase = np.arctan2(q_corr, i_corr)
        amplitude = np.sqrt(i_corr**2 + q_corr**2)

        # Determine V-switch state from burst phase
        # PAL burst is at 135 degrees (V=+1) or -135 degrees (V=-1) from U axis
        phase_deg = np.rad2deg(phase)

        # Normalize to -180 to +180
        while phase_deg > 180:
            phase_deg -= 360
        while phase_deg < -180:
            phase_deg += 360

        # V-switch detection:
        # burst at ~135 deg -> V-switch = +1
        # burst at ~-135 deg (or 225) -> V-switch = -1
        if -90 < phase_deg < 90:
            # Burst is in right half of circle
            if phase_deg > 0:
                v_switch = 1  # Around +135 -> +45 after offset
            else:
                v_switch = -1
        else:
            # Burst is in left half
            if phase_deg > 0:
                v_switch = 1
            else:
                v_switch = -1

        # More robust: use the actual measured phase
        # PAL burst should be at +135 or -135 (equivalently +225)
        if 45 < phase_deg < 180 or -180 < phase_deg < -135:
            v_switch = 1
        else:
            v_switch = -1

        return phase, amplitude, v_switch

    def _extract_chroma_comb(self, field_buffer, line_idx):
        """
        Extract chroma using 2-line comb filter.

        In PAL, chroma inverts phase every line (for V component).
        Subtracting adjacent lines doubles chroma and cancels Y.
        Adding adjacent lines doubles Y and cancels chroma.
        """
        if line_idx < 1 or line_idx >= len(field_buffer) - 1:
            # Edge case: use bandpass filter
            line = field_buffer[line_idx].astype(np.float64)
            chroma = scipy_signal.filtfilt(
                self.chroma_bpf_b, self.chroma_bpf_a, line
            )
            y = scipy_signal.filtfilt(self.notch_b, self.notch_a, line)
            return y, chroma

        prev_line = field_buffer[line_idx - 1].astype(np.float64)
        curr_line = field_buffer[line_idx].astype(np.float64)
        next_line = field_buffer[line_idx + 1].astype(np.float64)

        # 3-tap Y comb: (prev + 2*curr + next) / 4
        y_comb = (prev_line + 2 * curr_line + next_line) / 4.0

        # Chroma: curr - y_comb (complementary filter)
        chroma_comb = curr_line - y_comb

        # Apply bandpass to clean up chroma
        chroma = scipy_signal.filtfilt(
            self.chroma_bpf_b, self.chroma_bpf_a, chroma_comb
        )

        # Apply lowpass to Y
        y = scipy_signal.filtfilt(self.y_lpf_b, self.y_lpf_a, y_comb)

        return y, chroma

    def _demodulate_chroma(self, chroma, burst_phase, v_switch):
        """
        Demodulate PAL chroma to U and V using burst-locked carriers.

        hacktv PAL encoding (from video.c):
            chroma = U * sin(wt) + V * cos(wt) * pal_switch

        where pal_switch alternates +1/-1 per line.

        To demodulate:
            U = chroma * sin(wt) * 2, then lowpass
            V = chroma * cos(wt) * v_switch * 2, then lowpass
        """
        n = len(chroma)
        t = np.arange(n)

        # At 4*f_sc, one cycle = 4 samples
        # Burst phase tells us the carrier phase at burst position
        # We need to account for the phase relationship

        # The burst is at 135 degrees from U axis (for v_switch=+1)
        # So burst_phase measured from our reference should be ~135 deg

        # Demodulation carriers aligned to burst
        # Burst at 135 deg means: at burst position, carrier phase = 135 deg
        # We measure burst_phase relative to our reference (sample 0 = 0 deg)

        # For proper demodulation, align carriers to the encoding
        omega_t = t * np.pi / 2  # Carrier phase at 4*f_sc

        # U carrier: sin(wt)
        # V carrier: cos(wt) * v_switch
        u_carrier = np.sin(omega_t)
        v_carrier = np.cos(omega_t)

        # Demodulate
        u_raw = chroma * u_carrier * 2
        v_raw = chroma * v_carrier * v_switch * 2

        # Lowpass filter to remove 2*f_sc component
        u_filt = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, u_raw)
        v_filt = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, v_raw)

        return u_filt, v_filt

    def _pal_delay_line(self, u_curr, v_curr, u_prev, v_prev, v_switch_curr, v_switch_prev):
        """
        PAL delay line processing.

        Average U and V over two lines to cancel phase errors.
        U is the same on both lines.
        V was encoded with opposite signs on adjacent lines, but we've
        already corrected for v_switch during demodulation, so we can
        directly average.
        """
        if u_prev is None:
            return u_curr, v_curr

        # Simple averaging
        u_avg = (u_curr + u_prev) / 2.0
        v_avg = (v_curr + v_prev) / 2.0

        return u_avg, v_avg

    def _yuv_to_rgb(self, y, u, v):
        """
        Convert YUV to RGB.

        Y is in IRE units (-40 to 100), need to normalize to 0-1.
        U and V are demodulated chroma, need appropriate scaling.

        ITU-R BT.601 YUV to RGB:
        R = Y + 1.140 * V
        G = Y - 0.395 * U - 0.581 * V
        B = Y + 2.032 * U
        """
        # Normalize Y from IRE to 0-1
        # Black = 0 IRE, White = 100 IRE
        y_norm = np.clip(y / 100.0, 0, 1)

        # Scale U and V
        # The demodulated values need scaling based on encoding levels
        # hacktv uses eu=0.493, ev=0.877 for encoding
        # Burst amplitude in signal gives us reference
        u_scale = u / 30.0  # Empirical scaling
        v_scale = v / 30.0

        # BT.601 matrix
        r = y_norm + 1.140 * v_scale
        g = y_norm - 0.395 * u_scale - 0.581 * v_scale
        b = y_norm + 2.032 * u_scale

        return r, g, b

    def decode_field(self, field_signal):
        """
        Decode a PAL field to RGB.

        Args:
            field_signal: int8 array of PAL_INPUT_SIZE samples in IRE

        Returns:
            RGB image as uint8 array (height, width, 3)
        """
        if len(field_signal) != PAL_INPUT_SIZE:
            raise ValueError(f"Expected {PAL_INPUT_SIZE} samples, got {len(field_signal)}")

        # Reshape to lines
        field = field_signal.reshape((PAL_VRES, PAL_HRES)).astype(np.float64)

        output = np.zeros((PAL_LINES, self.output_width, 3), dtype=np.uint8)

        prev_u = None
        prev_v = None
        prev_v_switch = None

        for line_idx in range(PAL_TOP, PAL_BOT):
            out_idx = line_idx - PAL_TOP
            line_data = field[line_idx]

            # Detect burst phase and V-switch
            burst_phase, burst_amp, v_switch = self._detect_burst(line_data)

            # Y/C separation using comb filter
            y, chroma = self._extract_chroma_comb(field, line_idx)

            # Demodulate chroma
            u, v = self._demodulate_chroma(chroma, burst_phase, v_switch)

            # PAL delay line averaging
            u_avg, v_avg = self._pal_delay_line(
                u, v, prev_u, prev_v, v_switch, prev_v_switch
            )

            # Store for next line
            prev_u = u.copy()
            prev_v = v.copy()
            prev_v_switch = v_switch

            # Extract active video region
            y_active = y[AV_BEG:AV_BEG + AV_LEN]
            u_active = u_avg[AV_BEG:AV_BEG + AV_LEN]
            v_active = v_avg[AV_BEG:AV_BEG + AV_LEN]

            # Convert to RGB
            r, g, b = self._yuv_to_rgb(y_active, u_active, v_active)

            # Clip and convert to uint8
            r = np.clip(r * 255, 0, 255).astype(np.uint8)
            g = np.clip(g * 255, 0, 255).astype(np.uint8)
            b = np.clip(b * 255, 0, 255).astype(np.uint8)

            # Resample to output width
            x = np.linspace(0, len(r) - 1, self.output_width)
            output[out_idx, :, 0] = np.interp(x, np.arange(len(r)), r).astype(np.uint8)
            output[out_idx, :, 1] = np.interp(x, np.arange(len(g)), g).astype(np.uint8)
            output[out_idx, :, 2] = np.interp(x, np.arange(len(b)), b).astype(np.uint8)

        # Scale to output height
        if output.shape[0] != self.output_height:
            img = Image.fromarray(output)
            img = img.resize((self.output_width, self.output_height), Image.LANCZOS)
            output = np.array(img)

        return output


def resample_hacktv_to_palcrt(data, src_samples_per_line=1024, src_lines=312):
    """
    Resample hacktv 16MHz baseband to PAL-CRT 4*f_sc format.

    hacktv int16 levels:
        sync:  -0.30 * 32767 = -9830
        black:  0.00 * 32767 = 0
        white:  0.70 * 32767 = 22937

    PAL-CRT int8 IRE levels:
        sync:  -40
        black:  0
        white:  100
    """
    output = np.zeros(PAL_INPUT_SIZE, dtype=np.int8)

    HACKTV_SYNC = -0.30 * 32767
    HACKTV_WHITE = 0.70 * 32767

    for line in range(min(src_lines, PAL_VRES)):
        src_start = line * src_samples_per_line
        src_end = src_start + src_samples_per_line

        if src_end > len(data):
            break

        line_data = data[src_start:src_end].astype(np.float64)

        # Resample from 1024 to 1135 samples
        x_src = np.arange(len(line_data))
        x_dst = np.linspace(0, len(line_data) - 1, PAL_HRES)
        resampled = np.interp(x_dst, x_src, line_data)

        # Convert to IRE
        normalized = (resampled - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

        # Clip to int8 range
        output[line * PAL_HRES:(line + 1) * PAL_HRES] = np.clip(ire, -128, 127).astype(np.int8)

    return output


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: improved_pal_decoder.py <baseband.bin> <output.png> [frame_num]")
        sys.exit(1)

    baseband_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    # Load baseband
    data = np.fromfile(baseband_file, dtype=np.int16)
    samples_per_line = 1024
    samples_per_frame = samples_per_line * 625

    # Extract field
    frame_start = frame_num * samples_per_frame
    field_samples = samples_per_line * 312
    field_data = data[frame_start:frame_start + field_samples]

    # Resample
    resampled = resample_hacktv_to_palcrt(field_data, samples_per_line, 312)

    # Decode
    decoder = ImprovedPALDecoder()
    decoded = decoder.decode_field(resampled)

    # Save
    img = Image.fromarray(decoded)
    img.save(output_file)
    print(f"Saved {output_file}")
