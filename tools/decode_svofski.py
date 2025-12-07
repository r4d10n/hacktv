#!/usr/bin/env python3
"""
PAL decoder adapted from svofski's CRT project.
https://github.com/svofski/CRT

Adapted for hacktv baseband decoding.
"""

import numpy as np
from scipy import signal as scipy_signal
import math

# PAL constants
Fsc = 4433618.75  # subcarrier frequency
Fline = 15625     # line frequency


class Biquad:
    """Biquad filter implementation."""

    def __init__(self):
        self.a0, self.a1, self.a2 = 0, 0, 0
        self.b1, self.b2 = 0, 0
        self.x_1, self.x_2 = 0, 0
        self.y_1, self.y_2 = 0, 0

    def reset(self):
        self.x_1, self.x_2 = 0, 0
        self.y_1, self.y_2 = 0, 0

    def filter(self, x):
        result = (self.a0 * x + self.a1 * self.x_1 + self.a2 * self.x_2
                  - self.b1 * self.y_1 - self.b2 * self.y_2)
        self.x_2 = self.x_1
        self.x_1 = x
        self.y_2 = self.y_1
        self.y_1 = result
        return result

    def filter_array(self, arr):
        """Filter an entire array."""
        output = np.zeros_like(arr)
        for i, x in enumerate(arr):
            output[i] = self.filter(x)
        return output

    def lowpass(self, sample_rate, freq, Q):
        K = math.tan(math.pi * freq / sample_rate)
        norm = 1 / (1 + K / Q + K * K)
        self.a0 = K * K * norm
        self.a1 = 2 * self.a0
        self.a2 = self.a0
        self.b1 = 2 * (K * K - 1) * norm
        self.b2 = (1 - K / Q + K * K) * norm
        return self

    def bandpass(self, sample_rate, freq, Q):
        K = math.tan(math.pi * freq / sample_rate)
        norm = 1.0 / (1 + K / Q + K * K)
        self.a0 = K / Q * norm
        self.a1 = 0.0
        self.a2 = -self.a0
        self.b1 = 2 * (K * K - 1) * norm
        self.b2 = (1 - K / Q + K * K) * norm
        return self

    def notch(self, sample_rate, freq, Q):
        K = math.tan(math.pi * freq / sample_rate)
        norm = 1 / (1 + K / Q + K * K)
        self.a0 = (1 + K * K) * norm
        self.a1 = 2 * (K * K - 1) * norm
        self.a2 = self.a0
        self.b1 = self.a1
        self.b2 = (1 - K / Q + K * K) * norm
        return self


def YUVtoRGB(y, u, v):
    """Convert YUV to RGB."""
    r = y + 1.14 * v
    g = y - 0.396 * u - 0.581 * v
    b = y + 2.029 * u
    return r, g, b


def clamp(p):
    return max(0, min(1.0, p))


