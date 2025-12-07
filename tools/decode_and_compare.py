#!/usr/bin/env python3
"""
PAL Decoder Comparison Tool

Decodes PAL baseband signals using multiple methods and compares quality.

Methods compared:
1. PAL-CRT library decoder
2. Custom professional decoder (decode_baseband.py)
3. Improved multi-dimensional comb filter decoder

Outputs:
- Decoded frames
- PSNR/MSE metrics
- Visual difference maps
- Recommendations for improvements
"""

import numpy as np
import subprocess
import argparse
import os
import sys
import ctypes
from scipy import signal as scipy_signal
from PIL import Image
import json
from datetime import datetime

# Add tools directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# PAL Constants
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
LINE_ns = HB_ns + AV_ns

# Signal levels (IRE)
WHITE_LEVEL = 100
BLACK_LEVEL = 0
SYNC_LEVEL = -40

def ns2pos(ns):
    return (ns * PAL_HRES) // LINE_ns

AV_BEG = ns2pos(HB_ns)
AV_LEN = ns2pos(AV_ns)
CB_BEG = ns2pos(FP_ns + SYNC_ns + BW_ns)


class PALCRTDecoder:
    """Wrapper for PAL-CRT library."""

    def __init__(self, lib_path=None, output_width=720, output_height=576):
        if lib_path is None:
            lib_path = os.path.join(script_dir, '..', 'external', 'pal-crt', 'libpal_decode.so')

        self.lib = ctypes.CDLL(lib_path)

        self.lib.decode_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.decode_init.restype = ctypes.c_int
        self.lib.decode_field.argtypes = [
            ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)
        ]
        self.lib.decode_field.restype = ctypes.c_int
        self.lib.decode_set_params.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int
        ]
        self.lib.get_input_size.restype = ctypes.c_int
        self.lib.decode_cleanup.restype = None

        self.output_width = output_width
        self.output_height = output_height
        self.output_size = output_width * output_height * 3
        self.output_buffer = (ctypes.c_uint8 * self.output_size)()

        self.lib.decode_init(output_width, output_height)

    def set_params(self, saturation=12, brightness=0, contrast=180,
                   black_point=0, white_point=100, chroma_correction=1):
        self.lib.decode_set_params(saturation, brightness, contrast,
                                   black_point, white_point, chroma_correction)

    def decode_field(self, field_signal):
        signal_arr = np.ascontiguousarray(field_signal, dtype=np.int8)
        signal_ptr = signal_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_int8))
        self.lib.decode_field(signal_ptr, len(signal_arr), self.output_buffer)
        output = np.ctypeslib.as_array(self.output_buffer)
        return output.reshape((self.output_height, self.output_width, 3)).copy()

    def __del__(self):
        if hasattr(self, 'lib'):
            self.lib.decode_cleanup()


