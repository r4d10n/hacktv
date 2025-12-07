#!/usr/bin/env python3
"""
PAL Decoder with proper phase tracking

The rainbow artifact indicates carrier phase drift. We need to track
the carrier phase sample-by-sample to match hacktv's encoding.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image

SAMPLE_RATE = 16e6
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625

BURST_START = int(5.6e-6 * SAMPLE_RATE)
BURST_END = BURST_START + int(2.25e-6 * SAMPLE_RATE)
ACTIVE_START = int(10.5e-6 * SAMPLE_RATE)
ACTIVE_END = int(62.0e-6 * SAMPLE_RATE)

FIRST_ACTIVE_LINE = 23
NUM_ACTIVE_LINES = 288

F_SC = 4433618.75

HACKTV_SYNC = -0.30 * 32767
HACKTV_BLACK = 0
HACKTV_WHITE = 0.70 * 32767


class PALDecoderPhaseTrack:
    def __init__(self, output_width=720, output_height=576):
        self.output_width = output_width
        self.output_height = output_height

        fs = SAMPLE_RATE
        nyq = fs / 2

        self.y_lpf_b, self.y_lpf_a = scipy_signal.butter(6, 5.5e6 / nyq, 'low')
        self.chroma_bpf_b, self.chroma_bpf_a = scipy_signal.butter(
            4, [(F_SC - 1.3e6) / nyq, (F_SC + 1.3e6) / nyq], 'band'
        )
        self.notch_b, self.notch_a = scipy_signal.butter(
            4, [(F_SC - 0.8e6) / nyq, (F_SC + 0.8e6) / nyq], 'bandstop'
        )
        self.uv_lpf_b, self.uv_lpf_a = scipy_signal.butter(4, 1.3e6 / nyq, 'low')

    def _detect_burst_phase(self, line_data):
        """Detect burst phase for carrier synchronization."""
        burst = line_data[BURST_START:BURST_END].astype(np.float64)
        burst = burst - np.mean(burst)

        # Generate reference at burst sample positions
        t_burst = (np.arange(BURST_START, BURST_END)) / SAMPLE_RATE
        cos_ref = np.cos(2 * np.pi * F_SC * t_burst)
        sin_ref = np.sin(2 * np.pi * F_SC * t_burst)

        i_corr = np.sum(burst * cos_ref)
        q_corr = np.sum(burst * sin_ref)

        return np.arctan2(q_corr, i_corr)

    def _extract_y(self, line_data):
        y = scipy_signal.filtfilt(self.notch_b, self.notch_a, line_data)
        y = scipy_signal.filtfilt(self.y_lpf_b, self.y_lpf_a, y)
        return y

    def _extract_chroma(self, line_data):
        return scipy_signal.filtfilt(self.chroma_bpf_b, self.chroma_bpf_a, line_data)

    def _demodulate_phase_locked(self, chroma, burst_phase, line_idx):
        """
        Demodulate with burst-locked phase tracking.

        The key insight: hacktv's burst is at 135° in its coordinate system.
        We measure the burst phase and use it to align our demodulation.
        """
        n = len(chroma)

        # Time for each sample in this line
        t = np.arange(n) / SAMPLE_RATE

        # The burst we measured is at sample BURST_START to BURST_END
        # Its phase is 'burst_phase' at the burst center
        burst_center = (BURST_START + BURST_END) // 2
        t_burst_center = burst_center / SAMPLE_RATE

        # hacktv encodes burst at 135° from U axis
        # So at burst center: carrier_phase = burst_phase, which represents 135°

        # Calculate the carrier phase offset to align 135° with measured burst
        # carrier_at_burst = 2π * f_sc * t_burst_center + phase_offset = burst_phase
        # We want the U axis (0°) reference
        carrier_offset = burst_phase - np.deg2rad(135)

        # Generate demodulation carriers aligned to burst
        carrier_phase = 2 * np.pi * F_SC * t + carrier_offset

        # U is on sin (quadrature), V is on cos (in-phase)
        # Actually in PAL: signal = V*cos + U*sin
        u_carrier = np.sin(carrier_phase)
        v_carrier = np.cos(carrier_phase)

        u_raw = chroma * u_carrier * 2
        v_raw = chroma * v_carrier * 2

        u = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, u_raw)
        v = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, v_raw)

        return u, v

    def _pal_delay_average(self, u_curr, v_curr, u_prev, v_prev):
        if u_prev is None:
            return u_curr, v_curr
        return (u_curr + u_prev) / 2, (v_curr + v_prev) / 2

    def _yuv_to_rgb(self, y, u, v):
        y_norm = (y - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        y_norm = np.clip(y_norm, 0, 1)

        # Scale U and V
        chroma_scale = (HACKTV_WHITE - HACKTV_BLACK) * 0.35
        u_scale = u / (0.493 * chroma_scale)
        v_scale = v / (0.877 * chroma_scale)

        r = y_norm + v_scale
        g = y_norm - 0.509 * v_scale - 0.194 * u_scale
        b = y_norm + u_scale

        return r, g, b

    def decode_field(self, field_data):
        output = np.zeros((NUM_ACTIVE_LINES, self.output_width, 3), dtype=np.uint8)

        prev_u = None
        prev_v = None

        for out_idx in range(NUM_ACTIVE_LINES):
            line_idx = FIRST_ACTIVE_LINE + out_idx
            line_start = line_idx * SAMPLES_PER_LINE
            line_data = field_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

            burst_phase = self._detect_burst_phase(line_data)

            y = self._extract_y(line_data)
            chroma = self._extract_chroma(line_data)

            u, v = self._demodulate_phase_locked(chroma, burst_phase, line_idx)

            u_avg, v_avg = self._pal_delay_average(u, v, prev_u, prev_v)
            prev_u = u.copy()
            prev_v = v.copy()

            y_active = y[ACTIVE_START:ACTIVE_END]
            u_active = u_avg[ACTIVE_START:ACTIVE_END]
            v_active = v_avg[ACTIVE_START:ACTIVE_END]

            r, g, b = self._yuv_to_rgb(y_active, u_active, v_active)

            r = np.clip(r * 255, 0, 255).astype(np.uint8)
            g = np.clip(g * 255, 0, 255).astype(np.uint8)
            b = np.clip(b * 255, 0, 255).astype(np.uint8)

            x = np.linspace(0, len(r) - 1, self.output_width)
            output[out_idx, :, 0] = np.interp(x, np.arange(len(r)), r)
            output[out_idx, :, 1] = np.interp(x, np.arange(len(g)), g)
            output[out_idx, :, 2] = np.interp(x, np.arange(len(b)), b)

        if output.shape[0] != self.output_height:
            img = Image.fromarray(output)
            img = img.resize((self.output_width, self.output_height), Image.LANCZOS)
            output = np.array(img)

        return output


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: pal_decoder_phase_track.py <baseband.bin> <output.png> [frame]")
        sys.exit(1)

    baseband_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    data = np.fromfile(baseband_file, dtype=np.int16)
    samples_per_frame = SAMPLES_PER_LINE * LINES_PER_FRAME

    frame_start = frame_num * samples_per_frame
    field_samples = SAMPLES_PER_LINE * 312
    field_data = data[frame_start:frame_start + field_samples]

    decoder = PALDecoderPhaseTrack()
    decoded = decoder.decode_field(field_data)

    img = Image.fromarray(decoded)
    img.save(output_file)
    print(f"Saved {output_file}")
