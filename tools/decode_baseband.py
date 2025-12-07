#!/usr/bin/env python3
"""
Baseband Video Decoder for hacktv output
Decodes PAL and NTSC composite video signals from raw baseband files.

The hacktv output format uses INT16 scaling:
- sync_level = config.sync_level * level * INT16_MAX
- blanking_level = config.blanking_level * level * INT16_MAX
- white_level = config.white_level * level * INT16_MAX

For PAL: sync=-9830, blanking=0, white=22937
For NTSC: sync=-9362, blanking=0, white=23405

Author: Claude
License: GPLv3+
"""

import numpy as np
import subprocess
import argparse
import sys
import os
from scipy import signal as scipy_signal

class BasebandDecoder:
    """Decodes PAL/NTSC baseband composite video signals."""

    INT16_MAX = 32767.0

    # PAL 625-line parameters (matching hacktv vid_config_pal)
    PAL_CONFIG = {
        'lines': 625,
        'active_lines': 576,
        'frame_rate': 25.0,
        'line_duration': 64e-6,  # 64 microseconds (1/15625 Hz)
        'active_width': 51.95e-6,
        'active_left': 10.40e-6,
        'hsync_width': 4.70e-6,
        # Signal levels (as fraction of total range)
        'white_level': 0.70,
        'black_level': 0.00,
        'blanking_level': 0.00,
        'sync_level': -0.30,
        # Colour burst
        'burst_left': 5.6e-6,
        'burst_width': 2.25e-6,
        'burst_level': 3.0/7.0,
        'colour_carrier': 4433618.75,
        # Active area
        'first_active_line': 23,
        'interlaced': True,
        # Colour encoding coefficients
        'ev_co': 0.877,
        'eu_co': 0.493,
    }

    # NTSC 525-line parameters (matching hacktv vid_config_ntsc)
    NTSC_CONFIG = {
        'lines': 525,
        'active_lines': 480,
        'frame_rate': 30000.0/1001.0,  # ~29.97
        'line_duration': 63.5555e-6,  # 1/15734.264 Hz
        'active_width': 52.90e-6,
        'active_left': 9.20e-6,
        'hsync_width': 4.70e-6,
        # Signal levels
        'white_level': 100.0/140.0,   # ~0.714
        'black_level': 7.5/140.0,     # ~0.054
        'blanking_level': 0.0,
        'sync_level': -40.0/140.0,    # ~-0.286
        # Colour burst
        'burst_left': 5.3e-6,
        'burst_width': 2.5e-6,
        'burst_level': 0.4,
        'colour_carrier': 3579545.4545,
        # Active area
        'first_active_line': 21,
        'interlaced': True,
        # Colour encoding coefficients
        'ev_co': 0.877,
        'eu_co': 0.493,
    }

    def __init__(self, mode='pal', sample_rate=16000000, output_width=720):
        """Initialize the decoder."""
        self.mode = mode.lower()
        self.sample_rate = sample_rate
        self.output_width = output_width

        if self.mode == 'pal':
            self.config = self.PAL_CONFIG.copy()
        elif self.mode == 'ntsc':
            self.config = self.NTSC_CONFIG.copy()
        else:
            raise ValueError(f"Unknown mode: {mode}")

        # Calculate INT16 signal levels (matching hacktv encoding)
        level = 1.0  # Default level in hacktv
        self.int16_white = self.config['white_level'] * level * self.INT16_MAX
        self.int16_black = self.config['black_level'] * level * self.INT16_MAX
        self.int16_blanking = self.config['blanking_level'] * level * self.INT16_MAX
        self.int16_sync = self.config['sync_level'] * level * self.INT16_MAX

        # Calculate samples per line
        self.samples_per_line = int(self.config['line_duration'] * self.sample_rate)

        # Calculate active region in samples
        self.active_start = int(self.config['active_left'] * self.sample_rate)
        self.active_samples = int(self.config['active_width'] * self.sample_rate)

        # Calculate burst region
        self.burst_start = int(self.config['burst_left'] * self.sample_rate)
        self.burst_samples = int(self.config['burst_width'] * self.sample_rate)

        # Output dimensions
        self.output_height = self.config['active_lines']

        # Sync detection threshold (halfway between sync and blanking)
        self.sync_threshold = (self.int16_sync + self.int16_blanking) / 2

        # Create filters
        self._create_filters()

        print(f"Decoder initialized for {self.mode.upper()}")
        print(f"  Sample rate: {self.sample_rate/1e6:.2f} MHz")
        print(f"  Samples per line: {self.samples_per_line}")
        print(f"  Active samples: {self.active_samples}")
        print(f"  Output: {self.output_width}x{self.output_height}")
        print(f"  Signal levels: sync={self.int16_sync:.0f}, blanking={self.int16_blanking:.0f}, white={self.int16_white:.0f}")

    def _create_filters(self):
        """Create filters for signal processing."""
        nyq = self.sample_rate / 2

        # Lowpass filter for luminance (Y) - ~4.2 MHz cutoff
        y_cutoff = min(4.2e6, nyq * 0.9)
        self.y_filter_b, self.y_filter_a = scipy_signal.butter(4, y_cutoff / nyq, 'low')

        # Lowpass filter for chrominance (U/V) - ~1.3 MHz cutoff
        c_cutoff = min(1.3e6, nyq * 0.9)
        self.c_filter_b, self.c_filter_a = scipy_signal.butter(3, c_cutoff / nyq, 'low')

        # Bandpass filter for colour subcarrier extraction
        fc = self.config['colour_carrier']
        color_bw = 1.3e6
        low_color = max((fc - color_bw) / nyq, 0.01)
        high_color = min((fc + color_bw) / nyq, 0.99)
        if low_color < high_color < 1.0:
            self.color_bp_b, self.color_bp_a = scipy_signal.butter(4, [low_color, high_color], 'band')
            self.has_color_filter = True
        else:
            self.has_color_filter = False

        # Notch filter to remove colour from Y
        notch_width = 0.6e6
        low_notch = max((fc - notch_width) / nyq, 0.01)
        high_notch = min((fc + notch_width) / nyq, 0.99)
        if low_notch < high_notch < 1.0:
            self.notch_b, self.notch_a = scipy_signal.butter(2, [low_notch, high_notch], 'bandstop')
            self.has_notch = True
        else:
            self.has_notch = False

    def _find_line_syncs(self, frame_data):
        """Find horizontal sync positions in frame data."""
        sync_positions = []
        search_start = 0
        min_line_samples = int(self.samples_per_line * 0.85)
        max_line_samples = int(self.samples_per_line * 1.15)

        while search_start < len(frame_data) - self.samples_per_line:
            search_end = min(search_start + max_line_samples, len(frame_data))
            window = frame_data[search_start:search_end]

            # Find minimum (sync tip) in window
            min_idx = np.argmin(window)
            min_val = window[min_idx]

            # Verify it's a valid sync pulse
            if min_val < self.sync_threshold:
                sync_pos = search_start + min_idx
                sync_positions.append(sync_pos)
                search_start = sync_pos + min_line_samples
            else:
                search_start += min_line_samples

        return np.array(sync_positions)

    def _extract_burst_phase(self, line_data):
        """Extract colour burst phase from a line."""
        if len(line_data) < self.burst_start + self.burst_samples:
            return 0.0, 0.0

        burst_region = line_data[self.burst_start:self.burst_start + self.burst_samples].astype(np.float64)

        # Generate reference signals
        fc = self.config['colour_carrier']
        t = np.arange(len(burst_region)) / self.sample_rate

        sin_ref = np.sin(2 * np.pi * fc * t)
        cos_ref = np.cos(2 * np.pi * fc * t)

        # Correlate with reference to find phase
        i_corr = np.sum(burst_region * cos_ref) * 2 / len(burst_region)
        q_corr = np.sum(burst_region * sin_ref) * 2 / len(burst_region)

        phase = np.arctan2(q_corr, i_corr)
        amplitude = np.sqrt(i_corr**2 + q_corr**2)

        return phase, amplitude

    def _decode_line(self, line_data, burst_phase, line_number):
        """Decode a single line to RGB."""
        # Convert to float64 for processing
        signal = line_data.astype(np.float64)

        # Ensure we have enough samples
        if len(signal) < self.active_start + self.active_samples:
            signal = np.pad(signal, (0, self.active_start + self.active_samples - len(signal)))

        # Generate colour carrier references with burst phase correction
        fc = self.config['colour_carrier']
        t = np.arange(len(signal)) / self.sample_rate

        # PAL alternates V phase on alternate lines
        if self.mode == 'pal':
            v_phase_flip = -1 if (line_number % 2) == 1 else 1
        else:
            v_phase_flip = 1

        # Demodulation carriers (phase-locked to burst)
        u_carrier = np.cos(2 * np.pi * fc * t + burst_phase)
        v_carrier = np.sin(2 * np.pi * fc * t + burst_phase) * v_phase_flip

        # Extract chroma signal using bandpass filter
        if self.has_color_filter:
            try:
                chroma = scipy_signal.filtfilt(self.color_bp_b, self.color_bp_a, signal)
            except Exception:
                chroma = np.zeros_like(signal)
        else:
            chroma = np.zeros_like(signal)

        # Demodulate U and V
        u_raw = chroma * u_carrier * 2
        v_raw = chroma * v_carrier * 2

        # Lowpass filter demodulated chroma
        try:
            u_filt = scipy_signal.filtfilt(self.c_filter_b, self.c_filter_a, u_raw)
            v_filt = scipy_signal.filtfilt(self.c_filter_b, self.c_filter_a, v_raw)
        except Exception:
            u_filt = u_raw
            v_filt = v_raw

        # Extract Y by removing chroma (notch filter at colour carrier)
        if self.has_notch:
            try:
                y_signal = scipy_signal.filtfilt(self.notch_b, self.notch_a, signal)
            except Exception:
                y_signal = signal.copy()
        else:
            y_signal = signal.copy()

        # Lowpass filter Y
        try:
            y_signal = scipy_signal.filtfilt(self.y_filter_b, self.y_filter_a, y_signal)
        except Exception:
            pass

        # Extract active region
        y_active = y_signal[self.active_start:self.active_start + self.active_samples]
        u_active = u_filt[self.active_start:self.active_start + self.active_samples]
        v_active = v_filt[self.active_start:self.active_start + self.active_samples]

        # Normalize Y: blanking=0, white=1
        # The signal uses: blanking_level -> black, white_level -> white
        y_range = self.int16_white - self.int16_blanking
        y_norm = (y_active - self.int16_blanking) / y_range
        y_norm = np.clip(y_norm, 0, 1)

        # Normalize U/V
        # Colour amplitude is burst_level * (white - blanking)
        burst_amp = self.config['burst_level'] * y_range
        eu = self.config['eu_co']
        ev = self.config['ev_co']

        # U and V are modulated with specific coefficients
        # Scale factor to convert demodulated values to normalized range
        u_scale = 1.0 / (eu * burst_amp * 2)
        v_scale = 1.0 / (ev * burst_amp * 2)

        u_norm = u_active * u_scale
        v_norm = v_active * v_scale

        # Clip to reasonable range
        u_norm = np.clip(u_norm, -0.5, 0.5)
        v_norm = np.clip(v_norm, -0.5, 0.5)

        # Convert YUV to RGB (ITU-R BT.601)
        r = y_norm + 1.140 * v_norm
        g = y_norm - 0.395 * u_norm - 0.581 * v_norm
        b = y_norm + 2.032 * u_norm

        # Clip and scale to 0-255
        r = np.clip(r * 255, 0, 255).astype(np.uint8)
        g = np.clip(g * 255, 0, 255).astype(np.uint8)
        b = np.clip(b * 255, 0, 255).astype(np.uint8)

        # Resample to output width
        rgb = np.stack([r, g, b], axis=-1)
        return self._resample_line(rgb, self.output_width)

    def _resample_line(self, line_rgb, target_width):
        """Resample a line to target width using linear interpolation."""
        if len(line_rgb) == target_width:
            return line_rgb

        src_indices = np.linspace(0, len(line_rgb) - 1, target_width)
        result = np.zeros((target_width, 3), dtype=np.uint8)

        for c in range(3):
            result[:, c] = np.interp(src_indices, np.arange(len(line_rgb)), line_rgb[:, c])

        return result

    def decode_frame(self, frame_data):
        """Decode a single frame from raw data."""
        sync_positions = self._find_line_syncs(frame_data)

        if len(sync_positions) < self.config['active_lines'] // 2:
            print(f"Warning: Only found {len(sync_positions)} sync pulses")

        frame_rgb = np.zeros((self.output_height, self.output_width, 3), dtype=np.uint8)
        first_active = self.config['first_active_line']

        for output_line in range(self.output_height):
            source_line = first_active + output_line

            if source_line >= len(sync_positions):
                break

            sync_pos = sync_positions[source_line]
            line_end = min(sync_pos + self.samples_per_line, len(frame_data))

            if line_end - sync_pos < self.samples_per_line // 2:
                continue

            line_data = frame_data[sync_pos:line_end]

            if len(line_data) < self.samples_per_line:
                line_data = np.pad(line_data, (0, self.samples_per_line - len(line_data)))

            burst_phase, _ = self._extract_burst_phase(line_data)
            line_rgb = self._decode_line(line_data, burst_phase, source_line)
            frame_rgb[output_line] = line_rgb

        return frame_rgb

    def decode_file(self, input_file, output_file, max_frames=None, progress_interval=10):
        """Decode a baseband file to video."""
        samples_per_frame = self.samples_per_line * self.config['lines']
        file_size = os.path.getsize(input_file)
        total_samples = file_size // 2
        total_frames = total_samples // samples_per_frame

        if max_frames:
            total_frames = min(total_frames, max_frames)

        print(f"Input file: {input_file}")
        print(f"File size: {file_size / 1024 / 1024:.2f} MB")
        print(f"Total frames to decode: {total_frames}")

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-pixel_format', 'rgb24',
            '-video_size', f'{self.output_width}x{self.output_height}',
            '-framerate', str(self.config['frame_rate']),
            '-i', '-',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            output_file
        ]

        print(f"Starting FFmpeg encoder...")

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        with open(input_file, 'rb') as f:
            for frame_num in range(total_frames):
                frame_bytes = f.read(samples_per_frame * 2)
                if len(frame_bytes) < samples_per_frame * 2:
                    print(f"End of file at frame {frame_num}")
                    break

                frame_data = np.frombuffer(frame_bytes, dtype=np.int16)
                frame_rgb = self.decode_frame(frame_data)
                ffmpeg_proc.stdin.write(frame_rgb.tobytes())

                if (frame_num + 1) % progress_interval == 0:
                    pct = (frame_num + 1) / total_frames * 100
                    print(f"Processed frame {frame_num + 1}/{total_frames} ({pct:.1f}%)")

        ffmpeg_proc.stdin.close()
        ffmpeg_proc.wait()

        if ffmpeg_proc.returncode != 0:
            stderr = ffmpeg_proc.stderr.read().decode()
            print(f"FFmpeg warning/error: {stderr[-500:]}")

        print(f"Output saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Decode hacktv baseband video output')
    parser.add_argument('input', help='Input baseband file (int16 raw)')
    parser.add_argument('output', help='Output video file (e.g., output.mp4)')
    parser.add_argument('-m', '--mode', choices=['pal', 'ntsc'], default='pal',
                        help='Video mode (default: pal)')
    parser.add_argument('-s', '--samplerate', type=int, default=16000000,
                        help='Sample rate in Hz (default: 16000000)')
    parser.add_argument('-w', '--width', type=int, default=720,
                        help='Output width (default: 720)')
    parser.add_argument('-n', '--frames', type=int, default=None,
                        help='Maximum frames to decode (None for all)')

    args = parser.parse_args()

    decoder = BasebandDecoder(
        mode=args.mode,
        sample_rate=args.samplerate,
        output_width=args.width
    )

    decoder.decode_file(
        args.input,
        args.output,
        max_frames=args.frames
    )


if __name__ == '__main__':
    main()
