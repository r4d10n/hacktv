#!/usr/bin/env python3
"""
Detailed inspection of a specific line to understand the pattern.
"""

import struct
import sys

def inspect_line_detail(filename, line_num, samples_per_line=1024):
    """
    Show detailed breakdown of a specific line.
    """
    offset = line_num * samples_per_line

    with open(filename, 'rb') as f:
        f.seek(offset * 4)  # 4 bytes per sample

        samples = []
        for i in range(samples_per_line):
            data = f.read(4)
            if len(data) < 4:
                break
            i_val, q_val = struct.unpack('<hh', data)
            samples.append(i_val)

    print(f"Line {line_num} detailed breakdown ({len(samples)} samples):")
    print()

    # Find sync pulse
    sync_end = 0
    for i, val in enumerate(samples):
        if val > -20000:
            sync_end = i
            break

    print(f"Sync pulse: samples 0-{sync_end} (avg: {sum(samples[:sync_end])/max(1,sync_end):.0f})")

    # Find back porch end
    back_porch_end = sync_end
    for i in range(sync_end, len(samples)):
        if samples[i] > 0:
            back_porch_end = i
            break

    print(f"Back porch: samples {sync_end}-{back_porch_end}")
    print(f"Active video starts at sample: {back_porch_end}")
    print()

    # Sample active video
    print("Active video samples (every 50th sample):")
    for i in range(back_porch_end, len(samples), 50):
        rel_pos = i - back_porch_end
        print(f"  Sample {i:4d} (active +{rel_pos:3d}): {samples[i]:6d}")

    # Show value distribution
    print()
    print("Value distribution in active video:")
    active = samples[back_porch_end:]
    if active:
        ranges = [
            (-32768, -20000, "Sync (shouldn't be here)"),
            (-20000, -5000, "Blanking"),
            (-5000, 5000, "Black"),
            (5000, 20000, "Gray"),
            (20000, 32767, "White")
        ]

        for low, high, name in ranges:
            count = sum(1 for v in active if low <= v < high)
            if count > 0:
                pct = 100 * count / len(active)
                print(f"  {name:30s}: {count:4d} samples ({pct:5.1f}%)")

if __name__ == "__main__":
    filename = sys.argv[1] if len(sys.argv) > 1 else "test_baseband.iq"
    line_num = int(sys.argv[2]) if len(sys.argv) > 2 else 150

    inspect_line_detail(filename, line_num)
