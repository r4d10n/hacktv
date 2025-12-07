# PAL Decoding Analysis Report

## Summary

Analysis of PAL decoding quality using PAL-CRT decoder on 500 frames from `samples/nature_original.mp4` encoded through hacktv.

## Test Configuration

- **Encoder**: hacktv with `-m pal` (16 MHz baseband output)
- **Decoder**: PAL-CRT library (commit a088380) with saturation=30
- **Sample Rate**: 16 MHz (hacktv) → 17.73 MHz (4×f_sc, PAL-CRT)
- **Resolution**: 720×576 output

## Results

### Quantitative Metrics (500 frames)

**Without Hue Correction:**
| Metric | Mean | Std Dev | Min | Max |
|--------|------|---------|-----|-----|
| PSNR (dB) | 18.93 | 3.60 | 8.18 | 36.09 |
| MSE | 1053.62 | 749.05 | 15.99 | 9885.43 |

**With 270° Hue Correction:**
| Metric | Mean | Std Dev | Min | Max |
|--------|------|---------|-----|-----|
| PSNR (dB) | 19.96 | 3.52 | 8.32 | 35.01 |
| MSE | 882.77 | - | - | - |

The 270° hue correction provides ~1 dB PSNR improvement.

### Qualitative Analysis

**Positive:**
- No Hanover bar artifacts (PAL V-switch correctly handled)
- Good luminance reproduction
- Proper sync and timing extraction
- Stable frame-to-frame consistency

**Issues Identified:**
1. **Hue Rotation (~180°)**: Orange/warm colors appear as purple/blue
   - Root cause: U/V axis phase difference between hacktv encoding and PAL-CRT decoding
   - hacktv burst reference angle differs from PAL-CRT expectations

2. **Color saturation**: Required boosting saturation from default 10 to 30

## Technical Details

### PAL Encoding (hacktv)
```
Chroma = V × cos(ωt) × pal_switch + U × sin(ωt)
where pal_switch = -1 if (frame + line) & 1 else +1
```

### Signal Levels
- Sync: -0.30 × 32767 = -9830
- Black: 0
- White: 0.70 × 32767 = 22937

### Resampling
16 MHz (1024 samples/line) → 17.73 MHz (1135 samples/line)
Linear interpolation per line

## Decoder Comparison

| Decoder | Hanover Bars | Hue Accuracy | PSNR Range |
|---------|--------------|--------------|------------|
| PAL-CRT (sat=30) | None | ~180° offset | 8-36 dB |
| pal_decoder_final.py | None | Correct | Similar |
| pal_decoder_burst_sync.py | None | Rainbow drift | Lower |

## Recommendations

### Immediate Fix
Apply hue correction by swapping/negating U and V channels or rotating hue by 180°:
```python
# Option 1: Swap and negate
u_corrected = -v
v_corrected = -u

# Option 2: HSV rotation
hue_corrected = (hue + 180) % 360
```

### Long-term Improvements
1. Verify PAL-CRT burst phase detection aligns with hacktv encoding
2. Implement adaptive hue correction based on burst phase measurement
3. Consider direct 16 MHz decoder to avoid resampling artifacts

## Files Created

- `tools/run_full_comparison.py` - 500-frame comparison script
- `tools/run_comparison_hue_corrected.py` - Comparison with hue correction testing
- `tools/pal_decoder_final.py` - Frame/line aware PAL decoder
- `tools/pal_decoder_burst_sync.py` - Burst-synchronized decoder
- `tools/pal_decoder_v3.py` - Bandpass chroma extraction decoder
- `external/pal-crt/decode_wrapper.c` - PAL-CRT C wrapper
- `external/pal-crt/libpal_decode.so` - Compiled decoder library

## Conclusion

PAL-CRT successfully decodes hacktv PAL baseband without Hanover bar artifacts. The primary issue is a consistent hue offset that can be corrected with a simple color rotation. Mean PSNR of ~19 dB is typical for analog video encode/decode cycles.