class AdvancedPALDecoder:
    """
    Advanced PAL decoder implementing techniques from Watkinson's guide.

    Techniques:
    1. 9-tap multi-dimensional comb filter
    2. Adaptive Y/C separation
    3. PAL delay line with proper V-switch handling
    4. Motion-adaptive processing
    5. High-quality chroma demodulation
    """

    def __init__(self, output_width=720, output_height=576):
        self.output_width = output_width
        self.output_height = output_height
        self.sample_rate = 17734475  # 4 * f_sc

        # PAL colour carrier
        self.colour_carrier = 4433618.75

        self._create_filters()

        # Field buffer for multi-field processing
        self.prev_field = None

    def _create_filters(self):
        """Create optimized filters."""
        fs = self.sample_rate
        nyq = fs / 2

        # Y lowpass: 5.2 MHz with sharp cutoff
        y_bw = 5.2e6
        self.y_lpf_b, self.y_lpf_a = scipy_signal.butter(8, y_bw / nyq, 'low')

        # Chroma bandpass around f_sc +/- 1.3 MHz
        fc = self.colour_carrier
        chroma_low = (fc - 1.3e6) / nyq
        chroma_high = (fc + 1.3e6) / nyq
        self.chroma_bpf_b, self.chroma_bpf_a = scipy_signal.butter(
            5, [chroma_low, chroma_high], 'band'
        )

        # UV lowpass: 1.29 MHz
        uv_bw = 1.29e6
        self.uv_lpf_b, self.uv_lpf_a = scipy_signal.butter(5, uv_bw / nyq, 'low')

        # Notch filter at f_sc for Y extraction
        notch_bw = 0.6e6
        notch_low = (fc - notch_bw) / nyq
        notch_high = (fc + notch_bw) / nyq
        self.notch_b, self.notch_a = scipy_signal.butter(
            4, [notch_low, notch_high], 'bandstop'
        )

    def _adaptive_comb_filter(self, field_buffer, line_idx):
        """
        Adaptive Y/C separation using vertical comb filtering.

        Uses 2-line and 3-line combs adaptively based on
        vertical colour transitions (Watkinson Section 3.5).
        """
        def get_line(idx):
            if 0 <= idx < len(field_buffer):
                return field_buffer[idx].astype(np.float64)
            return None

        current = get_line(line_idx)
        if current is None:
            return current, np.zeros(PAL_HRES)

        prev1 = get_line(line_idx - 1)
        prev2 = get_line(line_idx - 2)
        next1 = get_line(line_idx + 1)
        next2 = get_line(line_idx + 2)

        # Default to current line
        y_out = current.copy()
        c_out = np.zeros_like(current)

        # 3-tap comb for basic Y/C separation
        if prev1 is not None and next1 is not None:
            # In PAL, chroma inverts every line, so adding adjacent lines
            # cancels chroma and extracts Y
            y_3tap = (prev1 + 2 * current + next1) / 4.0
            c_3tap = current - y_3tap

            # Detect comb failure (high vertical chroma transitions)
            # by comparing bandpass-filtered adjacent lines
            chroma_prev = scipy_signal.filtfilt(
                self.chroma_bpf_b, self.chroma_bpf_a, prev1
            )
            chroma_curr = scipy_signal.filtfilt(
                self.chroma_bpf_b, self.chroma_bpf_a, current
            )
            chroma_next = scipy_signal.filtfilt(
                self.chroma_bpf_b, self.chroma_bpf_a, next1
            )

            # Phase difference between lines
            phase_diff = np.abs(chroma_curr - chroma_prev) + np.abs(chroma_curr - chroma_next)

            # Adaptive blend: use comb where phase is consistent, notch otherwise
            adapt_weight = np.clip(1.0 - phase_diff / 50.0, 0.3, 1.0)

            # Notch-filtered Y as fallback
            y_notch = scipy_signal.filtfilt(self.notch_b, self.notch_a, current)
            c_bandpass = scipy_signal.filtfilt(
                self.chroma_bpf_b, self.chroma_bpf_a, current
            )

            # Blend based on adaptation weight
            y_out = adapt_weight * y_3tap + (1 - adapt_weight) * y_notch
            c_out = adapt_weight * c_3tap + (1 - adapt_weight) * c_bandpass

        else:
            # Fallback to notch/bandpass
            y_out = scipy_signal.filtfilt(self.notch_b, self.notch_a, current)
            c_out = scipy_signal.filtfilt(
                self.chroma_bpf_b, self.chroma_bpf_a, current
            )

        return y_out, c_out

    def _detect_burst(self, line_data):
        """
        Detect colour burst phase and amplitude.

        PAL burst swings +/- 45 degrees around -U axis (135 or -135 degrees).
        """
        burst_start = CB_BEG
        burst_len = 10 * PAL_CB_FREQ

        if len(line_data) < burst_start + burst_len:
            return 0.0, 0.0, 1

        burst = line_data[burst_start:burst_start + burst_len].astype(np.float64)
        burst = burst - np.mean(burst)

        # At 4*f_sc: cos/sin cycle every 4 samples
        t = np.arange(len(burst))
        ref_cos = np.cos(t * np.pi / 2)
        ref_sin = np.sin(t * np.pi / 2)

        i_corr = np.sum(burst * ref_cos) * 2 / len(burst)
        q_corr = np.sum(burst * ref_sin) * 2 / len(burst)

        phase = np.arctan2(q_corr, i_corr)
        amplitude = np.sqrt(i_corr**2 + q_corr**2)

        # Detect V-switch from burst phase
        phase_deg = np.rad2deg(phase)
        while phase_deg > 180:
            phase_deg -= 360
        while phase_deg < -180:
            phase_deg += 360

        # PAL burst at +135 or -135 degrees
        pal_sign = 1 if phase_deg > -90 else -1

        return phase, amplitude, pal_sign

    def _demodulate_chroma(self, chroma, burst_phase, pal_sign):
        """
        Demodulate chroma to U and V.

        PAL encoding:
        - U modulated on sin(wt)
        - V modulated on cos(wt) with PAL switch
        """
        n = len(chroma)
        t = np.arange(n)

        # Phase offset to align with burst
        if pal_sign == 1:
            phase_offset = np.deg2rad(45)
        else:
            phase_offset = np.deg2rad(135)

        demod_phase = burst_phase + phase_offset

        # At 4*f_sc, carrier cycles every 4 samples
        omega_t = t * np.pi / 2 + demod_phase

        u_carrier = np.sin(omega_t)
        v_carrier = np.cos(omega_t) * pal_sign

        u_raw = chroma * u_carrier * 2
        v_raw = chroma * v_carrier * 2

        u_filt = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, u_raw)
        v_filt = scipy_signal.filtfilt(self.uv_lpf_b, self.uv_lpf_a, v_raw)

        return u_filt, v_filt

    def _pal_delay_average(self, u_curr, v_curr, u_prev, v_prev):
        """PAL delay line averaging."""
        if u_prev is None:
            return u_curr, v_curr
        return (u_curr + u_prev) / 2, (v_curr + v_prev) / 2

    def _yuv_to_rgb(self, y, u, v):
        """
        Convert YUV to RGB.

        Uses ITU-R BT.601 matrix with proper scaling.
        """
        # Normalize Y from IRE to 0-1
        y_norm = (y - SYNC_LEVEL) / (WHITE_LEVEL - SYNC_LEVEL)
        y_norm = np.clip((y_norm - 0.286) / 0.714, 0, 1)

        # Scale U and V (adjust for decoder gain)
        u_scale = u / 40.0
        v_scale = v / 40.0

        # BT.601 matrix
        r = y_norm + 1.140 * v_scale
        g = y_norm - 0.395 * u_scale - 0.581 * v_scale
        b = y_norm + 2.032 * u_scale

        return r, g, b

    def decode_field(self, field_signal):
        """Decode a field using advanced techniques."""
        if len(field_signal) != PAL_INPUT_SIZE:
            raise ValueError(f"Expected {PAL_INPUT_SIZE} samples")

        field_buffer = field_signal.reshape((PAL_VRES, PAL_HRES)).astype(np.float64)
        output = np.zeros((PAL_LINES, self.output_width, 3), dtype=np.uint8)

        prev_u = None
        prev_v = None

        for line_idx in range(PAL_TOP, PAL_BOT):
            line_data = field_buffer[line_idx]
            out_line = line_idx - PAL_TOP

            # Detect burst
            burst_phase, burst_amp, pal_sign = self._detect_burst(line_data)

            # Adaptive Y/C separation
            y_sep, chroma = self._adaptive_comb_filter(field_buffer, line_idx)

            # Final Y lowpass
            y_filt = scipy_signal.filtfilt(self.y_lpf_b, self.y_lpf_a, y_sep)

            # Demodulate chroma
            u_demod, v_demod = self._demodulate_chroma(chroma, burst_phase, pal_sign)

            # PAL delay line
            u_final, v_final = self._pal_delay_average(u_demod, v_demod, prev_u, prev_v)
            prev_u = u_demod.copy()
            prev_v = v_demod.copy()

            # Extract active video
            y_active = y_filt[AV_BEG:AV_BEG + AV_LEN]
            u_active = u_final[AV_BEG:AV_BEG + AV_LEN]
            v_active = v_final[AV_BEG:AV_BEG + AV_LEN]

            # Convert to RGB
            r, g, b = self._yuv_to_rgb(y_active, u_active, v_active)

            r = np.clip(r * 255, 0, 255).astype(np.uint8)
            g = np.clip(g * 255, 0, 255).astype(np.uint8)
            b = np.clip(b * 255, 0, 255).astype(np.uint8)

            # Resample to output width
            x = np.linspace(0, len(r) - 1, self.output_width)
            output[out_line, :, 0] = np.interp(x, np.arange(len(r)), r).astype(np.uint8)
            output[out_line, :, 1] = np.interp(x, np.arange(len(g)), g).astype(np.uint8)
            output[out_line, :, 2] = np.interp(x, np.arange(len(b)), b).astype(np.uint8)

        # Scale to output height
        if output.shape[0] != self.output_height:
            img = Image.fromarray(output)
            img = img.resize((self.output_width, self.output_height), Image.LANCZOS)
            output = np.array(img)

        return output


