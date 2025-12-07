#!/usr/bin/env python3
"""
PAL decoder using the PAL-CRT library.

Resamples hacktv baseband output to PAL-CRT format and decodes.
"""

import numpy as np
import subprocess
import argparse
import os
import ctypes
from scipy import signal as scipy_signal

# PAL-CRT constants (from pal.h)
PAL_CC_LINE = 28375
PAL_CB_FREQ = 4
PAL_HRES = (PAL_CC_LINE * PAL_CB_FREQ) // 100  # 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES

PAL_TOP = 22
PAL_BOT = 311
PAL_LINES = PAL_BOT - PAL_TOP  # 289 active lines

# Timing in nanoseconds
FP_ns = 1600
SYNC_ns = 4700
BW_ns = 800
CB_ns = 2500
BP_ns = 2400
AV_ns = 52000
HB_ns = FP_ns + SYNC_ns + BW_ns + CB_ns + BP_ns
LINE_ns = HB_ns + AV_ns  # ~64000 ns

# Signal levels (IRE)
WHITE_LEVEL = 100
BLACK_LEVEL = 0
SYNC_LEVEL = -40


def resample_line(line_data, src_samples, dst_samples):
    """Resample a single line from src_samples to dst_samples."""
    x_src = np.arange(len(line_data))
    x_dst = np.linspace(0, len(line_data) - 1, dst_samples)
    return np.interp(x_dst, x_src, line_data)


def convert_signal_level(signal_int16):
    """
    Convert hacktv int16 signal to PAL-CRT signed char format.

    hacktv levels (int16):
        sync:  -0.30 * 32767 = -9830
        black:  0.00 * 32767 = 0
        white:  0.70 * 32767 = 22937

    PAL-CRT levels (signed char IRE):
        sync:  -40
        black:  0
        white:  100
    """
    # hacktv signal range
    HACKTV_SYNC = -0.30 * 32767
    HACKTV_WHITE = 0.70 * 32767

    # Convert to 0-1 range based on hacktv levels
    normalized = (signal_int16 - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)

    # Convert to IRE range (-40 to 100)
    ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

    # Clip and convert to signed char
    ire_clipped = np.clip(ire, -128, 127).astype(np.int8)

    return ire_clipped


def resample_field(field_data, src_samples_per_line, src_lines):
    """
    Resample a field from hacktv format to PAL-CRT format.

    Args:
        field_data: int16 array of one field
        src_samples_per_line: hacktv samples per line (1024 at 16MHz)
        src_lines: number of lines in source (312 or 313)

    Returns:
        Resampled field as int8 array (PAL_INPUT_SIZE)
    """
    output = np.zeros(PAL_INPUT_SIZE, dtype=np.int8)

    for line in range(min(src_lines, PAL_VRES)):
        src_start = line * src_samples_per_line
        src_end = src_start + src_samples_per_line

        if src_end > len(field_data):
            break

        line_data = field_data[src_start:src_end].astype(np.float64)

        # Resample to PAL_HRES samples
        resampled = resample_line(line_data, src_samples_per_line, PAL_HRES)

        # Convert signal level
        converted = convert_signal_level(resampled)

        # Store in output
        dst_start = line * PAL_HRES
        output[dst_start:dst_start + PAL_HRES] = converted

    return output


class PALCRTDecoder:
    """Wrapper for PAL-CRT library using the simplified wrapper interface."""

    def __init__(self, lib_path=None, output_width=720, output_height=576):
        """Initialize the decoder."""
        if lib_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            lib_path = os.path.join(script_dir, '..', 'external', 'pal-crt', 'libpal_decode.so')

        if not os.path.exists(lib_path):
            raise RuntimeError(f"PAL-CRT library not found at {lib_path}. "
                             f"Compile with: cd external/pal-crt && "
                             f"gcc -shared -fPIC -O2 -o libpal_decode.so decode_wrapper.c pal.c pal_core.c -lm")

        self.lib = ctypes.CDLL(lib_path)

        # Define function signatures
        self.lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.decode_init.restype = ctypes.c_int

        self.lib.decode_field.argtypes = [
            ctypes.POINTER(ctypes.c_int8),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8)
        ]
        self.lib.decode_field.restype = ctypes.c_int

        self.lib.get_input_size.restype = ctypes.c_int
        self.lib.get_hres.restype = ctypes.c_int
        self.lib.get_vres.restype = ctypes.c_int

        self.lib.decode_cleanup.restype = None

        self.output_width = output_width
        self.output_height = output_height

        # Allocate output buffer (RGB = 3 bytes per pixel)
        self.output_size = output_width * output_height * 3
        self.output_buffer = (ctypes.c_uint8 * self.output_size)()

        # Initialize decoder
        result = self.lib.decode_init(output_width, output_height)
        if result != 0:
            raise RuntimeError("Failed to initialize PAL-CRT decoder")

        # Get library parameters for verification
        lib_input_size = self.lib.get_input_size()
        lib_hres = self.lib.get_hres()
        lib_vres = self.lib.get_vres()

        print(f"PAL-CRT decoder initialized: {output_width}x{output_height}")
        print(f"  Library expects: {lib_hres}x{lib_vres} = {lib_input_size} samples/field")

    def decode_field(self, field_signal):
        """
        Decode a field to RGB.

        Args:
            field_signal: numpy int8 array of PAL_INPUT_SIZE samples

        Returns:
            numpy RGB array of shape (output_height, output_width, 3)
        """
        expected_size = self.lib.get_input_size()
        if len(field_signal) != expected_size:
            raise ValueError(f"Expected {expected_size} samples, got {len(field_signal)}")

        # Ensure contiguous int8 array
        signal_arr = np.ascontiguousarray(field_signal, dtype=np.int8)
        signal_ptr = signal_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))

        # Decode
        result = self.lib.decode_field(signal_ptr, len(signal_arr), self.output_buffer)
        if result != 0:
            raise RuntimeError("Decode failed")

        # Convert output to numpy array
        output = np.ctypeslib.as_array(self.output_buffer)
        rgb = output.reshape((self.output_height, self.output_width, 3)).copy()

        return rgb

    def __del__(self):
        """Cleanup on destruction."""
        if hasattr(self, 'lib'):
            self.lib.decode_cleanup()


