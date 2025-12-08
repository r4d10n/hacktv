#!/usr/bin/env python3
"""
Decode hacktv signal to YUV and re-encode with PAL-CRT's encoder.

This approach bypasses the signal format differences by:
1. Extracting Y, U, V from hacktv's 16MHz signal using burst-locked demodulation
2. Converting to RGB
3. Using PAL-CRT's encoder to create a proper signal
4. Decoding with PAL-CRT

This ensures the signal format is exactly what PAL-CRT expects.
"""

import numpy as np
from scipy import signal as scipy_signal
from scipy.interpolate import interp1d
from PIL import Image
import ctypes
import sys
import os

# hacktv parameters
HACKTV_SR = 16e6
HACKTV_HRES = 1024
F_SC = 4433618.75

# PAL-CRT parameters
PALCRT_SR = F_SC * 4
PALCRT_HRES = 1135
PALCRT_VRES = 312

# hacktv levels
HACKTV_SYNC = int(-0.30 * 32767)  # -9830
HACKTV_BLACK = 0
HACKTV_WHITE = int(0.70 * 32767)  # 22937

# Timing in hacktv samples (at 16 MHz)
HACKTV_BURST_START = 90
HACKTV_BURST_END = 126
HACKTV_ACTIVE_START = 210  # ~13µs
HACKTV_ACTIVE_END = 970   # ~60µs


def extract_burst_phase(line_data):
    """Extract burst phase from a line."""
    omega = 2 * np.pi * F_SC / HACKTV_SR

    burst = line_data[HACKTV_BURST_START:HACKTV_BURST_END].astype(np.float64)
    t = np.arange(HACKTV_BURST_START, HACKTV_BURST_END)

    burst_sin = np.mean(burst * np.sin(t * omega))
    burst_cos = np.mean(burst * np.cos(t * omega))

    return np.arctan2(burst_sin, burst_cos)


def demodulate_chroma(line_data, burst_phase):
    """Demodulate chroma using burst-locked carriers."""
    omega = 2 * np.pi * F_SC / HACKTV_SR
    t = np.arange(len(line_data))

    # Burst phase should be at 135° in PAL
    # Adjust carrier phase so burst maps to 135°
    phase_correction = np.deg2rad(135) - burst_phase

    # Create carriers locked to burst
    cos_carrier = np.cos(t * omega + phase_correction)
    sin_carrier = np.sin(t * omega + phase_correction)

    # Demodulate
    line_float = line_data.astype(np.float64)

    # Bandpass filter to extract chroma
    low = (F_SC - 1.3e6) / (HACKTV_SR / 2)
    high = (F_SC + 1.3e6) / (HACKTV_SR / 2)
    b, a = scipy_signal.butter(3, [low, high], btype='band')
    chroma = scipy_signal.filtfilt(b, a, line_float)

    # Demodulate to get U and V
    u_raw = chroma * cos_carrier * 2
    v_raw = chroma * sin_carrier * 2

    # Low-pass filter to remove carrier frequency
    cutoff = 1.3e6 / (HACKTV_SR / 2)
    b, a = scipy_signal.butter(3, cutoff, btype='low')
    u = scipy_signal.filtfilt(b, a, u_raw)
    v = scipy_signal.filtfilt(b, a, v_raw)

    return u, v


def extract_luma(line_data):
    """Extract luma with lowpass filter."""
    cutoff = 4.0e6 / (HACKTV_SR / 2)
    b, a = scipy_signal.butter(4, cutoff, btype='low')
    return scipy_signal.filtfilt(b, a, line_data.astype(np.float64))


def yuv_to_rgb(y, u, v):
    """Convert YUV to RGB (BT.601)."""
    r = y + 1.140 * v
    g = y - 0.395 * u - 0.581 * v
    b = y + 2.032 * u

    return r, g, b


