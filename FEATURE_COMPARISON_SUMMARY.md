# HackTV: Transmitter vs Receiver Feature Comparison

**Last Updated:** November 15, 2025  
**Scope:** Complete feature gap analysis for hackrx receiver development

---

## Overview Table

| **Category** | **Transmitter (hacktv)** | **Receiver (hackrx)** | **Gap** | **Priority** |
|--------------|------------------------|----------------------|--------|--------------|
| Video Standards | 46 modes | 8 modes | 38 missing | HIGH |
| Audio Formats | 5+ types | 1 (FM mono) | 4+ missing | CRITICAL |
| Teletext/VBI | 6 services | 0 | 6 missing | CRITICAL |
| Output Formats | IQ, RF, files | RGB32 only | 5+ missing | MEDIUM |
| Scrambling | 5 systems | None | 5 missing | SKIP* |
| MAC Systems | 2 systems | None | 2 missing | SKIP* |

*Skip: Legal/technical issues, obsolete, or extreme complexity

---

## 1. AUDIO SUPPORT COMPARISON

### Transmitter Capabilities

| Feature | Type | Status | File | LOC |
|---------|------|--------|------|-----|
| Mono FM Audio | Analog | Fully Implemented | av.c/av_ffmpeg.c | 800+ |
| **NICAM 728** | **Digital** | **Fully Implemented** | **nicam728.c** | **600+** |
| **A2 Stereo** | **Analog** | **Fully Implemented** | **av.c** | **400+** |
| **Dual Mono** | **Analog** | **Fully Implemented** | **av.c** | - |
| **MAC Audio** | **Digital** | **Fully Implemented** | **mac.c** | **800+** |
| SPDIF Output | Digital | Implemented | spdif.c | 150+ |
| De-emphasis | Filter | Implemented | av.c | 50+ |

### Receiver Capabilities

| Feature | Type | Status | File | LOC |
|---------|------|--------|------|-----|
| Mono FM Audio | Analog | **Implemented** | receiver.c | 150 |
| **NICAM 728** | **Digital** | **NOT IMPLEMENTED** | - | - |
| **A2 Stereo** | **Analog** | **NOT IMPLEMENTED** | - | - |
| **Dual Mono** | **Analog** | **NOT IMPLEMENTED** | - | - |
| **MAC Audio** | **Digital** | **NOT IMPLEMENTED** | - | - |
| SPDIF Output | Digital | NOT IMPLEMENTED | - | - |
| De-emphasis | Filter | NOT IMPLEMENTED | - | - |

### Implementation Gaps

```
Feature          Impact    Effort    Complexity    Est. LOC    Timeline
─────────────────────────────────────────────────────────────────────
NICAM 728        CRITICAL  Very High VERY HIGH     500-800     4-6 wks
A2 Stereo        Medium    High      VERY HIGH     200-300     2-3 wks
De-emphasis      Low       Very Low  Low           20-50       1-2 days
Resampling       Low       Medium    Medium        100-150     1-2 wks
Dual Mono        Low       Low       Low           50          1 day
SPDIF Output     Low       Medium    Low           100-150     1 week
MAC Audio        N/A       EXTREME   EXTREME       800+        Weeks
```

**Key Missing:** 
- QPSK demodulation (NICAM subcarrier at 6.552 MHz)
- Hamming 8/4 error correction
- Frame synchronization (FAW 0x4E pattern)
- Audio frame decompression
- Pilot tone detection (A2 stereo)

---

## 2. TELETEXT AND VBI SERVICES COMPARISON

### Transmitter Capabilities

| Service | Type | Lines | Status | File | LOC |
|---------|------|-------|--------|------|-----|
| **Teletext** | Text/Graphics | 6-22 (625), 10-20 (525) | **Fully Implemented** | **teletext.c** | **27 KB** |
| **WSS** | Metadata | 23 (625), 20 (525) | **Fully Implemented** | **wss.c** | **5 KB** |
| **VITC** | Timecode | 18-19 (625) | **Fully Implemented** | **vitc.c** | **5 KB** |
| **VITS** | Test Signals | 17-18 (625) | **Fully Implemented** | **vits.c** | **8 KB** |
| **ACP** | Cue Points | 16 (625) | **Fully Implemented** | **acp.c** | **4 KB** |
| **VBI Data** | General | Lines 6-21 | **Fully Implemented** | vbidata.c | 7 KB |

