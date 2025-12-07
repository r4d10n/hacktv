#!/usr/bin/env python3
"""
PAL Decoder V3 - Bandpass chroma extraction with proper V-switch

Key insight: Don't use comb filter for chroma extraction as it complicates
V-switch handling. Instead:
1. Extract Y using notch filter (removes chroma from Y)
2. Extract chroma using bandpass filter
3. Demodulate each line with correct PAL switch
4. Use PAL delay line to average U/V (handles phase errors)
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image

# Constants
PAL_HRES = 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES
PAL_TOP = 22
PAL_BOT = 311
PAL_LINES = PAL_BOT - PAL_TOP

def ns2pos(ns):
    LINE_ns = 64000
    return (ns * PAL_HRES) // LINE_ns

CB_BEG = ns2pos(1600 + 4700 + 800)
CB_LEN = 40
AV_BEG = ns2pos(12000)
AV_LEN = ns2pos(52000)

SYNC_LEVEL = -40
WHITE_LEVEL = 100


class PALDecoderV3:
    def __init__(self, output_width=720, output_height=576):
        self.output_width = output_width
        self.output_height = output_height

        fs = 17734475  # 4 * f_sc
        nyq = fs / 2
        fc = 4433618.75

        # Y lowpass: 5.5 MHz
        self.y_lpf_b, self.y_lpf_a = scipy_signal.butter(6, 5.5e6 / nyq, 'low')

        # Notch filter to remove chroma from Y
        self.notch_b, self.notch_a = scipy_signal.butter(
            4, [(fc - 1.0e6) / nyq, (fc + 1.0e6) / nyq], 'bandstop'
        )

        # Chroma bandpass
        self.chroma_bpf_b, self.chroma_bpf_a = scipy_signal.butter(
            4, [(fc - 1.3e6) / nyq, (fc + 1.3e6) / nyq], 'band'
        )

        # UV lowpass
        self.uv_lpf_b, self.uv_lpf_a = scipy_signal.butter(4, 1.3e6 / nyq, 'low')

    def _extract_y_bandpass(self, line_data):
        """Extract Y using notch filter to remove chroma."""
        y = scipy_signal.filtfilt(self.notch_b, self.notch_a, line_data)
        y = scipy_signal.filtfilt(self.y_lpf_b, self.y_lpf_a, y)
        return y

    def _extract_chroma_bandpass(self, line_data):
        """Extract chroma using bandpass filter."""
        return scipy_signal.filtfilt(self.chroma_bpf_b, self.chroma_bpf_a, line_data)

    def _demodulate(self, chroma, line_idx):
        """
        Demodulate chroma.

        hacktv encodes: chroma = V * cos(wt) * pal + U * sin(wt)
        where pal = -1 if (line & 1) else +1

        To demodulate:
        - Multiply by sin(wt) -> gives U (after lowpass)
        - Multiply by cos(wt) -> gives V * pal (after lowpass)
        - Then apply pal correction to get V
        """
        n = len(chroma)
        t = np.arange(n)

        # Carriers at 4*f_sc
        cos_wt = np.cos(t * np.pi / 2)
        sin_wt = np.sin(t * np.pi / 2)

        # PAL switch: alternates per line
        pal = -1 if (line_idx & 1) else 1

        # Demodulate
        u_raw = chroma * sin_wt * 2
        v_raw = chroma * cos_wt * 2  # This gives V * pal

        # Lowpass
        u = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, u_raw)
        v = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, v_raw)

        # Apply PAL correction to V
        v = v * pal

        return u, v

    def _pal_delay_average(self, u_curr, v_curr, u_prev, v_prev):
        """
        PAL delay line.

        The V component was already corrected for PAL switch during demodulation,
        so both U and V can be simply averaged.
        """
        if u_prev is None:
            return u_curr, v_curr
        return (u_curr + u_prev) / 2, (v_curr + v_prev) / 2

    def _yuv_to_rgb(self, y, u, v):
        """Convert YUV to RGB."""
        y_norm = np.clip(y / 100.0, 0, 1)

        # Scale based on encoding coefficients (eu_co=0.493, ev_co=0.877)
        # and empirical tuning
        u_scale = u / 20.0
        v_scale = v / 20.0

        r = y_norm + 1.140 * v_scale
        g = y_norm - 0.581 * v_scale - 0.395 * u_scale
        b = y_norm + 2.028 * u_scale

        return r, g, b

    def decode_field(self, field_signal, frame=0):
        """Decode a PAL field."""
        if len(field_signal) != PAL_INPUT_SIZE:
            raise ValueError(f"Expected {PAL_INPUT_SIZE} samples")

        field = field_signal.reshape((PAL_VRES, PAL_HRES)).astype(np.float64)
        output = np.zeros((PAL_LINES, self.output_width, 3), dtype=np.uint8)

        prev_u = None
        prev_v = None

        for line_idx in range(PAL_TOP, PAL_BOT):
            out_idx = line_idx - PAL_TOP
            line_data = field[line_idx]

            # Extract Y and chroma using bandpass filters
            y = self._extract_y_bandpass(line_data)
            chroma = self._extract_chroma_bandpass(line_data)

            # Demodulate
            u, v = self._demodulate(chroma, line_idx)

            # PAL delay averaging
            u_avg, v_avg = self._pal_delay_average(u, v, prev_u, prev_v)
            prev_u = u.copy()
            prev_v = v.copy()

            # Extract active video
            y_active = y[AV_BEG:AV_BEG + AV_LEN]
            u_active = u_avg[AV_BEG:AV_BEG + AV_LEN]
            v_active = v_avg[AV_BEG:AV_BEG + AV_LEN]

            # Convert to RGB
            r, g, b = self._yuv_to_rgb(y_active, u_active, v_active)

            r = np.clip(r * 255, 0, 255).astype(np.uint8)
            g = np.clip(g * 255, 0, 255).astype(np.uint8)
            b = np.clip(b * 255, 0, 255).astype(np.uint8)

            # Resample
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


def resample_hacktv_to_palcrt(data, src_samples_per_line=1024, src_lines=312):
    output = np.zeros(PAL_INPUT_SIZE, dtype=np.int8)
    HACKTV_SYNC = -0.30 * 32767
    HACKTV_WHITE = 0.70 * 32767

    for line in range(min(src_lines, PAL_VRES)):
        src_start = line * src_samples_per_line
        src_end = src_start + src_samples_per_line
        if src_end > len(data):
            break

        line_data = data[src_start:src_end].astype(np.float64)
        x_src = np.arange(len(line_data))
        x_dst = np.linspace(0, len(line_data) - 1, PAL_HRES)
        resampled = np.interp(x_dst, x_src, line_data)

        normalized = (resampled - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)
        output[line * PAL_HRES:(line + 1) * PAL_HRES] = np.clip(ire, -128, 127).astype(np.int8)

    return output


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: pal_decoder_v3.py <baseband.bin> <output.png> [frame]")
        sys.exit(1)

    baseband_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_num = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    data = np.fromfile(baseband_file, dtype=np.int16)
    samples_per_line = 1024
    samples_per_frame = samples_per_line * 625

    frame_start = frame_num * samples_per_frame
    field_samples = samples_per_line * 312
    field_data = data[frame_start:frame_start + field_samples]

    resampled = resample_hacktv_to_palcrt(field_data, samples_per_line, 312)

    decoder = PALDecoderV3()
    decoded = decoder.decode_field(resampled, frame_num)

    img = Image.fromarray(decoded)
    img.save(output_file)
    print(f"Saved {output_file}")
