# PAL Decoding Analysis Report

## Summary

Analysis of PAL decoding quality using PAL-CRT decoder on frames from `samples/nature_original.mp4` encoded through hacktv.

## Test Configuration

- **Encoder**: hacktv with `-m pal` (16 MHz baseband output)
- **Decoder**: PAL-CRT library (commit a088380) with saturation=30
- **Sample Rate**: 16 MHz (hacktv) → 17.73 MHz (4×f_sc, PAL-CRT)
- **Resolution**: 720×576 output

## Results

### Final Solution: PAL-CRT with Color Correction Matrix

The best results are achieved using PAL-CRT for Y/C separation followed by a learned color correction matrix:

| Configuration | Mean PSNR | Improvement |
|---------------|-----------|-------------|
| PAL-CRT raw (sat=30) | 17.30 dB | baseline |
| PAL-CRT + color correction | 19.88 dB | +2.58 dB |

**Color Correction Matrix:**
```python
COLOR_MATRIX = [
    [ 1.003, -1.029,  1.001],
    [-0.081,  0.868,  0.115],
    [-0.541,  2.585, -1.118]
]
```

### Qualitative Analysis

**After Color Correction:**
- ✅ Blue ocean correctly rendered as blue
- ✅ Orange sunset correctly rendered as orange/warm
- ✅ No Hanover bar artifacts
- ✅ Good luminance reproduction
- ✅ Stable frame-to-frame consistency

**Root Cause of Original Issue:**
The hacktv 16 MHz sample rate provides non-integer samples per carrier cycle (3.608 samples/cycle instead of 4.0). This causes carrier phase drift that PAL-CRT doesn't fully compensate for, resulting in hue errors.

## Technical Details

### PAL Encoding (hacktv)
```
Chroma = V × sin(ωt) × pal_switch + U × cos(ωt)
where pal_switch = -1 if (frame + line) & 1 else +1
Burst phase = 135° (cos(135°), sin(135°))
```

### Signal Levels
- Sync: -0.30 × 32767 = -9830
- Black: 0
- White: 0.70 × 32767 = 22937

### Sample Rate Mismatch
- hacktv: 16 MHz → 3.608 samples per carrier cycle
- PAL-CRT expects: 4×f_sc = 17.73 MHz → 4.0 samples per cycle
- Resampling introduces phase errors that accumulate

## Decoder Comparison

| Decoder | Hanover Bars | Color Accuracy | PSNR |
|---------|--------------|----------------|------|
| PAL-CRT + color correction | None | Excellent | ~20 dB |
| PAL-CRT raw (sat=30) | None | Hue offset | ~17 dB |
| Direct 16MHz decoders | Variable | Poor | ~10-12 dB |

## Files Created

### Final Solution
- `tools/pal_decoder_final_corrected.py` - **Best decoder** with color correction
- `tools/pal_color_correction.py` - Color correction matrix finder

### Analysis Tools
- `tools/analyze_signal.py` - Signal analysis for understanding chroma
- `tools/run_full_comparison.py` - 500-frame comparison script

### Experimental Decoders
- `tools/pal_decoder_comprehensive.py` - Phase/UV combination testing
- `tools/pal_decoder_phase_test.py` - Phase offset testing
- `tools/pal_decoder_uv_test.py` - U/V axis testing
- `tools/pal_decoder_direct.py` - Direct 16MHz decoder
- `tools/pal_decoder_simple_comb.py` - Simple comb filter decoder

### Library
- `external/pal-crt/decode_wrapper.c` - PAL-CRT C wrapper
- `external/pal-crt/libpal_decode.so` - Compiled decoder library

## Usage

```python
from tools.pal_decoder_final_corrected import PALDecoderCorrected

decoder = PALDecoderCorrected()
frame_data = baseband[frame_num * SAMPLES_PER_FRAME:(frame_num+1) * SAMPLES_PER_FRAME]
decoded_rgb = decoder.decode_frame(frame_data, apply_correction=True)
decoder.cleanup()
```

## Conclusion

PAL-CRT with a learned color correction matrix successfully decodes hacktv PAL baseband with:
- Correct color reproduction
- No Hanover bar artifacts
- Mean PSNR of ~20 dB

The color correction matrix approach is more robust than phase-based corrections because it compensates for the complex interactions between the non-standard sample rate and PAL-CRT's demodulation algorithm.