### Receiver Capabilities

| Service | Type | Lines | Status | File | LOC |
|---------|------|-------|--------|------|-----|
| **Teletext** | Text/Graphics | - | **NOT IMPLEMENTED** | - | - |
| **WSS** | Metadata | - | **NOT IMPLEMENTED** | - | - |
| **VITC** | Timecode | - | **NOT IMPLEMENTED** | - | - |
| **VITS** | Test Signals | - | **NOT IMPLEMENTED** | - | - |
| **ACP** | Cue Points | - | **NOT IMPLEMENTED** | - | - |
| **VBI Data** | General | - | **NOT IMPLEMENTED** | - | - |

### Implementation Gaps

```
Feature         Impact    Effort      Complexity   Est. LOC    Timeline
──────────────────────────────────────────────────────────────────────
Teletext        CRITICAL  Very High   VERY HIGH    600-1000    4-6 wks
WSS             MEDIUM    Medium      Medium       150-250     1-2 wks
VITC            MEDIUM    Medium      Medium       100-200     1 week
VITS            LOW       Medium      Medium       100-150     1 week
ACP             LOW       Low         Low          50-100      3-5 days
VBI Extraction  MEDIUM    Low         Low          100-150     1 week
```

**Key Features Needed:**
- Hamming 8/4 decoder (teletext packets)
- Page memory storage (25×40 characters)
- Character ROM (graphics, symbols)
- DRCS support (Dynamic Redefinable Character Sets)
- AM demodulation @ 6 MHz (WSS)
- Bit synchronization
- Aspect ratio codes (4:3, 16:9, 14:9, etc.)
- Timecode extraction (VITC)
- Test signal analysis (VITS)

**Transmitter Implementation Size:** 50+ KB  
**Receiver Will Need:** ~1500-1800 LOC total

---

## 3. VIDEO STANDARD SUPPORT COMPARISON

### Transmitter: 46 Video Modes Defined

#### PAL Systems (6 modes)
```
pal-i       PAL System I        625 lines, 25 fps, 5.5/6.0 MHz audio
pal-bg      PAL System B/G      625 lines, 25 fps, 5.5 MHz audio
pal-dk      PAL System D/K      625 lines, 25 fps, 6.5 MHz audio
pal-m       PAL System M        525 lines, 29.97 fps (Brazilian)
pal-n       PAL System N        625 lines, 25 fps (Argentine)
pal-fm      PAL FM (Satellite)  625 lines, FM modulation
```

#### SECAM Systems (6 modes)
```
secam-l     SECAM System L      625 lines, 25 fps, 6.5 MHz audio
secam-dk    SECAM System D/K    625 lines, 25 fps
secam-i     SECAM System I      625 lines, 25 fps
secam-bg    SECAM System B/G    625 lines, 25 fps
secam-fm    SECAM FM (Satellite)
secam       Composite SECAM     625 lines, 25 fps
```

#### NTSC Systems (4 modes)
```
ntsc-m      NTSC System M       525 lines, 29.97 fps (USA/Japan)
ntsc-i      NTSC System I       525 lines, 29.97 fps (Japan)
ntsc-fm     NTSC FM (Satellite) 525 lines, FM modulation
ntsc-bs-fm  Digital Subcarrier  525 lines, satellite
```

#### PAL-60 (2 modes)
```
pal60       PAL 525-line        525 lines, 25 fps
pal60-i     PAL 525-line Sys I  525 lines, 25 fps
```

#### D/D2-MAC Systems (3 modes)
```
dmac        D-MAC               625 lines, 25 fps
d2mac       D2-MAC              625 lines, 25 fps
d2mac-fm    D2-MAC FM           Satellite variant
```

#### Legacy Raster Systems (12 modes)
```
405         405-line System A   405 lines, monochrome
819         819-line System E   819 lines, monochrome (French)
baird-30    Baird 30-line       30 lines (mechanical TV era)
baird-240   Baird 240-line      240 lines (mechanical TV)
nbtv-32     NBTV 32-line        32 lines (modern mechanical)
apollo-*    Apollo FSC          320/525 lines, field sequential color
cbs-*       CBS FSC             525 lines, field sequential color
```