def decode_hacktv_field(field_data):
    """Decode a hacktv field to RGB image."""
    # Output dimensions
    out_width = 720
    out_height = PALCRT_VRES

    rgb_image = np.zeros((out_height, out_width, 3), dtype=np.uint8)

    # Active video samples
    active_samples = HACKTV_ACTIVE_END - HACKTV_ACTIVE_START
    samples_per_pixel = active_samples / out_width

    for line in range(out_height):
        src_start = line * HACKTV_HRES
        if src_start + HACKTV_HRES > len(field_data):
            break

        line_data = field_data[src_start:src_start + HACKTV_HRES]

        # Extract burst phase
        burst_phase = extract_burst_phase(line_data)

        # Extract luma
        y = extract_luma(line_data)

        # Demodulate chroma
        u, v = demodulate_chroma(line_data, burst_phase)

        # PAL V-switch: V is inverted on alternate lines
        if line % 2 == 1:
            v = -v

        # Normalize luma to 0-1
        y_norm = (y - HACKTV_BLACK) / (HACKTV_WHITE - HACKTV_BLACK)

        # Scale U, V (empirically determined scaling)
        u_scale = 4500  # Adjust based on hacktv encoding
        v_scale = 4500
        u_norm = u / u_scale
        v_norm = v / v_scale

        # Resample to output width
        x_out = np.linspace(HACKTV_ACTIVE_START, HACKTV_ACTIVE_END - 1, out_width)
        x_in = np.arange(HACKTV_HRES)

        y_interp = interp1d(x_in, y_norm, bounds_error=False, fill_value=0)(x_out)
        u_interp = interp1d(x_in, u_norm, bounds_error=False, fill_value=0)(x_out)
        v_interp = interp1d(x_in, v_norm, bounds_error=False, fill_value=0)(x_out)

        # Convert to RGB
        r, g, b = yuv_to_rgb(y_interp, u_interp, v_interp)

        # Scale and clip
        rgb_image[line, :, 0] = np.clip(r * 255, 0, 255).astype(np.uint8)
        rgb_image[line, :, 1] = np.clip(g * 255, 0, 255).astype(np.uint8)
        rgb_image[line, :, 2] = np.clip(b * 255, 0, 255).astype(np.uint8)

    return rgb_image


def encode_and_decode_with_palcrt(rgb_image, saturation=30, contrast=180):
    """Encode with PAL-CRT and decode back."""
    lib_path = os.path.join(os.path.dirname(__file__), '../external/pal-crt/libpal_decode.so')
    lib = ctypes.CDLL(lib_path)

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.roundtrip_test.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_uint8), ctypes.c_int]
    lib.roundtrip_test.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    height, width, _ = rgb_image.shape

    lib.decode_init(width, height)
    lib.decode_set_params(saturation, 0, contrast, 0, 100, 1)

    rgb_ptr = rgb_image.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
    output = np.zeros_like(rgb_image)
    output_ptr = output.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))

    lib.roundtrip_test(rgb_ptr, width, height, output_ptr, 0)

    lib.decode_cleanup()
    return output


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Decode hacktv to YUV and re-encode with PAL-CRT')
    parser.add_argument('--input', type=str, default='/tmp/color_calibration/colorbars_pal.bin')
    parser.add_argument('--frame', type=int, default=15)
    parser.add_argument('--output', type=str, default='/tmp/yuv_palcrt.png')
    parser.add_argument('--saturation', type=int, default=30)
    parser.add_argument('--contrast', type=int, default=180)
    parser.add_argument('--no-roundtrip', action='store_true', help='Skip PAL-CRT roundtrip')
    args = parser.parse_args()

    print("hacktv YUV → PAL-CRT Decoder")
    print("=" * 50)

    # Load baseband using memory mapping for large files
    print(f"Loading {args.input}...")
    file_size = os.path.getsize(args.input)
    frame_samples = HACKTV_HRES * 625
    total_frames = file_size // (frame_samples * 2)  # 2 bytes per int16
    print(f"  Total frames: {total_frames}")

    if args.frame >= total_frames:
        print(f"Error: Frame {args.frame} out of range")
        return 1

    # Use memory mapping for efficient random access
    baseband = np.memmap(args.input, dtype=np.int16, mode='r')

    # Extract field
    frame_start = args.frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = np.array(baseband[frame_start:frame_start + field_samples])  # Copy to regular array

    # Decode to RGB
    print(f"Decoding frame {args.frame} to RGB...")
    rgb_decoded = decode_hacktv_field(field_data)

    if args.no_roundtrip:
        output = rgb_decoded
    else:
        # Re-encode and decode with PAL-CRT
        print("Re-encoding with PAL-CRT...")
        output = encode_and_decode_with_palcrt(rgb_decoded, args.saturation, args.contrast)

    # Save
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    Image.fromarray(output).save(args.output)
    print(f"Saved: {args.output}")

    # Also save intermediate RGB if doing roundtrip
    if not args.no_roundtrip:
        intermediate_path = args.output.replace('.png', '_intermediate.png')
        Image.fromarray(rgb_decoded).save(intermediate_path)
        print(f"Saved intermediate: {intermediate_path}")

    # Sample colors
    print("\nColor samples (line 150):")
    bar_width = 80
    positions = [60, 140, 220, 300, 380, 460, 540, 620]
    names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']

    for name, x in zip(names, positions):
        region = output[140:160, x-10:x+10]
        mean_rgb = np.mean(region, axis=(0, 1)).astype(int)
        print(f"  {name:10s}: RGB = {tuple(mean_rgb)}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
