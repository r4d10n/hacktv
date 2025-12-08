#!/usr/bin/env python3
"""
Convert hacktv 16MHz baseband to PAL-CRT 17.73MHz format.

Key insight: PAL-CRT expects a very specific line format with:
- Front porch, sync, back porch, burst at specific positions
- 4 samples per carrier cycle (phase locked)

This converter:
1. Extracts luma and chroma from hacktv signal
2. Reconstructs the signal in PAL-CRT's expected format
3. Preserves the chroma phase relationship
"""

import numpy as np
from scipy import signal as scipy_signal
from PIL import Image
import ctypes
import sys

# hacktv parameters
HACKTV_SR = 16e6
HACKTV_SAMPLES_PER_LINE = 1024
HACKTV_SAMPLES_PER_FRAME = HACKTV_SAMPLES_PER_LINE * 625

HACKTV_SYNC_LEVEL = -0.30 * 32767
HACKTV_WHITE_LEVEL = 0.70 * 32767

# PAL carrier
F_SC = 4433618.75

# PAL-CRT parameters
PALCRT_SR = F_SC * 4  # 17,734,475 Hz
PALCRT_HRES = 1135
PALCRT_VRES = 312

# PAL-CRT timing (from pal.h)
LINE_NS = 64000
FP_NS = 1600
SYNC_NS = 4700
BW_NS = 800
CB_NS = 2500
BP_NS = 2400
HB_NS = FP_NS + SYNC_NS + BW_NS + CB_NS + BP_NS
AV_NS = LINE_NS - HB_NS

# Convert ns to sample position
def ns2pos(ns):
    return int(ns * PALCRT_HRES / LINE_NS)

FP_BEG = ns2pos(0)
SYNC_BEG = ns2pos(FP_NS)
BW_BEG = ns2pos(FP_NS + SYNC_NS)
CB_BEG = ns2pos(FP_NS + SYNC_NS + BW_NS)
BP_BEG = ns2pos(FP_NS + SYNC_NS + BW_NS + CB_NS)
AV_BEG = ns2pos(HB_NS)
AV_LEN = ns2pos(AV_NS)

# hacktv timing (approximate)
HACKTV_SYNC_START = 0
HACKTV_SYNC_END = int(HACKTV_SR * 4.7e-6)  # ~75 samples
HACKTV_BURST_START = int(HACKTV_SR * 5.6e-6)  # ~90 samples
HACKTV_BURST_END = int(HACKTV_SR * 7.85e-6)  # ~126 samples
HACKTV_AV_START = int(HACKTV_SR * 10.5e-6)  # ~168 samples
HACKTV_AV_END = HACKTV_SAMPLES_PER_LINE - int(HACKTV_SR * 1.6e-6)  # ~998 samples

# IRE levels for PAL-CRT
SYNC_LEVEL = -40
BLACK_LEVEL = 0
WHITE_LEVEL = 100
BURST_LEVEL = 20


def extract_yuv_from_hacktv_line(line_data, line_num, frame_num):
    """
    Extract Y, U, V components from a hacktv line.

    Returns:
        y: Luma signal (same length as input)
        u: U component (lowpass filtered)
        v: V component (lowpass filtered)
        burst_phase: Detected burst phase
    """
    # Convert to float and normalize to 0-1 range
    line = line_data.astype(np.float64)

    # Separate luma and chroma using filters
    # Luma: lowpass at 5.5 MHz
    # Chroma: bandpass around 4.43 MHz

    nyq = HACKTV_SR / 2
    luma_cutoff = 4.0e6 / nyq
    chroma_low = 3.5e6 / nyq
    chroma_high = 5.5e6 / nyq

    luma_filter = scipy_signal.firwin(65, luma_cutoff)
    chroma_filter = scipy_signal.firwin(65, [chroma_low, chroma_high], pass_zero=False)

    luma = scipy_signal.lfilter(luma_filter, 1, line)
    chroma = scipy_signal.lfilter(chroma_filter, 1, line)

    # Demodulate chroma
    # Generate carrier at subcarrier frequency
    omega = 2 * np.pi * F_SC / HACKTV_SR
    t = np.arange(len(line))

    # PAL V-switch
    pal_switch = -1 if (frame_num + line_num) & 1 else 1

    # Demodulate: multiply by carrier and lowpass
    demod_filter = scipy_signal.firwin(33, 1.5e6 / nyq)

    u_demod = chroma * np.cos(t * omega) * 2
    v_demod = chroma * np.sin(t * omega) * 2 * pal_switch

    u = scipy_signal.lfilter(demod_filter, 1, u_demod)
    v = scipy_signal.lfilter(demod_filter, 1, v_demod)

    # Detect burst phase
    burst_region = chroma[HACKTV_BURST_START:HACKTV_BURST_END]
    burst_t = t[HACKTV_BURST_START:HACKTV_BURST_END]
    burst_sin = np.mean(burst_region * np.sin(burst_t * omega))
    burst_cos = np.mean(burst_region * np.cos(burst_t * omega))
    burst_phase = np.arctan2(burst_sin, burst_cos)

    return luma, u, v, burst_phase