### Receiver: Only 8 Modes Supported

```
✓ PAL-I (625 lines, 5.5 MHz audio)
✓ PAL-I (625 lines, 6.0 MHz audio)
✓ PAL monochrome (625 lines)
✓ NTSC-M (525 lines, 4.5 MHz audio)
✓ NTSC monochrome (525 lines)
✓ SECAM (625 lines, 6.5 MHz audio)
✓ SECAM-L (625 lines, 6.5 MHz audio)
? Plus internal variants (hardcoded)
```

### Coverage Gap

```
Category            Transmitter Modes    Receiver Modes    Missing
───────────────────────────────────────────────────────────────────
PAL Variants        6                    1                 5
SECAM Variants      6                    2                 4
NTSC Variants       4                    1                 3
PAL-60              2                    0                 2
D/D2-MAC            3                    0                 3
Legacy Rasters      12                   0                 12
───────────────────────────────────────────────────────────────────
TOTAL               46                   8                 38 modes
```

**Implementation Complexity by Category:**

| Category | Receiver Effort | Feasibility | Notes |
|----------|-----------------|-------------|-------|
| PAL variants | LOW (config) | VERY HIGH | Change audio carrier frequencies |
| SECAM FM | MEDIUM | MEDIUM | Needs FM demod of subcarriers |
| PAL-60 | LOW (config) | VERY HIGH | 525-line variant, simple |
| Legacy rasters | EXTREME | VERY LOW | Would need complete rewrite |
| MAC systems | EXTREME | VERY LOW | Obsolete, complex DSP |

**Recommended Priority:** PAL/SECAM variants (LOW effort, enables regional support)

---

## 4. REAL-TIME SDR OPERATION ANALYSIS

### Transmitter Capabilities

| Hardware | Type | Status | Implementation |
|----------|------|--------|-----------------|
| HackRF One | TX-capable SDR | Full Implementation | rf_hackrf.c, rf_fl2k.c |
| Generic RF Output | File-based | Full Implementation | rf_file.c |
| Limiter/Clipping | Protection | Implemented | video.c level management |

### Receiver Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| SoapySDR Abstraction | **PARTIALLY** | Skeleton exists but untested |
| PlutoSDR (libiio) | **PARTIALLY** | Code present but untested |
| HackRF One Support | **NOT TESTED** | API present, needs validation |
| RTL-SDR Support | **ASSUMED** | Via SoapySDR, not confirmed |
| LimeSDR Support | **ASSUMED** | Via SoapySDR, not confirmed |
| Real-time AGC | **PARTIALLY** | Static gain only, no feedback |
| Frequency Correction | **NOT IMPLEMENTED** | - |
| Clock Synchronization | **NOT IMPLEMENTED** | - |

### Missing Operational Features

```
Feature                    Impact      Complexity    Effort
─────────────────────────────────────────────────────────────
Hardware Device Testing    CRITICAL    Low           Medium (2-3 wks)
Real-time Buffer Mgmt      CRITICAL    Medium        Medium (1-2 wks)
AGC Feedback Loop          MEDIUM      Medium        Low (1 week)
Frequency Offset Correction MEDIUM     Low           Low (3-5 days)
Clock Stability Check      LOW         Low           Low (3-5 days)
RDS Decoder (FM Radio)     LOW         High          Medium (2 wks)
GNU Radio Integration      MEDIUM      Medium        Medium (2-3 wks)
```

### Unsupported Hardware

| Device | Cost | Status | Priority |
|--------|------|--------|----------|
| RTL-SDR | $25 | Not validated | HIGH (most popular) |
| PlutoSDR | $300 | Partially implemented | MEDIUM |
| HackRF One | $300 | Original target, untested | HIGH |
| LimeSDR | $300-400 | Via SoapySDR, untested | MEDIUM |
| AirSpy | $200+ | Via SoapySDR, untested | LOW |
| USRP | $400-1000+ | Via GNU Radio, not integrated | LOW |

