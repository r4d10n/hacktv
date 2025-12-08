# PAL Decoding from hacktv Baseband: Architecture and Experiments

## Overview

This document describes the architecture and experiments conducted to decode PAL color video from hacktv's 16MHz baseband output.

## Problem Statement

hacktv generates PAL baseband signals at 16 MHz sample rate. The goal was to decode these signals with correct color reproduction. The challenge: PAL color encoding uses a 4.43 MHz subcarrier, and proper decoding requires precise phase alignment.

## Signal Characteristics

### hacktv Output Format
- **Sample rate**: 16 MHz
- **Samples per line**: 1024 (64 µs line period)
- **Lines per frame**: 625 (PAL standard)
- **Data format**: int16 (-32768 to +32767)
- **Sync level**: -9830 (-0.30 × 32767)
- **White level**: +22937 (+0.70 × 32767)
- **Burst location**: samples 90-126 (~5.6 µs from line start)

### PAL Color Encoding
- **Subcarrier frequency (f_sc)**: 4,433,618.75 Hz
- **Samples per carrier cycle at 16 MHz**: 3.607 (non-integer!)
- **Phase advance per sample**: 99.76° (not 90°)
- **Phase drift per line**: ~270° cumulative

## Experiments Conducted

### Experiment 1: PAL-CRT Library Integration

**Approach**: Use the PAL-CRT library (designed for CRT simulation) to decode hacktv signals.

**Problem**: PAL-CRT expects signals at 17.73 MHz (4 × f_sc = exactly 4 samples per carrier cycle).

**Results**:
- Direct feeding of 16 MHz signal: Grayscale output only
- Resampling to 17.73 MHz: Colors appeared but with wrong hues
- PAL-CRT's own roundtrip (encode→decode): Perfect colors

**Conclusion**: Format mismatch between hacktv and PAL-CRT timing conventions.

### Experiment 2: Simple Resampling (16 MHz → 17.73 MHz)

**Approach**: Linear/cubic interpolation to resample from 16 MHz to 17.73 MHz.

**Results**: Grayscale or severely distorted colors.

**Analysis**: Simple resampling doesn't preserve carrier phase relationships. The chroma information is encoded in the phase of the 4.43 MHz carrier, and resampling at arbitrary points loses this information.

### Experiment 3: Phase-Locked Resampling

**Approach**: Resample such that each output sample corresponds to exact carrier phase positions (0°, 90°, 180°, 270°).

**Results**: Colors visible but cycling per line (rainbow banding effect).

**Analysis**: The burst phase varies wildly between lines due to non-integer cycles per line at 16 MHz. Each line has a different phase relationship.

### Experiment 4: Time-Shift Alignment

**Approach**: Apply time shifts to align hacktv burst position with PAL-CRT's expected burst position.

**Configuration**:
- hacktv burst at ~5.6 µs
- PAL-CRT expects burst at ~7.1 µs
- Applied shift: ~1.5 µs

**Results**: Colors still wrong (hue rotation of ~90-180°).

**Analysis**: Time shifting alone doesn't correct the carrier phase relationship throughout each line.

### Experiment 5: Chroma Phase Rotation

**Approach**: Extract chroma, apply phase rotation using Hilbert transform, recombine with luma.

**Results**: Phase correction had minimal effect; error values similar across all tested phases.

**Conclusion**: The issue wasn't a simple fixed phase offset.

### Experiment 6: YUV Extraction with Burst-Locked Demodulation (SUCCESS)

**Approach**: Bypass PAL-CRT entirely. Implement direct PAL decoding:
1. Extract burst phase from each line
2. Create burst-locked carriers for demodulation
3. Bandpass filter to extract chroma
4. Demodulate to get U and V components
5. Apply PAL V-switch (invert V on alternate lines)
6. Convert YUV to RGB

**Implementation** (`tools/hacktv_yuv_to_palcrt.py`):

```python
def extract_burst_phase(line_data):
    """Extract burst phase from samples 90-126."""
    omega = 2 * np.pi * F_SC / HACKTV_SR
    burst = line_data[90:126]
    t = np.arange(90, 126)
    burst_sin = np.mean(burst * np.sin(t * omega))
    burst_cos = np.mean(burst * np.cos(t * omega))
    return np.arctan2(burst_sin, burst_cos)

def demodulate_chroma(line_data, burst_phase):
    """Demodulate using burst-locked carriers."""
    # Phase correction to align burst to 135°
    phase_correction = np.deg2rad(135) - burst_phase

    # Create locked carriers
    cos_carrier = np.cos(t * omega + phase_correction)
    sin_carrier = np.sin(t * omega + phase_correction)

    # Bandpass filter and demodulate
    chroma = bandpass_filter(line_data, f_sc ± 1.3 MHz)
    u = lowpass(chroma * cos_carrier)
    v = lowpass(chroma * sin_carrier)
    return u, v
```