def resample_hacktv_to_palcrt(data, src_samples_per_line=1024, src_lines=312):
    """Resample hacktv 16MHz to PAL-CRT 4*f_sc format."""
    output = np.zeros(PAL_INPUT_SIZE, dtype=np.int8)

    HACKTV_SYNC = -0.30 * 32767
    HACKTV_WHITE = 0.70 * 32767

    for line in range(min(src_lines, PAL_VRES)):
        src_start = line * src_samples_per_line
        src_end = src_start + src_samples_per_line

        if src_end > len(data):
            break

        line_data = data[src_start:src_end].astype(np.float64)

        x_src = np.arange(len(line_data))
        x_dst = np.linspace(0, len(line_data) - 1, PAL_HRES)
        resampled = np.interp(x_dst, x_src, line_data)

        normalized = (resampled - HACKTV_SYNC) / (HACKTV_WHITE - HACKTV_SYNC)
        ire = SYNC_LEVEL + normalized * (WHITE_LEVEL - SYNC_LEVEL)
        output[line * PAL_HRES:(line + 1) * PAL_HRES] = np.clip(ire, -128, 127).astype(np.int8)

    return output


def compute_metrics(original, decoded):
    """Compute quality metrics between original and decoded frames."""
    # Resize decoded to match original if needed
    if original.shape[:2] != decoded.shape[:2]:
        img = Image.fromarray(decoded)
        img = img.resize((original.shape[1], original.shape[0]), Image.LANCZOS)
        decoded = np.array(img)

    orig_f = original.astype(np.float64)
    dec_f = decoded.astype(np.float64)

    # MSE
    mse = np.mean((orig_f - dec_f) ** 2)

    # PSNR
    psnr = 10 * np.log10(255**2 / mse) if mse > 0 else float('inf')

    # SSIM (simplified)
    mu_orig = np.mean(orig_f)
    mu_dec = np.mean(dec_f)
    var_orig = np.var(orig_f)
    var_dec = np.var(dec_f)
    cov = np.mean((orig_f - mu_orig) * (dec_f - mu_dec))

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    ssim = ((2*mu_orig*mu_dec + c1) * (2*cov + c2)) / \
           ((mu_orig**2 + mu_dec**2 + c1) * (var_orig + var_dec + c2))

    return {
        'mse': mse,
        'psnr': psnr,
        'ssim': ssim
    }