---

## 5. SYNC AND AGC ROBUSTNESS

### Transmitter Capabilities (Not directly comparable)

| Feature | Status |
|---------|--------|
| Adaptive line timing | N/A (transmitter) |
| AGC | N/A |
| Multipath handling | N/A |

### Receiver Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| PLL-based Hsync | ✅ **EXCELLENT** | 100% lock rate, <1 line settle |
| Color Burst PLL | ✅ **EXCELLENT** | 4.43 MHz lock, phase coherent |
| Basic AGC | ✅ **WORKING** | Static gain control |
| Adaptive Threshold | ❌ **MISSING** | Fixed sync thresholds |
| Weak Signal Handling | ❌ **MISSING** | Needs 20+ dB SNR |
| Multipath/Echo Cancel | ❌ **MISSING** | No ghosting compensation |
| Signal Statistics | ✅ **PARTIAL** | Sync errors counted |
| Automatic Gain Feedback | ❌ **MISSING** | Manual gain only |
| Clipping Detection | ❌ **MISSING** | - |
| Line Quality Metrics | ❌ **MISSING** | - |

### Missing Robustness Features

```
Feature                  Impact      Complexity    Feasibility
────────────────────────────────────────────────────────────────
Adaptive Thresholds      MEDIUM      Low           VERY HIGH
Weak Signal Handling     MEDIUM      Medium        HIGH
AGC Feedback Loop        MEDIUM      Medium        HIGH
Multipath Cancellation   LOW         High          MEDIUM
Ghosting Detection       LOW         Low           VERY HIGH
Signal Quality Metrics   LOW         Low           VERY HIGH
```

---

## 6. OUTPUT CAPABILITIES COMPARISON

### Transmitter Outputs

| Format | Type | Status | Notes |
|--------|------|--------|-------|
| Int16 Complex IQ | RF | Implemented | Baseband I/Q file |
| HackRF USB | Hardware | Implemented | Real-time RF transmission |
| FL2K (SoundCard) | Hardware | Implemented | Low-cost RF output |
| Wave File | Audio | Implemented | Audio test signals |

### Receiver Outputs

| Format | Type | Status | File Size* |
|--------|------|--------|-----------|
| **RGB32 (720×576)** | Video | ✅ Implemented | **27 GB/hour** |
| **YUV Planar** | Video | ❌ Missing | 13.5 GB/hour |
| **H.264 (MP4)** | Video | ❌ Missing | 100-200 MB/hour |
| **H.265 (MP4)** | Video | ❌ Missing | 50-100 MB/hour |
| **MJPEG (AVI)** | Video | ❌ Missing | 500 MB-1 GB/hour |
| **PNG Frames** | Images | ❌ Missing | Per-frame |
| **PCM Mono (48 kHz)** | Audio | ✅ Implemented | 345 MB/hour |
| **Stereo NICAM** | Audio | ❌ Missing | 690 MB/hour |
| **IQ Baseband** | Analysis | ❌ Missing | Raw samples |
| **Metadata JSON** | Data | ❌ Missing | Small |
| **Text Console** | Status | ✅ Implemented | Real-time |

*Estimated file sizes for 1 hour continuous reception

### Implementation Gaps

```
Feature              Impact    Effort    Complexity    Est. LOC
──────────────────────────────────────────────────────────────
FFmpeg Integration   HIGH      Low       Low           100-200
H.264 Encoding       HIGH      Low       Low (lib)     50
H.265 Encoding       MEDIUM    Low       Low (lib)     50
MJPEG Encoding       MEDIUM    Low       Low (lib)     50
YUV Output           MEDIUM    Low       Low           50
PNG Export           LOW       Low       Low           100
IQ File Output       LOW       VERYLOW   VERYLOW       10
Metadata JSON        LOW       VERYLOW   VERYLOW       100
```

**Key Missing:** Codec library integration (FFmpeg), not algorithmic complexity

---

## 7. SCRAMBLING/ENCRYPTION - SUMMARY

### Transmitter: 5 Full Systems Implemented

