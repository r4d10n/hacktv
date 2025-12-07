#!/usr/bin/env python3
"""
Encode/Decode Test Script for hacktv
Tests PAL and NTSC encoding/decoding with quality metrics.

This script:
1. Extracts frames from source video
2. Encodes using hacktv in PAL and NTSC modes
3. Decodes the baseband signal back to video
4. Calculates PSNR and SSIM quality metrics
5. Stores converted clips

Author: Claude
License: GPLv3+
"""

import os
import sys
import subprocess
import argparse
import tempfile
import shutil
from pathlib import Path

# Add tools directory to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

import numpy as np

try:
    from skimage.metrics import structural_similarity as ssim
    from skimage.metrics import peak_signal_noise_ratio as psnr
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False
    print("Warning: scikit-image not installed. Quality metrics will be limited.")


def run_command(cmd, description, timeout=300):
    """Run a command and return success status."""
    print(f"\n{description}...")
    print(f"  Command: {' '.join(cmd[:8])}{'...' if len(cmd) > 8 else ''}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=True
        )
        if result.returncode != 0:
            print(f"  Error: {result.stderr[:500] if result.stderr else 'Unknown error'}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  Timeout after {timeout}s")
        return False
    except Exception as e:
        print(f"  Exception: {e}")
        return False


def extract_frames(video_file, output_dir, max_frames=None, fps=None):
    """Extract frames from video to PNG files."""
    os.makedirs(output_dir, exist_ok=True)

    cmd = ['ffmpeg', '-y', '-i', video_file]

    if max_frames:
        cmd.extend(['-frames:v', str(max_frames)])

    if fps:
        cmd.extend(['-r', str(fps)])

    cmd.extend([
        '-q:v', '1',  # High quality
        os.path.join(output_dir, 'frame_%05d.png')
    ])

    return run_command(cmd, "Extracting frames from source video")


