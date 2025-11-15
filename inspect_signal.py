#!/usr/bin/env python3
"""
Inspect IQ signal file to see what it contains.
"""

import struct
import sys

def inspect_iq_file(filename, num_samples=10000):
    """
    Read and analyze IQ file.
    """
    print(f"Inspecting IQ file: {filename}")
    print()

    with open(filename, 'rb') as f:
        samples = []
        for i in range(num_samples):
            data = f.read(4)  # 2 bytes I + 2 bytes Q
            if len(data) < 4:
                break
            i_val, q_val = struct.unpack('<hh', data)
            samples.append((i_val, q_val))

    if not samples:
        print("No samples read!")
        return

    print(f"Read {len(samples)} samples")
    print()

    # Print first few samples
    print("First 20 samples:")
    for i in range(min(20, len(samples))):
        i_val, q_val = samples[i]
        print(f"  Sample {i:4d}: I={i_val:6d}, Q={q_val:6d}")

    print()

    # Statistics
    i_vals = [s[0] for s in samples]
    q_vals = [s[1] for s in samples]

    print("Statistics:")
    print(f"  I channel: min={min(i_vals):6d}, max={max(i_vals):6d}, avg={sum(i_vals)/len(i_vals):8.2f}")
    print(f"  Q channel: min={min(q_vals):6d}, max={max(q_vals):6d}, avg={sum(q_vals)/len(q_vals):8.2f}")
    print()

    # Look for sync pulses (large negative values)
    sync_threshold = -20000
    sync_count = sum(1 for i in i_vals if i < sync_threshold)

    print(f"Sync pulse detection (I < {sync_threshold}):")
    print(f"  Samples below threshold: {sync_count} ({100*sync_count/len(i_vals):.1f}%)")
    print()

    # Find transitions
    print("Sample value distribution:")
    ranges = [
        (-32768, -20000, "Sync level"),
        (-20000, -5000, "Blanking"),
        (-5000, 5000, "Black level"),
        (5000, 20000, "Gray/midtone"),
        (20000, 32767, "White level")
    ]

    for low, high, name in ranges:
        count = sum(1 for i in i_vals if low <= i < high)
        print(f"  {name:15s}: {count:6d} samples ({100*count/len(i_vals):5.1f}%)")

    print()

    # Look for periodic sync pulses
    print("Looking for periodic sync pattern:")
    sync_positions = [i for i, val in enumerate(i_vals) if val < sync_threshold]
    if len(sync_positions) > 1:
        gaps = [sync_positions[i+1] - sync_positions[i] for i in range(min(10, len(sync_positions)-1))]
        print(f"  First 10 gaps between sync pulses: {gaps}")
        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            print(f"  Average gap: {avg_gap:.1f} samples")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: inspect_signal.py <iq_file>")
        sys.exit(1)

    filename = sys.argv[1]
    num_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 10000

    inspect_iq_file(filename, num_samples)