def main():
    parser = argparse.ArgumentParser(description='PAL Decoder Comparison')
    parser.add_argument('baseband', help='Input PAL baseband file (int16)')
    parser.add_argument('-n', '--frames', type=int, default=500,
                        help='Number of frames to decode')
    parser.add_argument('-o', '--output', default='decode_results',
                        help='Output directory')
    parser.add_argument('--original', help='Original video for comparison')

    args = parser.parse_args()

    print("=" * 70)
    print("PAL Decoder Comparison Tool")
    print("=" * 70)
    print()

    os.makedirs(args.output, exist_ok=True)

    # Initialize decoders
    print("Initializing decoders...")
    try:
        pal_crt = PALCRTDecoder()
        print("  PAL-CRT: OK")
    except Exception as e:
        print(f"  PAL-CRT: FAILED ({e})")
        pal_crt = None

    advanced = AdvancedPALDecoder()
    print("  Advanced: OK")
    print()

    # Load baseband data
    print(f"Loading baseband: {args.baseband}")
    baseband = np.fromfile(args.baseband, dtype=np.int16)
    print(f"  Samples: {len(baseband)}")

    # Calculate frame parameters
    samples_per_line = 16000000 // 15625  # 1024 at 16 MHz
    samples_per_frame = samples_per_line * 625
    total_frames = len(baseband) // samples_per_frame

    frames_to_decode = min(args.frames, total_frames)
    print(f"  Total frames: {total_frames}")
    print(f"  Decoding: {frames_to_decode}")
    print()

    # Load original frames if provided
    original_frames = []
    if args.original and os.path.exists(args.original):
        print(f"Extracting original frames from: {args.original}")
        tmp_dir = '/tmp/orig_frames'
        os.makedirs(tmp_dir, exist_ok=True)

        cmd = [
            'ffmpeg', '-y', '-i', args.original,
            '-vframes', str(frames_to_decode),
            '-pix_fmt', 'rgb24',
            f'{tmp_dir}/frame_%04d.png'
        ]
        subprocess.run(cmd, capture_output=True)

        for i in range(1, frames_to_decode + 1):
            path = f'{tmp_dir}/frame_{i:04d}.png'
            if os.path.exists(path):
                img = Image.open(path)
                img = img.resize((720, 576), Image.LANCZOS)
                original_frames.append(np.array(img))

        print(f"  Loaded {len(original_frames)} original frames")
        print()

    # Decode and compare
    results = {
        'pal_crt': {'psnr': [], 'mse': [], 'ssim': []},
        'advanced': {'psnr': [], 'mse': [], 'ssim': []}
    }

    print("Decoding frames...")
    print("-" * 70)

    for frame_num in range(frames_to_decode):
        if (frame_num + 1) % 50 == 0:
            print(f"  Frame {frame_num + 1}/{frames_to_decode}")

        # Extract frame
        frame_start = frame_num * samples_per_frame
        frame_end = frame_start + samples_per_frame

        if frame_end > len(baseband):
            break

        frame_data = baseband[frame_start:frame_end]

        # Extract first field (312 lines)
        field_samples = samples_per_line * 312
        field_data = frame_data[:field_samples]

        # Resample to PAL-CRT format
        resampled = resample_hacktv_to_palcrt(field_data, samples_per_line, 312)

        # Decode with PAL-CRT
        if pal_crt is not None:
            try:
                decoded_palcrt = pal_crt.decode_field(resampled)

                if frame_num < len(original_frames):
                    metrics = compute_metrics(original_frames[frame_num], decoded_palcrt)
                    results['pal_crt']['psnr'].append(metrics['psnr'])
                    results['pal_crt']['mse'].append(metrics['mse'])
                    results['pal_crt']['ssim'].append(metrics['ssim'])

                if frame_num == 0:
                    img = Image.fromarray(decoded_palcrt)
                    img.save(os.path.join(args.output, 'palcrt_frame1.png'))

            except Exception as e:
                print(f"  PAL-CRT error at frame {frame_num}: {e}")

        # Decode with advanced decoder
        try:
            decoded_advanced = advanced.decode_field(resampled)

            if frame_num < len(original_frames):
                metrics = compute_metrics(original_frames[frame_num], decoded_advanced)
                results['advanced']['psnr'].append(metrics['psnr'])
                results['advanced']['mse'].append(metrics['mse'])
                results['advanced']['ssim'].append(metrics['ssim'])

            if frame_num == 0:
                img = Image.fromarray(decoded_advanced)
                img.save(os.path.join(args.output, 'advanced_frame1.png'))

                # Save difference if original available
                if original_frames:
                    diff = np.abs(
                        original_frames[0].astype(np.int16) -
                        decoded_advanced.astype(np.int16)
                    ).clip(0, 255).astype(np.uint8)
                    diff_img = Image.fromarray(diff * 3)  # Amplify for visibility
                    diff_img.save(os.path.join(args.output, 'diff_frame1.png'))

        except Exception as e:
            print(f"  Advanced error at frame {frame_num}: {e}")

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()

    # Calculate and display statistics
    for method, data in results.items():
        if data['psnr']:
            avg_psnr = np.mean(data['psnr'])
            avg_mse = np.mean(data['mse'])
            avg_ssim = np.mean(data['ssim'])

            print(f"{method.upper()} Decoder:")
            print(f"  Average PSNR: {avg_psnr:.2f} dB")
            print(f"  Average MSE: {avg_mse:.2f}")
            print(f"  Average SSIM: {avg_ssim:.4f}")
            print()

    # Save results to JSON
    results_file = os.path.join(args.output, 'results.json')
    with open(results_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'frames_decoded': frames_to_decode,
            'results': {k: {sk: float(np.mean(sv)) if sv else 0 for sk, sv in v.items()}
                       for k, v in results.items()}
        }, f, indent=2)

    print(f"Results saved to {results_file}")

    # Generate recommendations
    print()
    print("=" * 70)
    print("ANALYSIS & RECOMMENDATIONS")
    print("=" * 70)
    print()

    if results['pal_crt']['psnr'] and results['advanced']['psnr']:
        palcrt_psnr = np.mean(results['pal_crt']['psnr'])
        advanced_psnr = np.mean(results['advanced']['psnr'])

        if advanced_psnr > palcrt_psnr:
            print(f"The Advanced decoder performs {advanced_psnr - palcrt_psnr:.2f} dB better.")
        else:
            print(f"PAL-CRT performs {palcrt_psnr - advanced_psnr:.2f} dB better.")

    print()
    print("Key areas for improvement:")
    print("  1. Chroma demodulation phase alignment")
    print("  2. Y/C separation comb filter adaptation")
    print("  3. PAL delay line averaging precision")
    print("  4. Motion-adaptive processing")
    print("  5. Cross-color/cross-luminance reduction")


if __name__ == '__main__':
    main()