def create_palcrt_line(luma, u, v, line_num, pal_switch):
    """
    Create a PAL-CRT format line from Y, U, V components.

    The line format:
    - Front porch: BLACK_LEVEL
    - Sync: SYNC_LEVEL
    - Back porch with burst: BLACK_LEVEL + burst oscillation
    - Active video: Y + chroma modulation
    """
    output = np.zeros(PALCRT_HRES, dtype=np.float64)

    # Front porch
    output[FP_BEG:SYNC_BEG] = BLACK_LEVEL

    # Sync
    output[SYNC_BEG:BW_BEG] = SYNC_LEVEL

    # Breezeway
    output[BW_BEG:CB_BEG] = BLACK_LEVEL

    # Color burst (135° phase, ±BURST_LEVEL amplitude)
    # PAL burst is at 135° alternating with V-switch
    burst_t = np.arange(CB_BEG, BP_BEG)
    omega_palcrt = np.pi / 2  # 4 samples per cycle = 90° per sample
    burst_phase_135 = 135 * np.pi / 180
    burst_signal = BURST_LEVEL * np.sin(burst_t * omega_palcrt + burst_phase_135)
    # Apply tapering
    burst_len = BP_BEG - CB_BEG
    burst_window = np.sin(np.linspace(0, np.pi, burst_len))
    output[CB_BEG:BP_BEG] = BLACK_LEVEL + burst_signal * burst_window * pal_switch

    # Back porch
    output[BP_BEG:AV_BEG] = BLACK_LEVEL

    # Active video: need to resample luma and u,v from hacktv resolution
    # Map hacktv active video (HACKTV_AV_START to HACKTV_AV_END) to PAL-CRT (AV_BEG to AV_BEG+AV_LEN)
    hacktv_av_len = HACKTV_AV_END - HACKTV_AV_START

    for i in range(AV_LEN):
        # Progress through active video
        progress = i / AV_LEN
        # Map to hacktv position
        hacktv_pos = HACKTV_AV_START + progress * hacktv_av_len

        if hacktv_pos >= len(luma) - 1:
            break

        # Interpolate luma
        pos_int = int(hacktv_pos)
        frac = hacktv_pos - pos_int
        y_val = luma[pos_int] * (1 - frac) + luma[pos_int + 1] * frac
        u_val = u[pos_int] * (1 - frac) + u[pos_int + 1] * frac
        v_val = v[pos_int] * (1 - frac) + v[pos_int + 1] * frac

        # Convert to IRE scale
        y_ire = (y_val - HACKTV_SYNC_LEVEL) / (HACKTV_WHITE_LEVEL - HACKTV_SYNC_LEVEL) * WHITE_LEVEL

        # Scale U, V (they're already demodulated)
        # The chroma amplitude needs calibration
        chroma_scale = 0.5  # Adjust this!
        u_scaled = u_val / (HACKTV_WHITE_LEVEL - HACKTV_SYNC_LEVEL) * WHITE_LEVEL * chroma_scale
        v_scaled = v_val / (HACKTV_WHITE_LEVEL - HACKTV_SYNC_LEVEL) * WHITE_LEVEL * chroma_scale

        # Modulate chroma back onto carrier
        palcrt_pos = AV_BEG + i
        # PAL-CRT expects 4 samples per cycle, so carrier advances 90° per sample
        carrier_phase = palcrt_pos * np.pi / 2

        chroma = u_scaled * np.cos(carrier_phase) + v_scaled * np.sin(carrier_phase) * pal_switch

        output[palcrt_pos] = y_ire + chroma

    # Clamp to valid range
    output = np.clip(output, SYNC_LEVEL, WHITE_LEVEL + 10)

    return output


