#!/usr/bin/env python3
"""
Working PAL baseband decoder for hacktv output.
Uses empirically-determined per-line phase correction.
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import argparse


def find_syncs(data, samples_per_line):
    """Find horizontal sync positions."""
    sync_threshold = -0.15 * 32767
    sync_positions = []
    search_pos = 0
    max_syncs = len(data) // samples_per_line + 100

    while search_pos < len(data) - samples_per_line and len(sync_positions) < max_syncs:
        window = data[search_pos:search_pos+int(samples_per_line*1.1)]
        min_idx = np.argmin(window)
        if window[min_idx] < sync_threshold:
            sync_positions.append(search_pos + min_idx)
            search_pos = search_pos + min_idx + int(samples_per_line * 0.9)
        else:
            search_pos += int(samples_per_line * 0.9)

    return sync_positions


def decode_pal_frame(data, sample_rate=16e6):
    """Decode a single PAL frame from baseband data."""

    fc = 4433618.75
    samples_per_line = int(round(sample_rate / 15625.0))
    lines = 625
    samples_per_frame = samples_per_line * lines

    # Get frame data
    frame_data = data[:samples_per_frame].astype(np.float64)

    # Find syncs
    sync_positions = find_syncs(data[:samples_per_frame], samples_per_line)

    if len(sync_positions) < 400:
        print(f"Warning: only found {len(sync_positions)} syncs")
        return None

    # Filter design
    nyq = sample_rate / 2
    bpf_b, bpf_a = scipy_signal.butter(4, [(fc-1.3e6)/nyq, (fc+1.3e6)/nyq], 'band')
    notch_b, notch_a = scipy_signal.butter(3, [(fc-0.8e6)/nyq, (fc+0.8e6)/nyq], 'bandstop')
    uv_lpf_b, uv_lpf_a = scipy_signal.butter(4, 1.3e6/nyq, 'low')

    # Timing
    active_start = int(10.4e-6 * sample_rate)
    active_width = int(51.95e-6 * sample_rate)
    burst_start = int(5.6e-6 * sample_rate)
    burst_len = int(2.25e-6 * sample_rate)

    # Output
    output_height = 576
    output_width = 720
    output = np.zeros((output_height, output_width, 3), dtype=np.uint8)

    # Field parameters
    field1_start = 23
    field2_start = 336
    lines_per_field = 288

    # Pre-calculate time array
    t = np.arange(samples_per_line) / sample_rate

    for field_idx, (field_start, field_parity) in enumerate([(field1_start, 0), (field2_start, 1)]):
        for fline in range(lines_per_field):
            source_line = field_start + fline
            output_row = fline * 2 + field_parity

            if output_row >= output_height or source_line >= len(sync_positions):
                continue

            sync_pos = sync_positions[source_line]
            line_end = sync_pos + samples_per_line

            if line_end > len(frame_data):
                continue

            line_data = frame_data[sync_pos:line_end]

            # Measure burst phase
            burst = line_data[burst_start:burst_start+burst_len]
            burst = burst - np.mean(burst)
            t_burst = np.arange(len(burst)) / sample_rate
            i_corr = np.sum(burst * np.cos(2*np.pi*fc*t_burst)) * 2 / len(burst)
            q_corr = np.sum(burst * np.sin(2*np.pi*fc*t_burst)) * 2 / len(burst)
            burst_phase = np.arctan2(q_corr, i_corr)

            # Y/C separation
            chroma = scipy_signal.filtfilt(bpf_b, bpf_a, line_data)
            luma = scipy_signal.filtfilt(notch_b, notch_a, line_data)

            # PAL sign and phase correction
            pal_sign = 1.0 if (source_line % 2) == 0 else -1.0

            # Optimal demodulation phase = burst_phase + 187° + 44° * pal_sign
            # But we also use pal_sign on v_carrier, so the formula becomes simpler
            # When optimizing for line 200 (pal_sign=+1), optimal was 153°
            # When optimizing for line 199 (pal_sign=-1), optimal was 245°
            # The burst phase was -77.5° for line 200 and 103.1° for line 199
            # So: optimal = burst_phase + offset
            # Line 200: 153 = -77.5 + offset => offset = 230.5°
            # Line 199: 245 = 103.1 + offset => offset = 141.9°
            # This changes with pal_sign, but we're applying pal_sign on v_carrier
            # So let's use: demod_phase = burst_phase + offset
            # where offset varies based on which type of line

            if pal_sign > 0:
                # Even lines: offset ~230.5°
                offset = np.deg2rad(230.5)
            else:
                # Odd lines: offset ~141.9°
                offset = np.deg2rad(141.9)

            demod_phase = burst_phase + offset
            omega_t = 2 * np.pi * fc * t + demod_phase

            # Demodulate
            u_raw = chroma * np.sin(omega_t) * 2
            v_raw = chroma * np.cos(omega_t) * pal_sign * 2

            u = scipy_signal.filtfilt(uv_lpf_b, uv_lpf_a, u_raw)
            v = scipy_signal.filtfilt(uv_lpf_b, uv_lpf_a, v_raw)

            # Extract active region
            luma_active = luma[active_start:active_start+active_width]
            u_active = u[active_start:active_start+active_width]
            v_active = v[active_start:active_start+active_width]

            # Convert to RGB
            y_norm = np.clip(luma_active / (0.70 * 32767), 0, 1)
            y_range = 0.70 * 32767
            chroma_scale = 2.0

            b_minus_y = u_active * chroma_scale / (0.493 * y_range)
            r_minus_y = v_active * chroma_scale / (0.877 * y_range)

            r = np.clip((y_norm + r_minus_y) * 255, 0, 255)
            b = np.clip((y_norm + b_minus_y) * 255, 0, 255)
            g = np.clip(((y_norm - 0.299*(y_norm+r_minus_y) - 0.114*(y_norm+b_minus_y)) / 0.587) * 255, 0, 255)

            # Resample to output width
            if len(r) != output_width:
                x_src = np.linspace(0, len(r)-1, output_width)
                r = np.interp(x_src, np.arange(len(r)), r)
                g = np.interp(x_src, np.arange(len(g)), g)
                b = np.interp(x_src, np.arange(len(b)), b)

            output[output_row, :, 0] = r.astype(np.uint8)
            output[output_row, :, 1] = g.astype(np.uint8)
            output[output_row, :, 2] = b.astype(np.uint8)

    return output


def main():
    parser = argparse.ArgumentParser(description='Decode PAL baseband video')
    parser.add_argument('input', help='Input baseband file (int16 raw)')
    parser.add_argument('output', help='Output image or video file')
    parser.add_argument('-s', '--samplerate', type=float, default=16e6,
                        help='Sample rate in Hz (default: 16000000)')
    parser.add_argument('-n', '--frames', type=int, default=1,
                        help='Number of frames to decode')

    args = parser.parse_args()

    data = np.fromfile(args.input, dtype=np.int16)
    print(f"Loaded {len(data)} samples")

    samples_per_frame = 1024 * 625  # Assuming 16MHz

    if args.frames == 1:
        frame = decode_pal_frame(data, args.samplerate)
        if frame is not None:
            Image.fromarray(frame).save(args.output)
            print(f"Saved to {args.output}")
    else:
        import subprocess

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo', '-pixel_format', 'rgb24',
            '-video_size', '720x576', '-framerate', '25',
            '-i', '-',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
            '-pix_fmt', 'yuv420p', args.output
        ]

        ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

        for i in range(args.frames):
            frame_start = i * samples_per_frame
            frame_data = data[frame_start:frame_start + samples_per_frame]
            if len(frame_data) < samples_per_frame:
                break

            frame = decode_pal_frame(frame_data, args.samplerate)
            if frame is not None:
                ffmpeg.stdin.write(frame.tobytes())

            if (i + 1) % 10 == 0:
                print(f"Decoded frame {i+1}/{args.frames}")

        ffmpeg.stdin.close()
        ffmpeg.wait()
        print(f"Saved to {args.output}")


if __name__ == '__main__':
    main()
