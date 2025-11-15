# Analog TV Receiver Decoder Improvements

## Summary

This document summarizes the critical fixes and improvements made to the analog TV receiver based on expert code review, along with known issues requiring further investigation.

## Implemented Fixes

### 1. NTSC I/Q to U/V Conversion (✅ COMPLETED)

**Issue**: The original conversion `u = (i + q) / 2; v = (i - q) / 2` was incorrect.

**Fix**: Implemented proper 33° rotation matrix:
```c
/* U = I * cos(33°) + Q * sin(33°) */
/* V = -I * sin(33°) + Q * cos(33°) */
int32_t u_tmp = ((int32_t)i * 27484 + (int32_t)q * 17845) >> 15;
int32_t v_tmp = (-(int32_t)i * 17845 + (int32_t)q * 27484) >> 15;
```

**Impact**: Corrects significant hue errors in NTSC color decoding.

**Location**: `src/receiver.c:656-664`

### 2. Buffer Structure Additions (✅ COMPLETED)

**PAL Decoder**:
- ✅ 1H delay line for comb filter: `int16_t *prev_line`
- ✅ Delay line length tracking: `int prev_line_length`

**NTSC Decoder**:
- ✅ 1H delay line for comb filter: `int16_t *prev_line`
- ✅ Delay line length tracking: `int prev_line_length`

**SECAM Decoder**:
- ✅ 1H delay lines for U/V storage: `int16_t *prev_u`, `int16_t *prev_v`
- ✅ Bandpass filter pointers: `fir_int16_t *dr_filter`, `fir_int16_t *db_filter`

**Location**: `src/receiver.h:112-115, 140-142, 157-164`

### 3. Improved Bounds Checking (✅ COMPLETED)

**Issue**: `chroma_bandpass()` and `chroma_comb_filter()` could access out-of-bounds memory.

**Fix**: Added proper bounds checking:
```c
if(x < taps)
{
    return line[x];
}
return 0;  /* Out of bounds */
```

**Location**: `src/receiver.c:334-359`

## Partially Implemented (Disabled Due to Buffer Issues)

### 4. NTSC Comb Filter (⚠️ DISABLED)

**Design**: Implements 1H delay comb filter for NTSC Y/C separation:
```c
/* Luma = (current + previous) / 2 */
/* Chroma = (current - previous) / 2 */
```

**Status**: Code written but disabled due to buffer overflow issues.

**Location**: `src/receiver.c:641-654` (commented out)

### 5. SECAM 1H Delay Line Logic (⚠️ PARTIAL)

**Design**: Properly stores and retrieves U/V values from alternating lines.

**Status**: Structure allocated, logic implemented but untested due to buffer issues.

**Location**: `src/receiver.c:787-831`

## Known Issues

### Critical: Buffer Overflow (❌ UNRESOLVED)

**Symptom**: Stack smashing detected during runtime, even with comb filters disabled.

**Investigation**:
- Persists even when ALL new decoder code is disabled
- Suggests deep architectural issue with buffer management
- Likely related to interaction between:
  - Line buffer offsets (`line_buffer + active_start`)
  - Decoder expectations of full vs. partial line buffers
  - PLL burst processing requirements

**Recommended Action**:
1. Comprehensive audit of buffer sizes and offsets throughout `rx_process_samples()`
2. Verify `line_buffer` allocation size vs. usage
3. Check framebuffer pointer arithmetic
4. Consider using address sanitizer (`-fsanitize=address`) for debugging

### Architectural Issues (from Expert Review)

#### SECAM Decoder
**Issue**: FM demodulator receives composite signal directly instead of basebanded chroma.

**Proper Architecture**:
1. Bandpass filter at Dr/Db subcarrier frequency
2. Frequency translation to baseband (0 Hz IF)
3. Feed basebanded I/Q to FM demodulator

**Status**: TODO markers added, bandpass filter structures created, implementation pending.

#### Missing FIR Filters
**Issue**: Crude 3-tap bandpass used instead of proper FIR filters.

**Recommendation**: Use existing `fir_int16_t` infrastructure to create:
- Chroma bandpass filters (PAL: 4.43 MHz, NTSC: 3.58 MHz, ±1.3 MHz BW)
- Low-pass filters for demodulated signals

## Testing Status

- ✅ Compiles cleanly (with warnings about unused functions)
- ❌ Runtime crash prevents validation
- ⚠️  NTSC I/Q fix unvalidated
- ⚠️  Comb filters unvalidated
- ⚠️  SECAM improvements unvalidated

## Next Steps

1. **CRITICAL**: Resolve buffer overflow issue
   - Use debugger or address sanitizer
   - Audit all buffer allocations and accesses

2. **HIGH**: Implement proper FIR filters
   - Design filter coefficients
   - Replace `chroma_bandpass()` with proper FIR

3. **MEDIUM**: Complete SECAM baseband conversion
   - Implement bandpass + frequency translation
   - Test with SECAM signals

4. **LOW**: Optimize FM demodulator
   - Replace `atan2()` with cross-product discriminator

## Files Modified

- `src/receiver.h`: Added buffer structures to all decoders
- `src/receiver.c`:
  - NTSC I/Q to U/V rotation fix
  - Bounds checking improvements
  - Comb filter implementations (disabled)
  - SECAM 1H delay logic (disabled)
  - PLL processing moved to higher level (disabled)

## References

- Expert code review analysis (detailed in original report)
- ITU-R BT.601: Digital encoding of component signals
- PAL specification: V-phase alternation
- NTSC specification: I/Q color space
- SECAM specification: FM chroma on alternating lines
