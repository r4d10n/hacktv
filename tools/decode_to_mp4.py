#!/usr/bin/env python3
"""
Decode PAL baseband frames and convert to compressed MP4.
"""

import numpy as np
from PIL import Image
import ctypes
import os
import subprocess
import tempfile
import shutil

SAMPLE_RATE = 16e6
F_SC = 4433618.75
SAMPLES_PER_LINE = 1024
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * 625

HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767

PAL_HRES = 1135
PAL_VRES = 312
PAL_INPUT_SIZE = PAL_HRES * PAL_VRES

SYNC_LEVEL = -40
WHITE_LEVEL = 100

# Color correction matrix
COLOR_MATRIX = np.array([
    [ 1.0026791,  -1.0288666,   1.0008646],
    [-0.08147726,  0.8675986,   0.1154002],
    [-0.5413261,   2.5849624,  -1.1179323]
])


def resample_to_palcrt(field_data):
    """Resample hacktv 16MHz to PAL-CRT 4*f_sc."""
    resampled = np.zeros(PAL_INPUT_SIZE, dtype=np.int8)

    for line in range(min(312, PAL_VRES)):
        src_start = line * SAMPLES_PER_LINE
        if src_start + SAMPLES_PER_LINE > len(field_data):
            break

        line_data = field_data[src_start:src_start + SAMPLES_PER_LINE].astype(np.float64)
        x_src = np.arange(len(line_data))
        x_dst = np.linspace(0, len(line_data) - 1, PAL_HRES)
        resampled_line = np.interp(x_dst, x_src, line_data)

        normalized = (resampled_line - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)
        resampled[line * PAL_HRES:(line + 1) * PAL_HRES] = np.clip(ire, -128, 127).astype(np.int8)

    return resampled


def apply_color_correction(img):
    """Apply color correction matrix."""
    flat = img.reshape(-1, 3).astype(np.float32)
    transformed = np.dot(flat, COLOR_MATRIX.T)
    return np.clip(transformed, 0, 255).astype(np.uint8).reshape(img.shape)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Decode PAL baseband to MP4')
    parser.add_argument('--frames', type=int, default=1000, help='Number of frames to decode')
    parser.add_argument('--from-end', action='store_true', help='Decode from end of video')
    parser.add_argument('--output', type=str, default='samples/decoded_video.mp4', help='Output MP4 file')
    parser.add_argument('--fps', type=int, default=25, help='Output frame rate')
    args = parser.parse_args()

    print(f"PAL Baseband to MP4 Decoder")
    print("=" * 50)

    # Load PAL-CRT library
    print("\nLoading PAL-CRT library...")
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int]*6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()

    # Load baseband
    print("Loading baseband...")
    baseband = np.fromfile('/tmp/pal_baseband.bin', dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME
    print(f"  Total frames in baseband: {total_frames}")

    # Calculate frame range
    num_frames = min(args.frames, total_frames)
    if args.from_end:
        start_frame = max(0, total_frames - num_frames)
    else:
        start_frame = 0
    end_frame = start_frame + num_frames

    print(f"  Decoding frames {start_frame} to {end_frame-1} ({num_frames} frames)")

    # Create temp directory for frames
    temp_dir = tempfile.mkdtemp(prefix='pal_decode_')
    print(f"  Temp directory: {temp_dir}")

    try:
        # Decode frames
        print(f"\nDecoding {num_frames} frames...")
        for i, fn in enumerate(range(start_frame, end_frame)):
            frame_start = fn * SAMPLES_PER_FRAME
            frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

            # Decode with PAL-CRT
            field_samples = SAMPLES_PER_LINE * 312
            field_data = frame_data[:field_samples]
            resampled = resample_to_palcrt(field_data)
            signal_ptr = resampled.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
            lib.decode_field(signal_ptr, len(resampled), output_buffer)

            decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
            corrected = apply_color_correction(decoded)

            # Save frame
            img = Image.fromarray(corrected)
            img.save(f'{temp_dir}/frame_{i:05d}.png')

            if (i + 1) % 100 == 0:
                print(f"  Decoded {i + 1}/{num_frames} frames...")

        lib.decode_cleanup()

        # Convert to MP4 using ffmpeg
        print(f"\nConverting to MP4...")
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)

        cmd = [
            'ffmpeg', '-y',
            '-framerate', str(args.fps),
            '-i', f'{temp_dir}/frame_%05d.png',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            args.output
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"FFmpeg error: {result.stderr}")
            return 1

        # Get file size
        file_size = os.path.getsize(args.output) / (1024 * 1024)
        print(f"\n{'=' * 50}")
        print(f"SUCCESS!")
        print(f"{'=' * 50}")
        print(f"Output: {args.output}")
        print(f"Frames: {num_frames}")
        print(f"Duration: {num_frames / args.fps:.1f} seconds")
        print(f"File size: {file_size:.1f} MB")

    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir)
        print(f"Cleaned up temp files")

    return 0


if __name__ == '__main__':
    exit(main())
