#!/usr/bin/env python3
"""
Quality Metrics Calculator for video comparison.
Calculates PSNR and SSIM between original and decoded videos.

Author: Claude
License: GPLv3+
"""

import os
import sys
import subprocess
import tempfile
import argparse
import numpy as np
from PIL import Image

try:
    from skimage.metrics import structural_similarity as ssim_func
    from skimage.metrics import peak_signal_noise_ratio as psnr_func
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False


def extract_frames(video_file, output_dir, max_frames=None, width=None, height=None):
    """Extract frames from video to PNG files."""
    os.makedirs(output_dir, exist_ok=True)

    cmd = ['ffmpeg', '-y', '-i', video_file]

    if max_frames:
        cmd.extend(['-frames:v', str(max_frames)])

    # Scale to specific size if requested
    if width and height:
        cmd.extend(['-vf', f'scale={width}:{height}:flags=lanczos'])

    cmd.extend([
        '-q:v', '1',  # High quality
        os.path.join(output_dir, 'frame_%05d.png')
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def calculate_psnr_manual(img1, img2):
    """Calculate PSNR between two images."""
    mse = np.mean((img1.astype(np.float64) - img2.astype(np.float64)) ** 2)
    if mse == 0:
        return float('inf')
    max_pixel = 255.0
    return 20 * np.log10(max_pixel / np.sqrt(mse))


def calculate_ssim_manual(img1, img2, window_size=11):
    """Calculate simple SSIM approximation."""
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    mu1 = np.mean(img1)
    mu2 = np.mean(img2)

    sigma1_sq = np.var(img1)
    sigma2_sq = np.var(img2)
    sigma12 = np.cov(img1.flatten(), img2.flatten())[0, 1]

    ssim = ((2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)) / \
           ((mu1 ** 2 + mu2 ** 2 + C1) * (sigma1_sq + sigma2_sq + C2))

    return ssim


def compare_videos(original_video, decoded_video, max_frames=100, resize_to_original=True):
    """
    Compare two videos and calculate quality metrics.

    Returns:
        Dictionary with PSNR and SSIM statistics
    """
    print(f"\nComparing videos:")
    print(f"  Original: {original_video}")
    print(f"  Decoded:  {decoded_video}")

    # Get video info
    def get_video_info(path):
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,nb_frames',
            '-of', 'csv=p=0',
            path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        parts = result.stdout.strip().split(',')
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
        return None, None

    orig_w, orig_h = get_video_info(original_video)
    dec_w, dec_h = get_video_info(decoded_video)

    print(f"  Original resolution: {orig_w}x{orig_h}")
    print(f"  Decoded resolution:  {dec_w}x{dec_h}")

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_frames_dir = os.path.join(tmpdir, 'original')
        dec_frames_dir = os.path.join(tmpdir, 'decoded')

        # Extract frames - resize decoded to original size for fair comparison
        print(f"  Extracting up to {max_frames} frames...")

        if not extract_frames(original_video, orig_frames_dir, max_frames):
            print("  Error extracting original frames")
            return None

        # Resize decoded frames to match original for comparison
        if resize_to_original and orig_w and orig_h:
            if not extract_frames(decoded_video, dec_frames_dir, max_frames, orig_w, orig_h):
                print("  Error extracting decoded frames")
                return None
        else:
            if not extract_frames(decoded_video, dec_frames_dir, max_frames):
                print("  Error extracting decoded frames")
                return None

        # Get frame lists
        orig_frames = sorted([f for f in os.listdir(orig_frames_dir) if f.endswith('.png')])
        dec_frames = sorted([f for f in os.listdir(dec_frames_dir) if f.endswith('.png')])

        if not orig_frames or not dec_frames:
            print("  Error: No frames extracted")
            return None

        num_frames = min(len(orig_frames), len(dec_frames), max_frames)
        print(f"  Comparing {num_frames} frames...")

        psnr_values = []
        ssim_values = []

        for i in range(num_frames):
            orig_path = os.path.join(orig_frames_dir, orig_frames[i])
            dec_path = os.path.join(dec_frames_dir, dec_frames[i])

            # Load images
            orig_img = np.array(Image.open(orig_path).convert('RGB'))
            dec_img = np.array(Image.open(dec_path).convert('RGB'))

            # Resize if dimensions don't match
            if orig_img.shape != dec_img.shape:
                dec_pil = Image.open(dec_path).convert('RGB')
                dec_pil = dec_pil.resize((orig_img.shape[1], orig_img.shape[0]), Image.Resampling.LANCZOS)
                dec_img = np.array(dec_pil)

            # Calculate PSNR
            if HAS_SKIMAGE:
                psnr_val = psnr_func(orig_img, dec_img)
            else:
                psnr_val = calculate_psnr_manual(orig_img, dec_img)
            psnr_values.append(psnr_val)

            # Calculate SSIM
            if HAS_SKIMAGE:
                # For color images, compute on grayscale
                orig_gray = np.mean(orig_img, axis=2).astype(np.uint8)
                dec_gray = np.mean(dec_img, axis=2).astype(np.uint8)
                ssim_val = ssim_func(orig_gray, dec_gray, data_range=255)
            else:
                orig_gray = np.mean(orig_img, axis=2)
                dec_gray = np.mean(dec_img, axis=2)
                ssim_val = calculate_ssim_manual(orig_gray, dec_gray)
            ssim_values.append(ssim_val)

            if (i + 1) % 25 == 0:
                print(f"    Processed {i + 1}/{num_frames} frames")

        results = {
            'frames_compared': num_frames,
            'psnr_mean': np.mean(psnr_values),
            'psnr_min': np.min(psnr_values),
            'psnr_max': np.max(psnr_values),
            'psnr_std': np.std(psnr_values),
            'ssim_mean': np.mean(ssim_values),
            'ssim_min': np.min(ssim_values),
            'ssim_max': np.max(ssim_values),
            'ssim_std': np.std(ssim_values),
        }

        return results


def print_results(results, label):
    """Print quality metrics results."""
    if results is None:
        print(f"\n{label}: Unable to calculate metrics")
        return

    print(f"\n{'='*60}")
    print(f"{label} Quality Metrics ({results['frames_compared']} frames)")
    print(f"{'='*60}")

    print(f"\nPSNR (Peak Signal-to-Noise Ratio) [dB]:")
    print(f"  Mean:     {results['psnr_mean']:.2f} dB")
    print(f"  Min:      {results['psnr_min']:.2f} dB")
    print(f"  Max:      {results['psnr_max']:.2f} dB")
    print(f"  Std Dev:  {results['psnr_std']:.2f} dB")

    print(f"\nSSIM (Structural Similarity Index) [0-1]:")
    print(f"  Mean:     {results['ssim_mean']:.4f}")
    print(f"  Min:      {results['ssim_min']:.4f}")
    print(f"  Max:      {results['ssim_max']:.4f}")
    print(f"  Std Dev:  {results['ssim_std']:.4f}")

    # Quality assessment
    psnr = results['psnr_mean']
    ssim = results['ssim_mean']

    print(f"\nQuality Assessment:")

    # PSNR interpretation
    if psnr >= 40:
        psnr_quality = "Excellent - imperceptible difference from original"
    elif psnr >= 35:
        psnr_quality = "Very Good - minor differences, high quality"
    elif psnr >= 30:
        psnr_quality = "Good - noticeable but acceptable quality"
    elif psnr >= 25:
        psnr_quality = "Fair - visible artifacts present"
    else:
        psnr_quality = "Poor - significant quality degradation"

    # SSIM interpretation
    if ssim >= 0.95:
        ssim_quality = "Excellent structural similarity"
    elif ssim >= 0.90:
        ssim_quality = "Very good structural similarity"
    elif ssim >= 0.80:
        ssim_quality = "Good structural similarity"
    elif ssim >= 0.70:
        ssim_quality = "Fair structural similarity"
    else:
        ssim_quality = "Poor structural similarity"

    print(f"  PSNR: {psnr_quality}")
    print(f"  SSIM: {ssim_quality}")

    # Overall assessment
    if psnr >= 35 and ssim >= 0.90:
        overall = "HIGH QUALITY - Imperceptible or near-imperceptible differences"
    elif psnr >= 30 and ssim >= 0.80:
        overall = "GOOD QUALITY - Minor visible differences"
    elif psnr >= 25 and ssim >= 0.70:
        overall = "ACCEPTABLE QUALITY - Noticeable differences but usable"
    else:
        overall = "LOW QUALITY - Significant degradation"

    print(f"\n  OVERALL: {overall}")


def main():
    parser = argparse.ArgumentParser(description='Calculate video quality metrics')
    parser.add_argument('original', help='Original source video')
    parser.add_argument('decoded', help='Decoded video to compare')
    parser.add_argument('-n', '--frames', type=int, default=100,
                        help='Maximum frames to compare (default: 100)')
    parser.add_argument('-l', '--label', default='Video',
                        help='Label for the comparison (default: Video)')

    args = parser.parse_args()

    if not os.path.exists(args.original):
        print(f"Error: Original file not found: {args.original}")
        sys.exit(1)

    if not os.path.exists(args.decoded):
        print(f"Error: Decoded file not found: {args.decoded}")
        sys.exit(1)

    results = compare_videos(args.original, args.decoded, args.frames)
    print_results(results, args.label)


if __name__ == '__main__':
    main()