def get_video_info(video_file):
    """Get video info using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
        '-of', 'csv=p=0',
        video_file
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        parts = result.stdout.strip().split(',')
        if len(parts) >= 3:
            width = int(parts[0])
            height = int(parts[1])
            fps_parts = parts[2].split('/')
            fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
            return {'width': width, 'height': height, 'fps': fps}
    except Exception as e:
        print(f"Error getting video info: {e}")

    return None


def encode_with_hacktv(input_video, output_file, mode, sample_rate, duration=None, hacktv_path=None):
    """Encode video using hacktv."""
    if hacktv_path is None:
        hacktv_path = '/home/user/hacktv/src/hacktv'

    cmd = [
        hacktv_path,
        '-o', f'file:{output_file}',
        '-m', mode,
        '-s', str(sample_rate),
        '-t', 'int16',
    ]

    # Add duration limit if specified
    if duration:
        cmd.extend(['--ffmt', 'mp4', '--fopts', f't={duration}'])

    cmd.append(input_video)

    return run_command(cmd, f"Encoding video with hacktv ({mode.upper()} mode)", timeout=600)


def decode_baseband(input_file, output_file, mode, sample_rate):
    """Decode baseband file using our decoder."""
    from decode_baseband import BasebandDecoder

    print(f"\nDecoding baseband ({mode.upper()})...")

    try:
        decoder = BasebandDecoder(
            mode=mode,
            sample_rate=sample_rate,
            output_width=720
        )
        decoder.decode_file(
            input_file,
            output_file,
            max_frames=None,
            progress_interval=25
        )
        return True
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def calculate_psnr_simple(img1, img2):
    """Calculate PSNR between two images."""
    mse = np.mean((img1.astype(float) - img2.astype(float)) ** 2)
    if mse == 0:
        return float('inf')
    max_pixel = 255.0
    return 20 * np.log10(max_pixel / np.sqrt(mse))


def calculate_quality_metrics(original_video, decoded_video, max_frames=100):
    """Calculate quality metrics between original and decoded video."""
    print("\nCalculating quality metrics...")

    # Create temp directories for frame extraction
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_frames_dir = os.path.join(tmpdir, 'original')
        dec_frames_dir = os.path.join(tmpdir, 'decoded')

        # Extract frames from both videos
        extract_frames(original_video, orig_frames_dir, max_frames)
        extract_frames(decoded_video, dec_frames_dir, max_frames)

        # Get frame lists
        orig_frames = sorted([f for f in os.listdir(orig_frames_dir) if f.endswith('.png')])
        dec_frames = sorted([f for f in os.listdir(dec_frames_dir) if f.endswith('.png')])

        if not orig_frames or not dec_frames:
            print("  Error: Could not extract frames")
            return None

        # Use minimum frame count
        num_frames = min(len(orig_frames), len(dec_frames), max_frames)
        print(f"  Comparing {num_frames} frames...")

        psnr_values = []
        ssim_values = []

        try:
            from PIL import Image
        except ImportError:
            print("  Error: PIL not installed")
            return None

        for i in range(num_frames):
            orig_path = os.path.join(orig_frames_dir, orig_frames[i])
            dec_path = os.path.join(dec_frames_dir, dec_frames[i])

            # Load images
            orig_img = np.array(Image.open(orig_path).convert('RGB'))
            dec_img = np.array(Image.open(dec_path).convert('RGB'))

            # Resize decoded to match original if needed
            if orig_img.shape != dec_img.shape:
                from PIL import Image as PILImage
                dec_pil = PILImage.open(dec_path).convert('RGB')
                dec_pil = dec_pil.resize((orig_img.shape[1], orig_img.shape[0]), PILImage.Resampling.LANCZOS)
                dec_img = np.array(dec_pil)

            # Calculate PSNR
            psnr_val = calculate_psnr_simple(orig_img, dec_img)
            psnr_values.append(psnr_val)

            # Calculate SSIM if available
            if HAS_SKIMAGE:
                # Convert to grayscale for SSIM
                orig_gray = np.mean(orig_img, axis=2)
                dec_gray = np.mean(dec_img, axis=2)
                ssim_val = ssim(orig_gray, dec_gray, data_range=255)
                ssim_values.append(ssim_val)

        results = {
            'psnr_mean': np.mean(psnr_values),
            'psnr_min': np.min(psnr_values),
            'psnr_max': np.max(psnr_values),
            'psnr_std': np.std(psnr_values),
            'frames_compared': num_frames,
        }

        if ssim_values:
            results['ssim_mean'] = np.mean(ssim_values)
            results['ssim_min'] = np.min(ssim_values)
            results['ssim_max'] = np.max(ssim_values)

        return results


def print_quality_results(results, mode):
    """Print quality metric results."""
    if results is None:
        print(f"\n{mode.upper()} Quality: Unable to calculate")
        return

    print(f"\n{'='*50}")
    print(f"{mode.upper()} Quality Results ({results['frames_compared']} frames)")
    print(f"{'='*50}")
    print(f"  PSNR (dB):")
    print(f"    Mean: {results['psnr_mean']:.2f}")
    print(f"    Min:  {results['psnr_min']:.2f}")
    print(f"    Max:  {results['psnr_max']:.2f}")
    print(f"    Std:  {results['psnr_std']:.2f}")

    if 'ssim_mean' in results:
        print(f"  SSIM:")
        print(f"    Mean: {results['ssim_mean']:.4f}")
        print(f"    Min:  {results['ssim_min']:.4f}")
        print(f"    Max:  {results['ssim_max']:.4f}")

    # Quality assessment
    psnr_mean = results['psnr_mean']
    if psnr_mean >= 40:
        quality = "Excellent (imperceptible difference)"
    elif psnr_mean >= 35:
        quality = "Very Good (minor differences)"
    elif psnr_mean >= 30:
        quality = "Good (noticeable but acceptable)"
    elif psnr_mean >= 25:
        quality = "Fair (visible artifacts)"
    else:
        quality = "Poor (significant degradation)"

    print(f"\n  Quality Assessment: {quality}")


def run_full_test(source_video, output_dir, sample_rate=16000000, test_duration=5):
    """Run full encode/decode test for PAL and NTSC."""
    print("="*60)
    print("HackTV Encode/Decode Quality Test")
    print("="*60)

    os.makedirs(output_dir, exist_ok=True)

    # Get source video info
    info = get_video_info(source_video)
    if info:
        print(f"\nSource video: {source_video}")
        print(f"  Resolution: {info['width']}x{info['height']}")
        print(f"  Frame rate: {info['fps']:.2f} fps")

    results = {}

    for mode in ['pal', 'ntsc']:
        print(f"\n{'='*60}")
        print(f"Testing {mode.upper()} Mode")
        print(f"{'='*60}")

        # Define output paths
        baseband_file = os.path.join(output_dir, f'{mode}_baseband.bin')
        decoded_file = os.path.join(output_dir, f'{mode}_decoded.mp4')

        # Encode with hacktv
        if not encode_with_hacktv(source_video, baseband_file, mode, sample_rate):
            print(f"  Failed to encode with hacktv ({mode})")
            continue

        # Check baseband file
        if os.path.exists(baseband_file):
            size_mb = os.path.getsize(baseband_file) / 1024 / 1024
            print(f"  Baseband file size: {size_mb:.2f} MB")

        # Decode baseband
        if not decode_baseband(baseband_file, decoded_file, mode, sample_rate):
            print(f"  Failed to decode baseband ({mode})")
            continue

        # Check decoded file
        if os.path.exists(decoded_file):
            size_mb = os.path.getsize(decoded_file) / 1024 / 1024
            print(f"  Decoded file size: {size_mb:.2f} MB")

            # Calculate quality metrics
            metrics = calculate_quality_metrics(source_video, decoded_file, max_frames=50)
            results[mode] = metrics
            print_quality_results(metrics, mode)

    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")

    print(f"\nOutput files saved to: {output_dir}")
    for mode in ['pal', 'ntsc']:
        baseband_file = os.path.join(output_dir, f'{mode}_baseband.bin')
        decoded_file = os.path.join(output_dir, f'{mode}_decoded.mp4')
        if os.path.exists(decoded_file):
            print(f"  {mode.upper()}: {decoded_file}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Test hacktv encode/decode quality with PAL and NTSC'
    )
    parser.add_argument('source', help='Source video file')
    parser.add_argument('-o', '--output', default='./output',
                        help='Output directory (default: ./output)')
    parser.add_argument('-s', '--samplerate', type=int, default=16000000,
                        help='Sample rate in Hz (default: 16000000)')
    parser.add_argument('-d', '--duration', type=float, default=None,
                        help='Test duration in seconds (default: full video)')

    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"Error: Source file not found: {args.source}")
        sys.exit(1)

    run_full_test(
        source_video=args.source,
        output_dir=args.output,
        sample_rate=args.samplerate,
        test_duration=args.duration
    )


if __name__ == '__main__':
    main()