def convert_field(hacktv_field, frame_num):
    """Convert a complete field from hacktv format to PAL-CRT format."""
    output = np.zeros(PALCRT_HRES * PALCRT_VRES, dtype=np.int8)

    for line in range(PALCRT_VRES):
        src_start = line * HACKTV_SAMPLES_PER_LINE
        if src_start + HACKTV_SAMPLES_PER_LINE > len(hacktv_field):
            break

        line_data = hacktv_field[src_start:src_start + HACKTV_SAMPLES_PER_LINE]

        # Extract YUV
        luma, u, v, burst_phase = extract_yuv_from_hacktv_line(line_data, line, frame_num)

        # PAL V-switch
        pal_switch = -1 if (frame_num + line) & 1 else 1

        # Create PAL-CRT format line
        palcrt_line = create_palcrt_line(luma, u, v, line, pal_switch)

        # Store
        dst_start = line * PALCRT_HRES
        output[dst_start:dst_start + PALCRT_HRES] = palcrt_line.astype(np.int8)

    return output


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Convert hacktv to PAL-CRT format')
    parser.add_argument('--input', type=str, default='/tmp/color_calibration/colorbars_pal.bin',
                        help='Input hacktv baseband file')
    parser.add_argument('--frame', type=int, default=15,
                        help='Frame number to convert')
    parser.add_argument('--output', type=str, default='/tmp/converted_palcrt.png',
                        help='Output decoded image')
    args = parser.parse_args()

    print("hacktv to PAL-CRT Converter")
    print("=" * 50)

    # Load hacktv baseband
    print(f"Loading {args.input}...")
    baseband = np.fromfile(args.input, dtype=np.int16)
    total_frames = len(baseband) // int(HACKTV_SAMPLES_PER_FRAME)
    print(f"  Total frames: {total_frames}")

    # Extract frame
    frame_start = args.frame * int(HACKTV_SAMPLES_PER_FRAME)
    frame_data = baseband[frame_start:frame_start + int(HACKTV_SAMPLES_PER_FRAME)]

    # Convert first field
    print(f"\nConverting frame {args.frame}...")
    field_samples = HACKTV_SAMPLES_PER_LINE * PALCRT_VRES
    field_data = frame_data[:field_samples]

    converted = convert_field(field_data, args.frame)

    # Decode with PAL-CRT
    print("\nDecoding with PAL-CRT...")
    lib = ctypes.CDLL('external/pal-crt/libpal_decode.so')

    lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.decode_init.restype = ctypes.c_int
    lib.decode_field.argtypes = [ctypes.POINTER(ctypes.c_int8), ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_uint8)]
    lib.decode_field.restype = ctypes.c_int
    lib.decode_set_params.argtypes = [ctypes.c_int] * 6
    lib.decode_cleanup.restype = None

    lib.decode_init(720, 576)
    lib.decode_set_params(30, 0, 180, 0, 100, 1)

    output_buffer = (ctypes.c_uint8 * (720 * 576 * 3))()
    signal_ptr = converted.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
    lib.decode_field(signal_ptr, len(converted), output_buffer)

    decoded = np.ctypeslib.as_array(output_buffer).reshape((576, 720, 3)).copy()

    Image.fromarray(decoded).save(args.output)
    print(f"  Saved: {args.output}")

    lib.decode_cleanup()
    print("\nDone!")


if __name__ == '__main__':
    main()
