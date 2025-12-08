#!/usr/bin/env python3
"""
Resample hacktv signal to PAL-CRT format with chroma phase correction.

The key fix: Apply a phase rotation to the chroma signal to correct the
hue offset caused by timing/phase differences between hacktv and PAL-CRT.
"""

import numpy as np
from scipy import signal as scipy_signal
from scipy.interpolate import interp1d
from PIL import Image
import ctypes
import sys
import os

# Parameters
HACKTV_SR = 16e6
HACKTV_HRES = 1024
F_SC = 4433618.75
PALCRT_SR = F_SC * 4  # 17.73 MHz
PALCRT_HRES = 1135
PALCRT_VRES = 312

HACKTV_SYNC = -0.30 * 32767
HACKTV_WHITE = 0.70 * 32767
SYNC_LEVEL = -40
WHITE_LEVEL = 100


def extract_chroma(signal, sample_rate):
    """Extract chroma component using bandpass filter around f_sc."""
    # Bandpass around 4.43 MHz ± 1 MHz
    low = (F_SC - 1e6) / (sample_rate / 2)
    high = (F_SC + 1e6) / (sample_rate / 2)
    low = max(0.001, min(0.999, low))
    high = max(0.001, min(0.999, high))

    if low >= high:
        return np.zeros_like(signal)

    b, a = scipy_signal.butter(4, [low, high], btype='band')
    return scipy_signal.filtfilt(b, a, signal)


def extract_luma(signal, sample_rate):
    """Extract luma component using lowpass filter."""
    cutoff = 3.5e6 / (sample_rate / 2)
    cutoff = min(0.999, cutoff)
    b, a = scipy_signal.butter(4, cutoff, btype='low')
    return scipy_signal.filtfilt(b, a, signal)


def rotate_chroma_phase(chroma, phase_deg, sample_rate):
    """
    Rotate the phase of the chroma signal by phase_deg degrees.

    Uses Hilbert transform to get the analytic signal, then rotates.
    """
    if np.max(np.abs(chroma)) < 1:
        return chroma

    # Get analytic signal
    analytic = scipy_signal.hilbert(chroma)

    # Rotate by phase
    phase_rad = np.deg2rad(phase_deg)
    rotated = np.real(analytic * np.exp(1j * phase_rad))

    return rotated


def resample_line_with_phase_correction(hacktv_line, line_num, phase_correction_deg):
    """
    Resample a single line with burst alignment and phase correction.
    """
    # Time offset to align burst positions
    hacktv_burst_time = 5.6e-6
    palcrt_burst_time = 7.1e-6
    time_offset = palcrt_burst_time - hacktv_burst_time

    # Extract luma and chroma from hacktv signal
    line_float = hacktv_line.astype(float)
    luma = extract_luma(line_float, HACKTV_SR)
    chroma = line_float - luma

    # Apply phase rotation to chroma
    if abs(phase_correction_deg) > 0.1:
        chroma = rotate_chroma_phase(chroma, phase_correction_deg, HACKTV_SR)

    # Recombine
    corrected = luma + chroma

    # Create interpolator
    hacktv_t = np.arange(len(corrected)) / HACKTV_SR
    interp = interp1d(hacktv_t, corrected, kind='cubic',
                      bounds_error=False, fill_value=(corrected[0], corrected[-1]))

    # Resample to PAL-CRT rate with time offset
    palcrt_t = np.arange(PALCRT_HRES) / PALCRT_SR
    hacktv_sample_times = palcrt_t - time_offset
    output = interp(hacktv_sample_times)

    # Convert to IRE scale
    normalized = (output - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
    ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)

    return np.clip(ire, -128, 127).astype(np.int8)


def resample_field_with_phase_correction(hacktv_field, phase_correction_deg):
    """Resample a complete field with phase correction."""
    output = np.zeros(PALCRT_HRES * PALCRT_VRES, dtype=np.int8)

    for line in range(PALCRT_VRES):
        src_start = line * HACKTV_HRES
        if src_start + HACKTV_HRES > len(hacktv_field):
            break

        line_data = hacktv_field[src_start:src_start + HACKTV_HRES]
        resampled = resample_line_with_phase_correction(line_data, line, phase_correction_deg)

        dst_start = line * PALCRT_HRES
        output[dst_start:dst_start + PALCRT_HRES] = resampled

    return output


def decode_with_palcrt(signal, saturation=30, contrast=180):
    """Decode a signal using PAL-CRT library."""
    lib_path = os.path.join(os.path.dirname(__file__), '../external/pal-crt/libpal_decode.so')
    lib = ctypes.CDLL(lib_path)

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(saturation, 0, contrast, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()
    signal_ptr = signal.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(signal), output_buffer)

    decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()
    lib.decode_cleanup()

    return decoded


