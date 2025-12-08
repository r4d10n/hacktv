#!/usr/bin/env python3
"""
Direct PAL decoder for hacktv 16MHz baseband.
Matches hacktv's encoding formula exactly without resampling.

hacktv encoding:
- Composite = Y + V*sin(wt)*pal_switch + U*cos(wt)
- pal_switch = -1 if (frame + line) & 1 else +1
- Burst phase = 135° (reference)
"""

import numpy as np
from PIL import Image
import subprocess
import os
import json
from datetime import datetime

# hacktv constants
SAMPLE_RATE = 16e6  # 16 MHz
F_SC = 4433618.75   # PAL subcarrier frequency
SAMPLES_PER_LINE = 1024
LINES_PER_FRAME = 625
SAMPLES_PER_FRAME = SAMPLES_PER_LINE * LINES_PER_FRAME

# Signal levels (int16)
SYNC_LEVEL = -0.30 * 32767  # -9830
BLACK_LEVEL = 0
WHITE_LEVEL = 0.70 * 32767  # 22937

# Active video region (approximate)
ACTIVE_START = 264  # samples from line start
ACTIVE_WIDTH = 702  # active samples per line
ACTIVE_LINES_START = 23
ACTIVE_LINES = 576

# Burst position
BURST_START = 88
BURST_WIDTH = 36


def generate_carrier_tables(samples_per_line):
    """Generate sin/cos lookup tables for the subcarrier."""
    # Phase increment per sample
    phase_inc = 2 * np.pi * F_SC / SAMPLE_RATE

    # Generate for one line
    t = np.arange(samples_per_line)
    phase = t * phase_inc

    sin_table = np.sin(phase)
    cos_table = np.cos(phase)

    return sin_table, cos_table


def detect_burst_phase(line_data, sin_t, cos_t):
    """Detect burst phase for this line."""
    burst = line_data[BURST_START:BURST_START + BURST_WIDTH].astype(np.float64)
    burst -= BLACK_LEVEL  # Remove DC

    # Demodulate burst with reference carriers
    sin_burst = sin_t[BURST_START:BURST_START + BURST_WIDTH]
    cos_burst = cos_t[BURST_START:BURST_START + BURST_WIDTH]

    # Correlate with carriers
    i_component = np.mean(burst * cos_burst) * 2
    q_component = np.mean(burst * sin_burst) * 2

    # Burst phase (should be ~135° for PAL)
    burst_phase = np.arctan2(q_component, i_component)
    burst_amplitude = np.sqrt(i_component**2 + q_component**2)

    return burst_phase, burst_amplitude, i_component, q_component


def decode_line(line_data, sin_t, cos_t, pal_switch, burst_phase):
    """Decode one line of PAL signal."""
    active = line_data[ACTIVE_START:ACTIVE_START + ACTIVE_WIDTH].astype(np.float64)

    # Normalize signal: sync=-40 IRE, black=0, white=100 IRE
    # Convert to 0-1 range for luminance
    y_signal = (active - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)

    # Get carrier samples for active region
    sin_active = sin_t[ACTIVE_START:ACTIVE_START + ACTIVE_WIDTH]
    cos_active = cos_t[ACTIVE_START:ACTIVE_START + ACTIVE_WIDTH]

    # Burst reference phase is 135°
    # Adjust demodulation carriers relative to burst
    burst_ref = 135 * np.pi / 180
    phase_offset = burst_phase - burst_ref

    # Rotate carriers by phase offset
    cos_adj = np.cos(phase_offset)
    sin_adj = np.sin(phase_offset)

    sin_rot = sin_active * cos_adj - cos_active * sin_adj
    cos_rot = cos_active * cos_adj + sin_active * sin_adj

    # Demodulate chroma
    # hacktv encodes: V*sin(wt)*pal_switch + U*cos(wt)
    # So U = signal * cos(wt) * 2, V = signal * sin(wt) * pal_switch * 2
    chroma = active - BLACK_LEVEL

    u_demod = chroma * cos_rot * 2
    v_demod = chroma * sin_rot * 2 * pal_switch

    # Low-pass filter U and V (simple moving average)
    kernel_size = int(SAMPLE_RATE / F_SC / 2)  # Half cycle
    if kernel_size < 3:
        kernel_size = 3
    kernel = np.ones(kernel_size) / kernel_size

    u_filtered = np.convolve(u_demod, kernel, mode='same')
    v_filtered = np.convolve(v_demod, kernel, mode='same')

    # Extract luminance by removing chroma
    # Comb filter: average current line with previous (PAL delay line)
    # For now, just low-pass the signal for Y
    y_filtered = np.convolve(y_signal, kernel, mode='same')

    return y_filtered, u_filtered, v_filtered


