#!/usr/bin/env python3
"""
Decode hacktv PAL using burst-locked YUV extraction, then apply PAL-CRT
for CRT aesthetic filtering.

Pipeline:
1. Decode hacktv -> RGB using burst-locked YUV decoder (correct colors)
2. Scale to 576 lines for PAL-CRT compatibility
3. Encode with PAL-CRT encoder
4. Decode with PAL-CRT decoder (adds CRT aesthetic)
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

# Signal levels
HACKTV_SYNC = int(-0.30 * 32767)
HACKTV_BLACK = 0
HACKTV_WHITE = int(0.70 * 32767)

# Timing
HACKTV_BURST_START = 90
HACKTV_BURST_END = 126
HACKTV_ACTIVE_START = 210
HACKTV_ACTIVE_END = 970


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

    # Phase correction to align burst to 135°
    phase_correction = np.deg2rad(135) - burst_phase

    # Create locked carriers
    cos_carrier = np.cos(t * omega + phase_correction)
    sin_carrier = np.sin(t * omega + phase_correction)

    # Bandpass filter for chroma
    line_float = line_data.astype(np.float64)
    low = (F_SC - 1.3e6) / (HACKTV_SR / 2)
    high = (F_SC + 1.3e6) / (HACKTV_SR / 2)
    b, a = scipy_signal.butter(3, [low, high], btype='band')
    chroma = scipy_signal.filtfilt(b, a, line_float)

    # Demodulate
    u_raw = chroma * cos_carrier * 2
    v_raw = chroma * sin_carrier * 2

    # Lowpass filter
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


def decode_hacktv_to_rgb(field_data):
    """Decode hacktv field to RGB using burst-locked YUV."""
    out_width = 720
    out_height = PALCRT_VRES

    rgb_image = np.zeros((out_height, out_width, 3), dtype=np.uint8)

    for line in range(out_height):
        src_start = line * HACKTV_HRES
        if src_start + HACKTV_HRES > len(field_data):
            break

        line_data = field_data[src_start:src_start + HACKTV_HRES]

        # Extract components
        burst_phase = extract_burst_phase(line_data)
        y = extract_luma(line_data)
        u, v = demodulate_chroma(line_data, burst_phase)

        # PAL V-switch
        if line % 2 == 1:
            v = -v

        # Normalize
        y_norm = (y - HACKTV_BLACK) / (HACKTV_WHITE - HACKTV_BLACK)
        u_scale = 4500
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

        rgb_image[line, :, 0] = np.clip(r * 255, 0, 255).astype(np.uint8)
        rgb_image[line, :, 1] = np.clip(g * 255, 0, 255).astype(np.uint8)
        rgb_image[line, :, 2] = np.clip(b * 255, 0, 255).astype(np.uint8)

    return rgb_image


def apply_crt_filter(rgb_image, saturation=100, contrast=180):
    """Apply PAL-CRT filter for CRT aesthetic."""
    lib_path = os.path.join(os.path.dirname(__file__), '../external/pal-crt/libpal_decode.so')
    lib = ctypes.CDLL(lib_path)

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.roundtrip_test.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_uint8), ctypes.c_int]
    lib.roundtrip_test.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    # Scale to 576 lines for PAL-CRT
    height, width, _ = rgb_image.shape
    if height != 576:
        img_pil = Image.fromarray(rgb_image)
        img_pil = img_pil.resize((width, 576), Image.Resampling.BILINEAR)
        rgb_scaled = np.array(img_pil)
    else:
        rgb_scaled = rgb_image

    lib.decode_init(720, 576)
    lib.decode_set_params(saturation, 0, contrast, 0, 100, 1)

    rgb_ptr = rgb_scaled.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
    output = np.zeros_like(rgb_scaled)
    output_ptr = output.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))

    lib.roundtrip_test(rgb_ptr, 720, 576, output_ptr, 0)

    lib.decode_cleanup()
    return output


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Decode hacktv with CRT filter')
    parser.add_argument('--input', type=str, required=True)
    parser.add_argument('--frame', type=int, default=0)
    parser.add_argument('--output', type=str, required=True)
    parser.add_argument('--saturation', type=int, default=100)
    parser.add_argument('--contrast', type=int, default=180)
    parser.add_argument('--no-crt', action='store_true', help='Skip CRT filter')
    args = parser.parse_args()

    print("hacktv PAL Decoder with CRT Filter")
    print("=" * 50)

    # Load baseband
    print(f"Loading {args.input}...")
    file_size = os.path.getsize(args.input)
    frame_samples = HACKTV_HRES * 625
    total_frames = file_size // (frame_samples * 2)
    print(f"  Total frames: {total_frames}")

    if args.frame >= total_frames:
        print(f"Error: Frame {args.frame} out of range")
        return 1

    baseband = np.memmap(args.input, dtype=np.int16, mode='r')

    # Extract field
    frame_start = args.frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = np.array(baseband[frame_start:frame_start + field_samples])

    # Decode to RGB
    print(f"Decoding frame {args.frame}...")
    rgb_decoded = decode_hacktv_to_rgb(field_data)

    if args.no_crt:
        output = rgb_decoded
    else:
        # Apply CRT filter
        print("Applying CRT filter...")
        output = apply_crt_filter(rgb_decoded, args.saturation, args.contrast)

    # Save
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    Image.fromarray(output).save(args.output)
    print(f"Saved: {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