def decode_without_library(field_data, output_width=720, output_height=576):
    """
    Simple decoder without PAL-CRT library.
    Uses our existing decoder logic but with resampled input.
    """
    from decode_baseband import ProfessionalDecoder

    # This is a placeholder - would integrate with PAL-CRT
    pass


def main():
    parser = argparse.ArgumentParser(description='Decode PAL baseband using PAL-CRT')
    parser.add_argument('input', help='Input baseband file (int16 raw)')
    parser.add_argument('output', help='Output video/image file')
    parser.add_argument('-s', '--samplerate', type=int, default=16000000,
                        help='Input sample rate (default: 16000000)')
    parser.add_argument('-n', '--frames', type=int, default=1,
                        help='Number of frames to decode')
    parser.add_argument('-w', '--width', type=int, default=720,
                        help='Output width (default: 720)')
    parser.add_argument('-H', '--height', type=int, default=576,
                        help='Output height (default: 576)')
    parser.add_argument('--debug', action='store_true',
                        help='Save debug output')

    args = parser.parse_args()

    # Calculate input parameters
    input_samples_per_line = args.samplerate // 15625  # PAL line rate
    input_lines_per_frame = 625
    input_samples_per_frame = input_samples_per_line * input_lines_per_frame

    print(f"PAL-CRT Decoder")
    print(f"  Input: {args.input}")
    print(f"  Sample rate: {args.samplerate / 1e6:.3f} MHz")
    print(f"  Samples per line: {input_samples_per_line} -> {PAL_HRES}")
    print(f"  Resample ratio: {PAL_HRES / input_samples_per_line:.4f}")

    # Load input data
    data = np.fromfile(args.input, dtype=np.int16)
    print(f"  Loaded {len(data)} samples")

    # Initialize decoder
    try:
        decoder = PALCRTDecoder(output_width=args.width, output_height=args.height)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1

    # Determine output type
    is_video = args.output.lower().endswith(('.mp4', '.avi', '.mkv', '.mov'))
    is_image = args.output.lower().endswith(('.png', '.jpg', '.bmp'))

    if is_video:
        # Video output with ffmpeg
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-pixel_format', 'rgb24',
            '-video_size', f'{args.width}x{args.height}',
            '-framerate', '25',
            '-i', '-',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            args.output
        ]
        ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        ffmpeg = None

    # Process frames
    from PIL import Image

    for frame_num in range(args.frames):
        frame_offset = frame_num * input_samples_per_frame
        if frame_offset + input_samples_per_frame > len(data):
            print(f"End of data at frame {frame_num}")
            break

        # PAL has two fields per frame
        field1_lines = 312
        field2_lines = 313
        field1_samples = input_samples_per_line * field1_lines
        field2_samples = input_samples_per_line * field2_lines

        # Field 1 (odd lines)
        field1_data = data[frame_offset:frame_offset + field1_samples]
        resampled1 = resample_field(field1_data, input_samples_per_line, field1_lines)

        # Decode field 1
        rgb1 = decoder.decode_field(resampled1)

        # Field 2 (even lines)
        field2_offset = frame_offset + field1_samples
        field2_data = data[field2_offset:field2_offset + field2_samples]
        resampled2 = resample_field(field2_data, input_samples_per_line, field2_lines)

        # Decode field 2
        rgb2 = decoder.decode_field(resampled2)

        # Combine fields (interlace)
        # For simplicity, just use field 1 for now
        frame_rgb = rgb1

        if is_video and ffmpeg:
            ffmpeg.stdin.write(frame_rgb.tobytes())
        elif is_image and frame_num == 0:
            img = Image.fromarray(frame_rgb)
            img.save(args.output)
            print(f"  Saved image to {args.output}")

        if (frame_num + 1) % 10 == 0:
            print(f"  Frame {frame_num + 1}/{args.frames}")

    if ffmpeg:
        ffmpeg.stdin.close()
        ffmpeg.wait()
        print(f"  Saved video to {args.output}")

    # Save debug output
    if args.debug:
        debug_path = '/tmp/pal_crt_debug.png'
        if 'rgb1' in dir():
            img = Image.fromarray(rgb1)
            img.save(debug_path)
            print(f"  Saved debug frame to {debug_path}")


if __name__ == '__main__':
    main()
