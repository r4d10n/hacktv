#!/usr/bin/env python3
"""
PAL Decoder - Direct 16 MHz processing

Works directly with hacktv's 16 MHz output without resampling.
This avoids carrier phase alignment issues.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image

# hacktv 16 MHz constants
SAMPLE_RATE = 16e6
LINE_DURATION = 64e-6  # 64 µs
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625
ACTIVE_LINES = 576

# PAL timing (in samples at 16 MHz)
SYNC_START = 0
SYNC_END = int(4.7e-6 * SAMPLE_RATE)  # ~75 samples
BURST_START = int(5.6e-6 * SAMPLE_RATE)  # ~90 samples
BURST_END = BURST_START + int(2.25e-6 * SAMPLE_RATE)  # ~36 samples
ACTIVE_START = int(10.5e-6 * SAMPLE_RATE)  # ~168 samples
ACTIVE_END = int(62.0e-6 * SAMPLE_RATE)  # ~992 samples

# PAL colour carrier
F_SC = 4433618.75

# hacktv signal levels
HACKTV_SYNC = -0.30 * 32767
HACKTV_BLACK = 0
HACKTV_WHITE = 0.70 * 32767


class PALDecoder16MHz:
    def __init__(self, output_width=720, output_height=576):
        self.output_width = output_width
        self.output_height = output_height

        fs = SAMPLE_RATE
        nyq = fs / 2

        # Y lowpass: 5.5 MHz
        self.y_lpf_b, self.y_lpf_a = scipy_signal.butter(6, 5.5e6 / nyq, 'low')

        # Chroma bandpass around f_sc +/- 1.3 MHz
        chroma_low = (F_SC - 1.3e6) / nyq
        chroma_high = (F_SC + 1.3e6) / nyq
        self.chroma_bpf_b, self.chroma_bpf_a = scipy_signal.butter(
            4, [chroma_low, chroma_high], 'band'
        )

        # Notch at f_sc for Y extraction
        notch_low = (F_SC - 0.8e6) / nyq
        notch_high = (F_SC + 0.8e6) / nyq
        self.notch_b, self.notch_a = scipy_signal.butter(
            4, [notch_low, notch_high], 'bandstop'
        )

        # UV lowpass: 1.3 MHz
        self.uv_lpf_b, self.uv_lpf_a = scipy_signal.butter(4, 1.3e6 / nyq, 'low')

    def _detect_pal_switch(self, line_data):
        """
        Detect PAL switch from burst phase.

        hacktv renders burst with same pal multiplier as chroma,
        so burst phase indicates the current pal switch state.
        """
        burst = line_data[BURST_START:BURST_END].astype(np.float64)
        burst = burst - np.mean(burst)

        if len(burst) < 10:
            return 1

        # Generate reference carriers at f_sc
        t = np.arange(len(burst)) / SAMPLE_RATE
        cos_ref = np.cos(2 * np.pi * F_SC * t)
        sin_ref = np.sin(2 * np.pi * F_SC * t)

        # Correlate
        i_corr = np.sum(burst * cos_ref)
        q_corr = np.sum(burst * sin_ref)

        phase = np.arctan2(q_corr, i_corr)
        phase_deg = np.rad2deg(phase)

        # hacktv burst at 135° with pal=+1, ~-135° (45°) with pal=-1
        # Due to the way pal affects the rendering:
        # pal=+1: burst = V_burst * cos + U_burst * sin (phase ~135°)
        # pal=-1: burst = -V_burst * cos + U_burst * sin (phase ~45° or equivalently -135°)

        # Detect based on phase quadrant
        if 90 < phase_deg < 180 or -180 < phase_deg < -90:
            return 1  # Phase near 135° or -135° region
        else:
            return -1  # Phase near 45° or -45° region

    def _extract_y(self, line_data):
        """Extract Y using notch filter."""
        y = scipy_signal.filtfilt(self.notch_b, self.notch_a, line_data)
        y = scipy_signal.filtfilt(self.y_lpf_b, self.y_lpf_a, y)
        return y

    def _extract_chroma(self, line_data):
        """Extract chroma using bandpass."""
        return scipy_signal.filtfilt(self.chroma_bpf_b, self.chroma_bpf_a, line_data)

    def _demodulate(self, chroma, pal):
        """
        Demodulate chroma.

        hacktv encodes: chroma = V * I(t) * pal + U * Q(t)
        where I(t) = cos(2π*f_sc*t), Q(t) = sin(2π*f_sc*t)

        Demodulation:
        - Multiply by Q(t) and lowpass -> U
        - Multiply by I(t) and lowpass -> V * pal
        """
        n = len(chroma)
        t = np.arange(n) / SAMPLE_RATE

        cos_carrier = np.cos(2 * np.pi * F_SC * t)
        sin_carrier = np.sin(2 * np.pi * F_SC * t)

        # Demodulate
        u_raw = chroma * sin_carrier * 2
        v_raw = chroma * cos_carrier * 2

        # Lowpass
        u = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, u_raw)
        v = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, v_raw)

        # Correct V for pal switch
        v = v * pal

        return u, v

    def _pal_delay_average(self, u_curr, v_curr, u_prev, v_prev):
        """PAL delay line averaging."""
        if u_prev is None:
            return u_curr, v_curr
        return (u_curr + u_prev) / 2, (v_curr + v_prev) / 2

    def _yuv_to_rgb(self, y, u, v):
        """Convert YUV to RGB."""
        # Normalize Y from hacktv levels
        y_norm = (y - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        y_norm = np.clip(y_norm, 0, 1)

        # Scale U and V (empirical)
        u_scale = u / (0.493 * (HACKTV_WHITE - HACKTV_BLACK) / 2) * 0.5
        v_scale = v / (0.877 * (HACKTV_WHITE - HACKTV_BLACK) / 2) * 0.5

        # YUV to RGB
        r = y_norm + 1.140 * v_scale
        g = y_norm - 0.581 * v_scale - 0.395 * u_scale
        b = y_norm + 2.028 * u_scale

        return r, g, b

    def decode_field(self, field_data, first_line=23, num_lines=288):
        """
        Decode a PAL field.

        Args:
            field_data: int16 array from hacktv (samples_per_line * lines)
            first_line: First active video line
            num_lines: Number of active lines
        """
        lines_in_data = len(field_data) // SAMPLES_PER_LINE
        output = np.zeros((num_lines, self.output_width, 3), dtype=np.uint8)

        prev_u = None
        prev_v = None

        for out_idx in range(num_lines):
            line_idx = first_line + out_idx

            if line_idx >= lines_in_data:
                break

            line_start = line_idx * SAMPLES_PER_LINE
            line_data = field_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

            # Detect PAL switch
            pal = self._detect_pal_switch(line_data)

            # Extract Y and chroma
            y = self._extract_y(line_data)
            chroma = self._extract_chroma(line_data)

            # Demodulate
            u, v = self._demodulate(chroma, pal)

            # PAL delay averaging
            u_avg, v_avg = self._pal_delay_average(u, v, prev_u, prev_v)
            prev_u = u.copy()
            prev_v = v.copy()

            # Extract active region
            y_active = y[ACTIVE_START:ACTIVE_END]
            u_active = u_avg[ACTIVE_START:ACTIVE_END]
            v_active = v_avg[ACTIVE_START:ACTIVE_END]

            # Convert to RGB
            r, g, b = self._yuv_to_rgb(y_active, u_active, v_active)

            r = np.clip(r * 255, 0, 255).astype(np.uint8)
            g = np.clip(g * 255, 0, 255).astype(np.uint8)
            b = np.clip(b * 255, 0, 255).astype(np.uint8)

            # Resample to output width
            x = np.linspace(0, len(r) - 1, self.output_width)
            output[out_idx, :, 0] = np.interp(x, np.arange(len(r)), r)
            output[out_idx, :, 1] = np.interp(x, np.arange(len(g)), g)
            output[out_idx, :, 2] = np.interp(x, np.arange(len(b)), b)

        # Scale to output height
        if output.shape[0] != self.output_height:
            img = Image.fromarray(output)
            img = img.resize((self.output_width, self.output_height), Image.LANCZOS)
            output = np.array(img)

        return output


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: pal_decoder_16mhz.py <baseband.bin> <output.png> [frame]")
        sys.exit(1)

    baseband_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    data = np.fromfile(baseband_file, dtype=np.int16)
    samples_per_frame = SAMPLES_PER_LINE * LINES_PER_FRAME

    frame_start = frame_num * samples_per_frame
    field_samples = SAMPLES_PER_LINE * 312
    field_data = data[frame_start:frame_start + field_samples]

    decoder = PALDecoder16MHz()
    decoded = decoder.decode_field(field_data)

    img = Image.fromarray(decoded)
    img.save(output_file)
    print(f"Saved {output_file}")

    # Debug: PAL switch detection
    print("\nPAL switch detection for lines 23-33:")
    for line_idx in range(23, 33):
        line_start = line_idx * SAMPLES_PER_LINE
        line_data = field_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)
        burst = line_data[BURST_START:BURST_END]
        burst = burst - np.mean(burst)
        t = np.arange(len(burst)) / SAMPLE_RATE
        i = np.sum(burst * np.cos(2 * np.pi * F_SC * t))
        q = np.sum(burst * np.sin(2 * np.pi * F_SC * t))
        phase = np.rad2deg(np.arctan2(q, i))
        pal = 1 if (90 < phase < 180 or -180 < phase < -90) else -1
        print(f"  Line {line_idx}: phase={phase:.1f}°, pal={pal}")