def yuv_to_rgb(y, u, v):
    """Convert YUV to RGB using PAL matrix."""
    # Scale factors for U,V (empirically determined)
    u_scale = 0.5 / (WHITE_LEVEL - BLACK_LEVEL)
    v_scale = 0.5 / (WHITE_LEVEL - BLACK_LEVEL)

    u = u * u_scale
    v = v * v_scale

    # YUV to RGB matrix (BT.601)
    r = y + 1.402 * v
    g = y - 0.344 * u - 0.714 * v
    b = y + 1.772 * u

    return np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b, 0, 1)


def decode_frame(frame_data, frame_num, sin_t, cos_t):
    """Decode one complete frame."""
    height = ACTIVE_LINES
    width = ACTIVE_WIDTH

    rgb = np.zeros((height, width, 3), dtype=np.uint8)

    for line_idx in range(height):
        actual_line = ACTIVE_LINES_START + line_idx
        line_start = actual_line * SAMPLES_PER_LINE
        line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

        if len(line_data) < SAMPLES_PER_LINE:
            continue

        # Determine PAL switch for this line
        pal_switch = -1 if (frame_num + actual_line) & 1 else 1

        # Detect burst phase
        burst_phase, burst_amp, _, _ = detect_burst_phase(line_data, sin_t, cos_t)

        # Skip lines with weak/no burst
        if burst_amp < 500:
            # Monochrome line
            y = (line_data[ACTIVE_START:ACTIVE_START + ACTIVE_WIDTH].astype(np.float64) - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            kernel = np.ones(5) / 5
            y = np.convolve(y, kernel, mode='same')
            rgb[line_idx, :, 0] = np.clip(y * 255, 0, 255).astype(np.uint8)
            rgb[line_idx, :, 1] = rgb[line_idx, :, 0]
            rgb[line_idx, :, 2] = rgb[line_idx, :, 0]
            continue

        # Decode with color
        y, u, v = decode_line(line_data, sin_t, cos_t, pal_switch, burst_phase)
        r, g, b = yuv_to_rgb(y, u, v)

        rgb[line_idx, :, 0] = (r * 255).astype(np.uint8)
        rgb[line_idx, :, 1] = (g * 255).astype(np.uint8)
        rgb[line_idx, :, 2] = (b * 255).astype(np.uint8)

    return rgb


def decode_frame_with_comb(frame_data, frame_num, sin_t, cos_t):
    """Decode frame using PAL delay line (comb filter)."""
    height = ACTIVE_LINES
    width = ACTIVE_WIDTH

    rgb = np.zeros((height, width, 3), dtype=np.uint8)

    # First pass: decode all lines and store Y, U, V
    y_lines = []
    u_lines = []
    v_lines = []

    for line_idx in range(height):
        actual_line = ACTIVE_LINES_START + line_idx
        line_start = actual_line * SAMPLES_PER_LINE
        line_data = frame_data[line_start:line_start + SAMPLES_PER_LINE]

        if len(line_data) < SAMPLES_PER_LINE:
            y_lines.append(np.zeros(width))
            u_lines.append(np.zeros(width))
            v_lines.append(np.zeros(width))
            continue

        pal_switch = -1 if (frame_num + actual_line) & 1 else 1
        burst_phase, burst_amp, _, _ = detect_burst_phase(line_data, sin_t, cos_t)

        if burst_amp < 500:
            y = (line_data[ACTIVE_START:ACTIVE_START + width].astype(np.float64) - BLACK_LEVEL) / (WHITE_LEVEL - BLACK_LEVEL)
            y_lines.append(y)
            u_lines.append(np.zeros(width))
            v_lines.append(np.zeros(width))
        else:
            y, u, v = decode_line(line_data, sin_t, cos_t, pal_switch, burst_phase)
            y_lines.append(y)
            u_lines.append(u)
            v_lines.append(v)

    # Second pass: apply PAL delay line averaging
    # In PAL, V is inverted on alternate lines
    # Averaging (current + previous) cancels V crosstalk into U
    # Differencing (current - previous) / 2 gives clean V

    for line_idx in range(height):
        if line_idx == 0:
            y = y_lines[line_idx]
            u = u_lines[line_idx]
            v = v_lines[line_idx]
        else:
            y = y_lines[line_idx]
            # PAL delay line: average U, difference V
            u = (u_lines[line_idx] + u_lines[line_idx - 1]) / 2
            v = (v_lines[line_idx] - v_lines[line_idx - 1]) / 2

        r, g, b = yuv_to_rgb(y, u, v)
        rgb[line_idx, :, 0] = (r * 255).astype(np.uint8)
        rgb[line_idx, :, 1] = (g * 255).astype(np.uint8)
        rgb[line_idx, :, 2] = (b * 255).astype(np.uint8)

    return rgb


def compute_metrics(original, decoded):
    """Compute PSNR between original and decoded."""
    if original.shape != decoded.shape:
        img = Image.fromarray(decoded)
        img = img.resize((original.shape[1], original.shape[0]), Image.LANCZOS)
        decoded = np.array(img)

    mse = np.mean((original.astype(float) - decoded.astype(float)) ** 2)
    psnr = 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')
    return {'psnr': psnr, 'mse': mse}


def main():
    baseband_file = '/tmp/pal_baseband.bin'
    original_video = 'samples/nature_original.mp4'
    output_dir = '/tmp/direct_decode'

    os.makedirs(output_dir, exist_ok=True)

    print("Loading baseband...")
    baseband = np.fromfile(baseband_file, dtype=np.int16)
    total_frames = len(baseband) // SAMPLES_PER_FRAME

    # Generate carrier tables
    print("Generating carrier tables...")
    sin_t, cos_t = generate_carrier_tables(SAMPLES_PER_LINE)

    # Test frames with diverse colors
    test_frames = [50, 100, 150, 200, 250, 300, 350, 400, 450]

    # Extract original frames for comparison
    print("Extracting original frames...")
    orig_dir = f'{output_dir}/original'
    os.makedirs(orig_dir, exist_ok=True)

    max_frame = max(test_frames) + 1
    subprocess.run([
        'ffmpeg', '-y', '-i', original_video,
        '-vframes', str(max_frame),
        '-pix_fmt', 'rgb24',
        f'{orig_dir}/frame_%04d.png'
    ], capture_output=True)

    # Load original frames
    original_frames = {}
    for f in test_frames:
        path = f'{orig_dir}/frame_{f+1:04d}.png'
        if os.path.exists(path):
            img = Image.open(path).resize((ACTIVE_WIDTH, ACTIVE_LINES), Image.LANCZOS)
            original_frames[f] = np.array(img)

    print(f"\nDecoding {len(test_frames)} test frames...")
    results = []

    for frame_num in test_frames:
        print(f"\nFrame {frame_num}:")

        frame_start = frame_num * SAMPLES_PER_FRAME
        frame_data = baseband[frame_start:frame_start + SAMPLES_PER_FRAME]

        if len(frame_data) < SAMPLES_PER_FRAME:
            print(f"  Skipped (insufficient data)")
            continue

        # Decode without comb filter
        decoded_simple = decode_frame(frame_data, frame_num, sin_t, cos_t)
        img = Image.fromarray(decoded_simple)
        img.save(f'{output_dir}/simple_frame_{frame_num:04d}.png')

        # Decode with comb filter
        decoded_comb = decode_frame_with_comb(frame_data, frame_num, sin_t, cos_t)
        img = Image.fromarray(decoded_comb)
        img.save(f'{output_dir}/comb_frame_{frame_num:04d}.png')

        # Compare with original
        if frame_num in original_frames:
            orig = original_frames[frame_num]

            metrics_simple = compute_metrics(orig, decoded_simple)
            metrics_comb = compute_metrics(orig, decoded_comb)

            print(f"  Simple: PSNR = {metrics_simple['psnr']:.2f} dB")
            print(f"  Comb:   PSNR = {metrics_comb['psnr']:.2f} dB")

            results.append({
                'frame': frame_num,
                'simple_psnr': metrics_simple['psnr'],
                'comb_psnr': metrics_comb['psnr']
            })

    # Save results
    with open(f'{output_dir}/results.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'frames': results,
            'mean_simple_psnr': np.mean([r['simple_psnr'] for r in results]),
            'mean_comb_psnr': np.mean([r['comb_psnr'] for r in results])
        }, f, indent=2)

    print(f"\n{'='*60}")
    print("RESULTS")
    print('='*60)
    print(f"Mean Simple PSNR: {np.mean([r['simple_psnr'] for r in results]):.2f} dB")
    print(f"Mean Comb PSNR: {np.mean([r['comb_psnr'] for r in results]):.2f} dB")
    print(f"Results saved to {output_dir}/")


if __name__ == '__main__':
    main()