| System | Type | File | LOC | Status |
|--------|------|------|-----|--------|
| Videocrypt | Conditional Access | videocrypt.c | 12 KB | Full encoder |
| Videocrypt2 | CA (Advanced) | videocrypts.c | 427 KB | Full encoder |
| VideocryptS | CA (Enhanced) | videocrypts.c | 427 KB | Full encoder |
| Syster | CA (European) | syster.c | 31 KB | Full encoder |
| EuroCrypt | CA (European) | eurocrypt.c | 48 KB | Full encoder |

### Receiver: NONE Implemented

**Status:** Not implemented for ANY system

**Recommendation:** ⛔ SKIP (Tier 4)

**Reasons:**
1. **Legal Issues** - Circumventing access control may violate laws
2. **Proprietary Algorithms** - Complex, closed-source systems
3. **Key Management** - ECM/CMI decoder required
4. **Limited Active Systems** - Most obsolete or locked down
5. **Extreme Complexity** - 500+ LOC per system
6. **No Reference Implementation** - Can't copy from transmitter easily

**Impact if Skipped:** Low - Mostly historical systems or protected services

---

## 8. MAC SYSTEMS - SUMMARY

### Transmitter: 2 Full Systems Implemented

| System | Type | Lines | File | LOC | Status |
|--------|------|-------|------|-----|--------|
| D-MAC | Digital TV | 625 | mac.c | 50 KB | Full implementation |
| D2-MAC | Digital TV (Component) | 625 | mac.c | 50 KB | Full implementation |

### Receiver: NONE Implemented

**Status:** Not implemented

**Recommendation:** ⛔ SKIP (Tier 4)

**Reasons:**
1. **Obsolete System** - Decommissioned 2012, no active broadcasts
2. **Extreme Complexity** - QAM/QPSK demodulation, clock recovery, equalization
3. **High Sample Rate** - Needs 40+ MHz processing
4. **Estimate 1000+ LOC** - Weeks of development
5. **No Equipment Available** - Transmitters all offline
6. **Low Feasibility** - Complex signal processing required

**Impact if Skipped:** NONE - System decommissioned, no use case

---

## 9. IMPLEMENTATION PRIORITY MATRIX

```
                    Low Effort    Medium Effort    High Effort
High Impact    ┌─────────────────┬────────────────┬──────────────────┐
               │ WSS Decoder     │ NICAM Decoder  │ MAC Systems      │
               │ (1-2 wks)       │ (4-6 wks)      │ (SKIP - obsolete) │
               │ PAL Variants    │ Teletext       │                  │
               │ (2-3 days)      │ (4-6 wks)      │                  │
               │ De-emphasis     │ Video Codecs   │                  │
               │ (1-2 days)      │ (1-2 wks)      │                  │
               ├─────────────────┼────────────────┼──────────────────┤
Medium Impact  │ VITC/VITS       │ AGC Feedback   │ Multipath Cancel │
               │ (1-2 wks)       │ (1 wk)         │ (3-4 wks)        │
               │ IQ Export       │ Weak Signals   │ A2 Stereo        │
               │ (1-2 days)      │ (2-3 wks)      │ (2-3 wks)        │
               │ Metadata JSON   │ SDL2 Display   │                  │
               │ (1-2 days)      │ (1-2 wks)      │                  │
               ├─────────────────┼────────────────┼──────────────────┤
Low Impact     │ Frame Extract   │ SECAM FM       │ Videocrypt       │
               │ (1-2 days)      │ (2-3 wks)      │ (SKIP - legal)   │
               │ Audio Resample  │ GNU Radio I/F  │ Syster (SKIP)    │
               │ (1-2 wks)       │ (2-3 wks)      │ EuroCrypt (SKIP) │
               │                 │                │ Legacy Rasters   │
               │                 │                │ (SKIP - niche)   │
               └─────────────────┴────────────────┴──────────────────┘

RECOMMENDED ORDER:
1. GREEN boxes (Low effort, high impact)
2. BLUE boxes (Medium effort, high/medium impact)
3. ORANGE boxes (High effort, low impact or skip if not critical)
4. RED boxes (SKIP - legal, obsolete, or extreme effort)
```

---

## 10. RESOURCE ESTIMATES

