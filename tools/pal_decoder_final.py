#!/usr/bin/env python3
"""
PAL Decoder Final - Uses known frame/line for PAL switch

The PAL switch is determined by (frame + line) & 1 as per hacktv.
This decoder works directly at 16 MHz without resampling issues.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image

# hacktv 16 MHz constants
SAMPLE_RATE = 16e6
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625

# PAL timing (in samples at 16 MHz)
BURST_START = int(5.6e-6 * SAMPLE_RATE)  # ~90 samples
BURST_END = BURST_START + int(2.25e-6 * SAMPLE_RATE)  # ~36 samples
ACTIVE_START = int(10.5e-6 * SAMPLE_RATE)  # ~168 samples
ACTIVE_END = int(62.0e-6 * SAMPLE_RATE)  # ~992 samples

# First active line and count
FIRST_ACTIVE_LINE = 23
NUM_ACTIVE_LINES = 288

# PAL colour carrier
F_SC = 4433618.75

# hacktv signal levels
HACKTV_SYNC = -0.30 * 32767
HACKTV_BLACK = 0
HACKTV_WHITE = 0.70 * 32767


class PALDecoderFinal:
    def __init__(self, output_width=720, output_height=576):
        self.output_width = output_width
        self.output_height = output_height

        fs = SAMPLE_RATE
        nyq = fs / 2

        # Y lowpass: 5.5 MHz
        self.y_lpf_b, self.y_lpf_a = scipy_signal.butter(6, 5.5e6 / nyq, 'low')

        # Chroma bandpass around f_sc +/- 1.3 MHz
        self.chroma_bpf_b, self.chroma_bpf_a = scipy_signal.butter(
            4, [(F_SC - 1.3e6) / nyq, (F_SC + 1.3e6) / nyq], 'band'
        )

        # Notch at f_sc for Y extraction
        self.notch_b, self.notch_a = scipy_signal.butter(
            4, [(F_SC - 0.8e6) / nyq, (F_SC + 0.8e6) / nyq], 'bandstop'
        )

        # UV lowpass: 1.3 MHz
        self.uv_lpf_b, self.uv_lpf_a = scipy_signal.butter(4, 1.3e6 / nyq, 'low')

    def _get_pal_switch(self, frame, line):
        """
        Get PAL switch value based on frame and line number.

        hacktv: pal = -1 if (frame + line) & 1 else +1
        """
        return -1 if ((frame + line) & 1) else 1

    def _extract_y(self, line_data):
        """Extract Y using notch filter to remove chroma."""
        y = scipy_signal.filtfilt(self.notch_b, self.notch_a, line_data)
        y = scipy_signal.filtfilt(self.y_lpf_b, self.y_lpf_a, y)
        return y

    def _extract_chroma(self, line_data):
        """Extract chroma using bandpass filter."""
        return scipy_signal.filtfilt(self.chroma_bpf_b, self.chroma_bpf_a, line_data)

    def _demodulate(self, chroma, pal):
        """
        Demodulate chroma to U and V.

        hacktv encodes: chroma = V * cos(wt) * pal + U * sin(wt)

        Demodulation:
        - Multiply by sin(wt) -> U
        - Multiply by cos(wt) -> V * pal, then correct with pal
        """
        n = len(chroma)
        t = np.arange(n) / SAMPLE_RATE

        cos_carrier = np.cos(2 * np.pi * F_SC * t)
        sin_carrier = np.sin(2 * np.pi * F_SC * t)

        # Demodulate
        u_raw = chroma * sin_carrier * 2
        v_raw = chroma * cos_carrier * 2  # This gives V * pal

        # Lowpass filter
        u = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, u_raw)
        v = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, v_raw)

        # Correct V for PAL switch
        v = v * pal

        return u, v

    def _pal_delay_average(self, u_curr, v_curr, u_prev, v_prev):
        """
        PAL delay line averaging.

        After PAL switch correction, both U and V can be averaged directly.
        """
        if u_prev is None:
            return u_curr, v_curr
        return (u_curr + u_prev) / 2, (v_curr + v_prev) / 2

    def _yuv_to_rgb(self, y, u, v):
        """
        Convert YUV to RGB.

        hacktv encoding coefficients: eu_co = 0.493, ev_co = 0.877
        """
        # Normalize Y from hacktv levels
        y_norm = (y - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        y_norm = np.clip(y_norm, 0, 1)

        # Scale U and V based on encoding coefficients
        # hacktv encodes: U = eu_co * (B-Y), V = ev_co * (R-Y)
        # So: B-Y = U / eu_co, R-Y = V / ev_co
        chroma_scale = (HACKTV_WHITE - HACKTV_BLACK) * 0.5  # Chroma amplitude
        u_scale = u / (0.493 * chroma_scale)
        v_scale = v / (0.877 * chroma_scale)

        # YUV to RGB (BT.601)
        r = y_norm + v_scale
        g = y_norm - 0.509 * v_scale - 0.194 * u_scale
        b = y_norm + u_scale

        return r, g, b

    def decode_field(self, field_data, frame_num):
        """
        Decode a PAL field.

        Args:
            field_data: int16 array from hacktv
            frame_num: Frame number (needed for PAL switch calculation)
        """
        output = np.zeros((NUM_ACTIVE_LINES, self.output_width, 3), dtype=np.uint8)

        prev_u = None
        prev_v = None

        for out_idx in range(NUM_ACTIVE_LINES):
            line_idx = FIRST_ACTIVE_LINE + out_idx
            line_start = line_idx * SAMPLES_PER_LINE
            line_data = field_data[line_start:line_start + SAMPLES_PER_LINE].astype(np.float64)

            # Get PAL switch for this line
            pal = self._get_pal_switch(frame_num, line_idx)

            # Extract Y and chroma
            y = self._extract_y(line_data)
            chroma = self._extract_chroma(line_data)

            # Demodulate with known PAL switch
            u, v = self._demodulate(chroma, pal)

            # PAL delay averaging
            u_avg, v_avg = self._pal_delay_average(u, v, prev_u, prev_v)
            prev_u = u.copy()
            prev_v = v.copy()

            # Extract active video region
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


def compute_metrics(original, decoded):
    """Compute PSNR and SSIM between original and decoded."""
    if original.shape != decoded.shape:
        img = Image.fromarray(decoded)
        img = img.resize((original.shape[1], original.shape[0]), Image.LANCZOS)
        decoded = np.array(img)

    mse = np.mean((original.astype(float) - decoded.astype(float)) ** 2)
    psnr = 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')

    return {'psnr': psnr, 'mse': mse}


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: pal_decoder_final.py <baseband.bin> <output.png> [frame]")
        sys.exit(1)

    baseband_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    data = np.fromfile(baseband_file, dtype=np.int16)
    samples_per_frame = SAMPLES_PER_LINE * LINES_PER_FRAME

    frame_start = frame_num * samples_per_frame
    field_samples = SAMPLES_PER_LINE * 312
    field_data = data[frame_start:frame_start + field_samples]

    decoder = PALDecoderFinal()
    decoded = decoder.decode_field(field_data, frame_num)

    img = Image.fromarray(decoded)
    img.save(output_file)
    print(f"Saved {output_file}")

    # Show PAL switch pattern
    print(f"\nPAL switch pattern for frame {frame_num}:")
    for line in range(FIRST_ACTIVE_LINE, FIRST_ACTIVE_LINE + 10):
        pal = -1 if ((frame_num + line) & 1) else 1
        print(f"  Line {line}: pal = {pal:+d}")