**Results**: Correct colors on all test content:
- Color bars: All 8 colors correct
- Nature video frame 101: Blue ocean/sky, green vegetation
- Nature video frame 251: Orange/red sunset
- Various frames: Consistent color accuracy

## Architecture

### Final Decoder Pipeline

```
┌─────────────────┐
│ hacktv 16MHz    │
│ int16 baseband  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Line Extraction │  1024 samples/line
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────────┐
│ Luma  │ │  Burst    │
│ LPF   │ │  Phase    │
│ 4MHz  │ │  Extract  │
└───┬───┘ └─────┬─────┘
    │           │
    │     ┌─────┴─────┐
    │     ▼           ▼
    │ ┌───────┐ ┌───────┐
    │ │ cos   │ │ sin   │  Burst-locked
    │ │carrier│ │carrier│  carriers
    │ └───┬───┘ └───┬───┘
    │     │         │
    │     ▼         ▼
    │ ┌───────────────┐
    │ │ Chroma BPF    │  4.43 MHz ± 1.3 MHz
    │ │ + Demodulate  │
    │ └───────┬───────┘
    │         │
    │    ┌────┴────┐
    │    ▼         ▼
    │ ┌─────┐ ┌─────┐
    │ │  U  │ │  V  │
    │ │ LPF │ │ LPF │
    │ └──┬──┘ └──┬──┘
    │    │       │
    │    │  ┌────┴────┐
    │    │  ▼         │
    │    │ PAL V-sw   │  Invert V on odd lines
    │    │            │
    ▼    ▼            ▼
┌─────────────────────────┐
│     YUV to RGB          │
│   BT.601 Matrix         │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────┐
│   RGB Output    │
│   720 × 312     │
└─────────────────┘
```

### Key Components

1. **Burst Phase Extraction**: Measures the actual carrier phase in the burst region of each line
2. **Burst-Locked Carriers**: Generates sin/cos carriers phase-aligned to the burst
3. **Bandpass Filter**: Isolates chroma around 4.43 MHz
4. **Quadrature Demodulation**: Extracts U and V using the locked carriers
5. **PAL V-Switch**: Corrects for PAL's line-alternating V phase inversion
6. **YUV→RGB**: Standard BT.601 color matrix conversion

## Key Findings

### Why PAL-CRT Integration Failed

1. **Timing mismatch**: PAL-CRT expects sync at samples 28-110; hacktv has sync at 0-75
2. **Sample rate assumption**: PAL-CRT assumes exactly 4 samples/cycle; 16 MHz gives 3.6 samples/cycle
3. **Phase continuity**: PAL-CRT relies on consistent sample-to-phase mapping that doesn't hold at 16 MHz

### Why Burst-Locked Decoding Works

1. **Per-line phase reference**: Each line's burst provides the correct phase reference for that line
2. **No resampling needed**: Works directly with 16 MHz samples
3. **Handles phase drift**: The per-line burst measurement automatically compensates for cumulative phase drift

### Signal Quality Requirements

The decoder works correctly when:
- Sync pulses are present and at correct level (-9830)
- Burst is present with sufficient amplitude (~2000 units)
- Line timing is consistent (1024 samples/line)

Some test patterns failed due to corrupted encoding (missing/wrong sync levels), not decoder issues.

## Files

| File | Purpose |
|------|---------|
| `tools/hacktv_yuv_to_palcrt.py` | Main decoder - burst-locked YUV extraction |
| `tools/analyze_palcrt_encoded.py` | Analyzes PAL-CRT's encoded signal format |
| `tools/analyze_signal_detailed.py` | Detailed hacktv signal analysis |
| `tools/resample_with_phase_correction.py` | Phase correction experiments (deprecated) |
| `samples/yuv_decoded/` | Sample decoded frames |

## Usage

```bash
# Decode a single frame
python3 tools/hacktv_yuv_to_palcrt.py \
    --input /path/to/baseband.bin \
    --frame 100 \
    --output frame100.png \
    --no-roundtrip

# The decoder uses memory mapping for efficient access to large files
```

## Conclusions

1. **Direct burst-locked YUV decoding is the correct approach** for hacktv's 16 MHz PAL signals
2. **Resampling to PAL-CRT's rate doesn't work** due to carrier phase discontinuities
3. **Per-line burst phase measurement is essential** to handle the non-integer samples per carrier cycle
4. **PAL V-switch must be applied** to get correct colors (invert V on alternate lines)

The final decoder successfully extracts correct colors from hacktv PAL baseband, validated on:
- Standard color bar patterns
- Nature video with diverse colors (blue sky/ocean, green vegetation, orange sunsets)
- Multiple frames across different scenes