def sample_color_bars(decoded):
    """Sample color bar regions and return RGB values."""
    # Color bars typically at line 100-200, divided into 8 bars
    bar_y = 150
    bar_width = 80
    bar_positions = [60, 140, 220, 300, 380, 460, 540, 620]
    bar_names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']

    results = {}
    for name, x in zip(bar_names, bar_positions):
        # Sample 20x20 region
        region = decoded[bar_y-10:bar_y+10, x-10:x+10]
        mean_rgb = np.mean(region, axis=(0, 1)).astype(int)
        results[name] = tuple(mean_rgb)

    return results


def calculate_color_error(sampled, expected):
    """Calculate total color error between sampled and expected colors."""
    # Expected approximate PAL color bar values
    expected_colors = {
        'white': (210, 210, 210),
        'yellow': (210, 210, 20),
        'cyan': (20, 210, 210),
        'green': (20, 210, 20),
        'magenta': (210, 20, 210),
        'red': (210, 20, 20),
        'blue': (20, 20, 210),
        'black': (16, 16, 16)
    }

    total_error = 0
    for name in ['yellow', 'cyan', 'green', 'magenta', 'red', 'blue']:
        if name in sampled and name in expected_colors:
            s = np.array(sampled[name])
            e = np.array(expected_colors[name])
            total_error += np.sqrt(np.sum((s - e) ** 2))

    return total_error


def search_best_phase(baseband, frame, output_dir):
    """Search for the best phase correction value."""
    frame_samples = HACKTV_HRES * 625
    frame_start = frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = baseband[frame_start:frame_start + field_samples]

    os.makedirs(output_dir, exist_ok=True)

    best_phase = 0
    best_error = float('inf')
    results = []

    # Test phase corrections from -180 to +180 in 15 degree steps
    for phase in range(-180, 181, 15):
        print(f"  Testing phase = {phase}°...", end=' ')

        resampled = resample_field_with_phase_correction(field_data, phase)
        decoded = decode_with_palcrt(resampled)

        colors = sample_color_bars(decoded)
        error = calculate_color_error(colors, None)

        results.append((phase, error, colors))
        print(f"error = {error:.0f}")

        if error < best_error:
            best_error = error
            best_phase = phase
            Image.fromarray(decoded).save(f"{output_dir}/phase_{phase:+04d}.png")

    return best_phase, best_error, results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Resample with chroma phase correction')
    parser.add_argument('--input', type=str, default='/tmp/color_calibration/colorbars_pal.bin')
    parser.add_argument('--frame', type=int, default=15)
    parser.add_argument('--output', type=str, default='/tmp/phase_corrected.png')
    parser.add_argument('--phase', type=float, default=None, help='Phase correction in degrees')
    parser.add_argument('--search', action='store_true', help='Search for best phase')
    parser.add_argument('--saturation', type=int, default=30)
    parser.add_argument('--contrast', type=int, default=180)
    args = parser.parse_args()

    print("Chroma Phase-Corrected Resampler")
    print("=" * 50)

    # Load baseband
    print(f"Loading {args.input}...")
    baseband = np.fromfile(args.input, dtype=np.int16)

    frame_samples = HACKTV_HRES * 625
    total_frames = len(baseband) // frame_samples
    print(f"  Total frames: {total_frames}")

    if args.search:
        print(f"\nSearching for best phase correction...")
        output_dir = os.path.dirname(args.output) or '/tmp'
        best_phase, best_error, results = search_best_phase(baseband, args.frame, output_dir)
        print(f"\nBest phase: {best_phase}° (error: {best_error:.0f})")

        # Final decode with best phase
        args.phase = best_phase

    if args.phase is None:
        args.phase = 0

    print(f"\nConverting frame {args.frame} with phase correction = {args.phase}°...")

    frame_start = args.frame * frame_samples
    field_samples = HACKTV_HRES * PALCRT_VRES
    field_data = baseband[frame_start:frame_start + field_samples]

    resampled = resample_field_with_phase_correction(field_data, args.phase)
    decoded = decode_with_palcrt(resampled, args.saturation, args.contrast)

    # Save output
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    Image.fromarray(decoded).save(args.output)
    print(f"Saved: {args.output}")

    # Sample color bars
    print("\nColor bar samples:")
    colors = sample_color_bars(decoded)
    for name, rgb in colors.items():
        print(f"  {name:10s}: RGB = {rgb}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
