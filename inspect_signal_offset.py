#!/usr/bin/env python3
"""
Inspect IQ signal at specific offset to see active video.
"""

import struct
import sys

def inspect_at_offset(filename, offset_samples, num_samples=1024):
    """
    Read samples starting at specific offset.
    """
    print(f"Inspecting {filename} at offset {offset_samples} samples")
    print()

    with open(filename, 'rb') as f:
        # Seek to offset
        f.seek(offset_samples * 4)  # 4 bytes per sample

        samples = []
        for i in range(num_samples):
            data = f.read(4)
            if len(data) < 4:
                break
            i_val, q_val = struct.unpack('<hh', data)
            samples.append((i_val, q_val))

    if not samples:
        print("No samples read!")
        return

    print(f"Read {len(samples)} samples starting at offset {offset_samples}")
    print()

    # Show samples
    print("Samples:")
    for i in range(0, min(len(samples), 100), 10):
        i_val, q_val = samples[i]
        print(f"  Sample {offset_samples + i:7d}: I={i_val:6d}, Q={q_val:6d}")

    print()

    # Statistics
    i_vals = [s[0] for s in samples]
    q_vals = [s[1] for s in samples]

    print("Statistics for this window:")
    print(f"  I channel: min={min(i_vals):6d}, max={max(i_vals):6d}, avg={sum(i_vals)/len(i_vals):8.2f}")
    print(f"  Q channel: min={min(q_vals):6d}, max={max(q_vals):6d}, avg={sum(q_vals)/len(q_vals):8.2f}")
    print()

    # Value distribution
    ranges = [
        (-32768, -20000, "Sync"),
        (-20000, -5000, "Blanking"),
        (-5000, 5000, "Black"),
        (5000, 20000, "Gray"),
        (20000, 32767, "White")
    ]

    for low, high, name in ranges:
        count = sum(1 for i in i_vals if low <= i < high)
        if count > 0:
            print(f"  {name:10s}: {count:4d} samples ({100*count/len(i_vals):5.1f}%)")

if __name__ == "__main__":
    filename = sys.argv[1]

    # Check multiple offsets
    # PAL: 1024 samples/line, so let's check:
    # - Line 0 (sync)
    # - Line 50 (should be active video)
    # - Line 100 (should be active video)

    samples_per_line = 1024

    print("="*60)
    print("LINE 0 (should have sync pulse)")
    print("="*60)
    inspect_at_offset(filename, 0, 100)

    print("\n" + "="*60)
    print(f"LINE 50 (offset {50 * samples_per_line}, should have active video)")
    print("="*60)
    inspect_at_offset(filename, 50 * samples_per_line, 200)

    print("\n" + "="*60)
    print(f"LINE 150 (offset {150 * samples_per_line}, should have active video)")
    print("="*60)
    inspect_at_offset(filename, 150 * samples_per_line, 200)