class SvofskiDecoder:
    """
    PAL decoder based on svofski's CRT implementation.
    Uses biquad filters for Y/C separation.
    """

    def __init__(self, sample_rate=16000000, output_width=720, output_height=576):
        self.sample_rate = sample_rate
        self.samples_per_line = sample_rate // Fline
        self.output_width = output_width
        self.output_height = output_height

        # Width ratio for carrier phase calculation
        self.width_ratio = self.samples_per_line / (Fsc / Fline)
        self.delta_wt = math.pi / self.width_ratio

        # Create filters
        self._init_filters()

        print(f"Svofski decoder initialized:")
        print(f"  Sample rate: {sample_rate / 1e6:.3f} MHz")
        print(f"  Samples/line: {self.samples_per_line}")
        print(f"  Width ratio: {self.width_ratio:.3f}")

    def _init_filters(self):
        """Initialize the biquad filters."""
        effective_sample_rate = Fsc * self.width_ratio

        # Chroma bandpass filter
        self.chroma_bp = Biquad().bandpass(effective_sample_rate, Fsc, 0.7)

        # Luma notch filter
        self.luma_notch = Biquad().notch(effective_sample_rate, Fsc, 0.7)

        # Chroma output smoothing filters
        self.filter_u = Biquad().lowpass(effective_sample_rate, Fsc * 0.2, 0.7)
        self.filter_v = Biquad().lowpass(effective_sample_rate, Fsc * 0.2, 0.7)

    def _reset_filters(self):
        """Reset filter state for new line."""
        self.chroma_bp.reset()
        self.luma_notch.reset()
        self.filter_u.reset()
        self.filter_v.reset()

    def decode_line(self, line_data, line_number, active_start, active_len):
        """
        Decode a single line of baseband signal to RGB.

        Args:
            line_data: Raw signal for one line (int16 or float)
            line_number: Line number (for PAL phase)
            active_start: Sample offset where active video starts
            active_len: Number of samples in active video

        Returns:
            RGB array of shape (output_width, 3)
        """
        self._reset_filters()

        # Normalize signal to 0-1 range
        signal = line_data.astype(np.float64)
        signal = (signal / 32767.0 + 0.30) / 1.0  # Normalize hacktv range

        # Extract active video region
        active = signal[active_start:active_start + active_len]

        # PAL line phase: alternates +90/-90 degrees
        line_phase = math.pi / 2 if (line_number % 2) == 0 else -math.pi / 2

        # Decode each sample
        output = np.zeros((len(active), 3), dtype=np.float64)

        for t, pal in enumerate(active):
            # Calculate carrier phase
            wt = t * 2 * math.pi / self.width_ratio + line_phase
            sinwt = math.sin(wt)
            coswt = math.cos(wt)

            # Filter to separate chroma
            color = self.chroma_bp.filter(pal)
            y = self.luma_notch.filter(pal)

            # Demodulate U and V with gain boost
            chroma_gain = 8.0  # Boost chroma to compensate for filter losses
            u = color * 2 * sinwt * chroma_gain
            v = color * 2 * coswt * chroma_gain

            # Smooth chroma
            u = self.filter_u.filter(u)
            v = self.filter_v.filter(v)

            # Convert to RGB
            r, g, b = YUVtoRGB(y, u, v)
            output[t] = [clamp(r), clamp(g), clamp(b)]

        # Resample to output width
        if len(output) != self.output_width:
            from scipy.ndimage import zoom
            scale = self.output_width / len(output)
            output = zoom(output, (scale, 1), order=1)

        return (output * 255).astype(np.uint8)

    def decode_field(self, field_data, field_number=0):
        """
        Decode a field to RGB.

        Args:
            field_data: Raw int16 signal for one field
            field_number: 0 or 1

        Returns:
            RGB array of shape (output_height, output_width, 3)
        """
        lines_per_field = 312 if field_number == 0 else 313

        # PAL timing (approximate for 16MHz)
        active_start = int(12.0e-6 * self.sample_rate)  # ~12us from line start
        active_len = int(52.0e-6 * self.sample_rate)    # ~52us active video

        output = np.zeros((self.output_height, self.output_width, 3), dtype=np.uint8)

        # Active lines (skip VBI)
        first_active = 23 if field_number == 0 else 336 - 312

        for out_line in range(self.output_height):
            # Map output line to field line
            field_line = first_active + out_line * lines_per_field // self.output_height

            # Get line data
            line_start = field_line * self.samples_per_line
            line_end = line_start + self.samples_per_line

            if line_end > len(field_data):
                break

            line_data = field_data[line_start:line_end]

            # Decode line
            rgb_line = self.decode_line(line_data, field_line, active_start, active_len)

            if len(rgb_line) >= self.output_width:
                output[out_line] = rgb_line[:self.output_width]

        return output


def main():
    import argparse
    from PIL import Image

    parser = argparse.ArgumentParser(description='Decode PAL baseband using svofski method')
    parser.add_argument('input', help='Input baseband file (int16 raw)')
    parser.add_argument('output', help='Output image file')
    parser.add_argument('-s', '--samplerate', type=int, default=16000000,
                        help='Input sample rate (default: 16000000)')
    parser.add_argument('-n', '--frames', type=int, default=1,
                        help='Number of frames to decode')

    args = parser.parse_args()

    # Load data
    data = np.fromfile(args.input, dtype=np.int16)
    print(f"Loaded {len(data)} samples from {args.input}")

    # Initialize decoder
    decoder = SvofskiDecoder(sample_rate=args.samplerate)

    # Decode first field
    samples_per_line = args.samplerate // Fline
    field_samples = samples_per_line * 312

    field_data = data[:field_samples]
    rgb = decoder.decode_field(field_data, 0)

    # Save
    img = Image.fromarray(rgb)
    img.save(args.output)
    print(f"Saved to {args.output}")


if __name__ == '__main__':
    main()