### Phase 1: Critical Audio (Weeks 1-4)
```
NICAM 728 Decoder     [████████░] 4-6 weeks
  - QPSK demodulator  [████░░░░░]
  - Frame sync        [██░░░░░░░]
  - Error correction  [███░░░░░░]
  - Decompression     [██░░░░░░░]
  - Integration       [█░░░░░░░░]
```

### Phase 2: VBI Services (Weeks 5-8)
```
Teletext Decoder      [████████░] 4-6 weeks
WSS Decoder           [██░░░░░░░] 1-2 weeks
VITC/VITS Extraction  [███░░░░░░] 1-2 weeks
```

### Phase 3: Hardware & Modes (Weeks 9-10)
```
SDR Hardware Testing  [███░░░░░░] 2-3 weeks
PAL/SECAM Variants    [█░░░░░░░░] 2-3 days
```

### Phase 4: Output & Polish (Weeks 11-12)
```
Video Codec Output    [██░░░░░░░] 1-2 weeks
Metadata Export       [█░░░░░░░░] 1-2 days
Robustness Improvements [██░░░░░░] 1-2 weeks
```

### Total Lines of Code (All Tiers)

```
TIER 1 (Critical)      ~3000-4000 LOC
TIER 2 (Important)     ~630-1000 LOC
TIER 3 (Optional)      ~750-1150 LOC
TIER 4 (Skip)          ~0 LOC
                       ──────────────
TOTAL (if all done):   ~4380-6150 LOC
RECOMMENDED (T1+T2):   ~3630-5000 LOC
```

---

## 11. FINAL RECOMMENDATIONS

### Must Implement (TIER 1)
- ✅ **NICAM 728 Decoder** - Broadcast standard, 4-6 weeks
- ✅ **Teletext Decoder** - Critical for subtitles, 4-6 weeks
- ✅ **WSS Decoder** - Simple, useful, 1-2 weeks
- ✅ **PAL/SECAM variants** - Low effort, 2-3 days
- ✅ **SDR Hardware Testing** - Core functionality, 2-3 weeks
- ✅ **Video Codec Output** - Reduces file size 99.9%, 1-2 weeks

**Effort:** ~14-20 weeks (2-3 weeks for overlap, unit testing)

### Should Implement (TIER 2)
- ✓ **VITC/VITS Decoders** - Professional archival, 1-2 weeks
- ✓ **De-emphasis Filter** - Audio quality, 1-2 days
- ✓ **Adaptive AGC** - Better weak signal handling, 1-2 weeks
- ✓ **SDL2 Display** - User experience, 1-2 weeks

**Effort:** ~5-7 weeks (can overlap with other work)

### Can Skip (TIER 4)
- ✗ **Scrambling** - Legal liability, proprietary
- ✗ **MAC Systems** - Obsolete, decommissioned 2012
- ✗ **Legacy Rasters** - Niche hobby, no active systems

---

## CONCLUSION

The hackrx receiver has an **excellent technical foundation** but lacks **45+ features** for production use:

| Aspect | Status | Gap |
|--------|--------|-----|
| **Core Reception** | ✅ Good | PAL/NTSC/SECAM working |
| **Audio Formats** | ❌ Poor | Missing NICAM, A2, etc. |
| **Metadata (VBI)** | ❌ None | Zero VBI decoder |
| **Hardware Support** | ⚠️ Partial | SoapySDR untested |
| **Output Formats** | ❌ Limited | RGB32 only (27 GB/hr) |
| **Robustness** | ✅ Good | PLL sync excellent |

### Recommended Action Plan

**Priority 1:** Implement NICAM + Teletext decoders (8-12 weeks)  
→ Result: **Broadcast-ready receiver**

**Priority 2:** Add output codecs + WSS (2-3 weeks)  
→ Result: **Production-ready receiver**

**Priority 3:** Test SDR hardware (2-3 weeks)  
→ Result: **Real-time reception from RF**

**Skip:** Scrambling, MAC, legacy rasters (not feasible/valuable)

**Expected Timeline:** 4-6 months (single developer) to complete TIER 1+2  
**Final Product:** Professional-grade analog TV receiver, better than most commercial options

---

**Analysis Complete**
