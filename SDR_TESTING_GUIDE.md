# SDR Hardware Testing Guide - HackTV/HackRX

Complete guide for testing analog TV transmission and reception using SDR hardware.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Hardware Setup](#hardware-setup)
3. [Command-Line Workflows](#command-line-workflows)
4. [Automated Testing](#automated-testing)
5. [Feature Testing](#feature-testing)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Fastest Way to Test (HackRF Loopback)

```bash
# Automated test script (recommended)
./test_hackrf_loopback.sh

# Or manual 2-step process:
# Terminal 1: Transmit
./src/hacktv -o hackrf -m pal -f 474000000 -s 16000000 test

# Terminal 2: Receive
./src/hackrx --sdr -f 474000000 -m pal -s 16000000 -d vsb -o video.yuv --video-format yuv420 --gain 40
```

### View Received Video

```bash
# Play raw YUV
ffplay -f rawvideo -pixel_format yuv420p -video_size 720x576 -framerate 25 video.yuv

# Or convert to MP4
ffmpeg -f rawvideo -pixel_format yuv420p -video_size 720x576 -framerate 25 -i video.yuv -c:v libx264 output.mp4
```

---

## Hardware Setup

### Supported SDR Hardware

| Hardware | Transmit | Receive | Sample Rate | Notes |
|----------|----------|---------|-------------|-------|
| **HackRF One** | ✓ | ✓ | Up to 20 MHz | Best for testing |
| **PlutoSDR** | ✓ | ✓ | Up to 61.44 MHz | High quality |
| **RTL-SDR** | ✗ | ✓ | Up to 3.2 MHz | RX only |
| **LimeSDR** | ✓ | ✓ | Up to 61.44 MHz | Advanced |

### Physical Setup for Loopback Testing

**Option 1: Attenuated Cable (Recommended)**
```
HackRF TX → 30dB Attenuator → HackRF RX
```
- **IMPORTANT**: Always use 30dB+ attenuation to prevent damage!
- Use quality SMA cables
- Keep cables short (< 1m)

**Option 2: Over-the-Air (for testing range)**
```
HackRF TX with antenna → [1-2 meters] → HackRF RX with antenna
```
- Use low TX power
- Comply with local regulations
- Use shielded room if possible

**Option 3: IQ File Method (No hardware loop required)**
```
1. Generate IQ file with hacktv
2. Process with hackrx
```
See [IQ File Workflow](#iq-file-workflow) below.

---

## Command-Line Workflows

### 1. HackRF Transmit → HackRF Receive (Live)

Most realistic test using two HackRF devices:

**Terminal 1 - Transmitter:**
```bash
./src/hacktv \
    -o hackrf \
    -m pal \
    -f 474000000 \
    -s 16000000 \
    --teletext teletext_pages \
    --gain 30 \
    test_pattern.png
```

**Terminal 2 - Receiver (in a separate terminal):**
```bash
./src/hackrx \
    --sdr \
    -f 474000000 \
    -m pal \
    -s 16000000 \
    -d vsb \
    -o received.yuv \
    --video-format yuv420 \
    --teletext-output teletext.txt \
    --nicam \
    --gain 40 \
    --verbose
```

**What to expect:**
- TX should show "Transmitting..."
- RX should show sync lock within 2-3 seconds
- Frame counter should increment
- Video file should grow (~25 MB/second for YUV420)

### 2. IQ File Workflow

Generate IQ file once, test repeatedly without hardware:

**Step 1: Generate IQ file with hacktv**
```bash
./src/hacktv \
    -o file \
    -t int16 \
    -m pal \
    -s 16000000 \
    --teletext teletext_pages \
    test_pattern.png \
    test_pal.iq
```

**Step 2: Receive from IQ file**
```bash
./src/hackrx \
    -i test_pal.iq \
    -m pal \
    -s 16000000 \
    -d fm \
    -o decoded.yuv \
    --video-format yuv420 \
    --teletext-output teletext.txt \
    --verbose
```

**Advantages:**
- No SDR hardware needed
- Reproducible tests
- Fast iteration
- Can share test files

### 3. PlutoSDR Testing

**Transmit (PlutoSDR):**
```bash
./src/hacktv \
    -o plutosdr \
    -m pal \
    -f 474000000 \
    -s 16000000 \
    test_pattern.png
```

**Receive (PlutoSDR):**
```bash
./src/hackrx \
    --sdr \
    --device "driver=plutosdr" \
    -f 474000000 \
    -m pal \
    -s 16000000 \
    -d vsb \
    -o video.yuv \
    --video-format yuv420 \
    --gain 50
```

### 4. RTL-SDR Reception Only

RTL-SDR can receive but not transmit:

```bash
# Generate test signal to file first
./src/hacktv -o file -t int16 -m ntsc -s 2400000 test test_ntsc.iq

# Or use HackRF/PlutoSDR to transmit live

# Receive with RTL-SDR
./src/hackrx \
    --sdr \
    --device "driver=rtlsdr" \
    -f 474000000 \
    -m pal \
    -s 2400000 \
    -d vsb \
    -o video.yuv \
    --video-format yuv420 \
    --gain 40
```

---

## Automated Testing

### Using test_hackrf_loopback.sh

```bash
# Basic test (PAL, 10 seconds)
./test_hackrf_loopback.sh

# NTSC test
./test_hackrf_loopback.sh --mode ntsc --duration 15

# Custom frequency
./test_hackrf_loopback.sh --frequency 850000000 --mode pal

# Help
./test_hackrf_loopback.sh --help
```

**Output Files:**
- `hackrf_test_output/received_video.yuv` - Raw YUV video
- `hackrf_test_output/received_video.mp4` - Encoded video (if ffmpeg available)
- `hackrf_test_output/teletext.txt` - Captured teletext pages

---

## Feature Testing

### Testing NICAM Digital Audio

**Transmit with NICAM:**
```bash
./src/hacktv \
    -o hackrf \
    -m pal \
    -f 474000000 \
    --nicam \
    --audio audio.wav \
    test.png
```

**Receive with NICAM:**
```bash
./src/hackrx \
    --sdr \
    -f 474000000 \
    -m pal \
    -d vsb \
    -o video.yuv \
    --nicam \
    --nicam-output nicam_audio.pcm \
    --verbose
```

**Play NICAM audio:**
```bash
ffplay -f s16le -ar 32000 -ac 2 nicam_audio.pcm
```

### Testing Teletext

**Transmit with Teletext:**
```bash
# Create teletext_pages directory with .tti files
mkdir -p teletext_pages
echo "PN,100
PS,C100
OL,1,Test Page 100
OL,2,This is a test" > teletext_pages/page100.tti

./src/hacktv \
    -o hackrf \
    -m pal \
    -f 474000000 \
    --teletext teletext_pages \
    test.png
```

**Receive Teletext:**
```bash
./src/hackrx \
    --sdr \
    -f 474000000 \
    -m pal \
    -d vsb \
    -o video.yuv \
    --teletext \
    --teletext-output captured_pages.txt \
    --verbose
```

**View captured teletext:**
```bash
cat captured_pages.txt
```

### Testing Different TV Standards

**PAL (625 lines, 25 fps):**
```bash
# TX
./src/hacktv -o hackrf -m pal -f 474000000 -s 16000000 test

# RX
./src/hackrx --sdr -f 474000000 -m pal -s 16000000 -d vsb -o pal.yuv --video-format yuv420
```

**NTSC (525 lines, 29.97 fps):**
```bash
# TX
./src/hacktv -o hackrf -m ntsc -f 474000000 -s 16000000 test

# RX
./src/hackrx --sdr -f 474000000 -m ntsc -s 16000000 -d vsb -o ntsc.yuv --video-format yuv420
```

**SECAM (625 lines, 25 fps):**
```bash
# TX
./src/hacktv -o hackrf -m secam -f 474000000 -s 16000000 test

# RX
./src/hackrx --sdr -f 474000000 -m secam -s 16000000 -d vsb -o secam.yuv --video-format yuv420
```

### Testing Video Output Formats

**Raw RGB24:**
```bash
./src/hackrx -i test.iq -m pal -s 16000000 -d fm -o output.rgb --video-format rgb
```

**Raw YUV420 (smallest, best for encoding):**
```bash
./src/hackrx -i test.iq -m pal -s 16000000 -d fm -o output.yuv --video-format yuv420
```

**Pipe to ffmpeg for direct encoding:**
```bash
./src/hackrx -i test.iq -m pal -s 16000000 -d fm --video-format pipe | \
    ffmpeg -f rawvideo -pixel_format rgb24 -video_size 720x576 -framerate 25 -i - \
           -c:v libx264 -preset fast -crf 22 output.mp4
```

---

## Troubleshooting

### Problem: No sync detected

**Symptoms:**
- RX shows "Searching for sync..."
- No frame counter

**Solutions:**
1. Check frequency match between TX and RX
2. Increase RX gain: `--gain 50`
3. Try different demodulator: `-d vsb` vs `-d fm`
4. Check cable connections / attenuation
5. Verify TX is actually transmitting

### Problem: Sync detected but bad picture

**Symptoms:**
- Frame counter increases
- Video output garbled or noisy

**Solutions:**
1. Check sample rate matches: `-s 16000000` on both TX and RX
2. Verify TV mode matches: `-m pal` on both
3. Try adjusting gain (too high or too low causes issues)
4. Check for RF interference
5. Use better quality cables/attenuators

### Problem: Video output file not created

**Symptoms:**
- hackrx runs but no output file

**Solutions:**
1. Ensure `--video-format` is specified
2. Check disk space
3. Verify output directory exists
4. Check permissions

### Problem: Teletext not decoding

**Symptoms:**
- Empty teletext output file
- No teletext pages captured

**Solutions:**
1. Verify transmitter is sending teletext: `--teletext pages_dir`
2. Check you're receiving VBI lines (lines 7-22 for PAL)
3. Ensure signal quality is good (teletext needs clean signal)
4. Try increasing gain

### Problem: NICAM audio silent

**Symptoms:**
- NICAM decoder enabled but no audio

**Solutions:**
1. Verify NICAM carrier frequency: `--nicam-carrier 6552000`
2. Check transmitter is sending NICAM: `--nicam`
3. NICAM requires good SNR - check signal quality
4. Verify audio output sample rate: `--audio-rate 32000`

### Problem: High CPU usage

**Symptoms:**
- 100% CPU usage
- Dropped frames

**Solutions:**
1. Reduce sample rate to 8 MHz or 4 MHz
2. Use faster demodulator (FM instead of VSB)
3. Disable features you're not testing
4. Use raw output formats (not encoded)

---

## Performance Benchmarks

Expected performance on modern hardware (Intel i5 or better):

| Mode | Sample Rate | CPU Usage | Real-time |
|------|-------------|-----------|-----------|
| PAL/FM | 16 MHz | 25-40% | ✓ |
| PAL/VSB | 16 MHz | 40-60% | ✓ |
| NTSC/FM | 16 MHz | 20-35% | ✓ |
| PAL/FM + NICAM | 16 MHz | 30-50% | ✓ |
| PAL/VSB + Teletext | 16 MHz | 45-70% | ✓ |

---

## Example Test Scenarios

### Scenario 1: Quick Validation Test

**Goal:** Verify basic TX/RX works
**Duration:** 10 seconds
**Command:**
```bash
./test_hackrf_loopback.sh --duration 10
```

### Scenario 2: Long-term Stability Test

**Goal:** Test for memory leaks, stability
**Duration:** 1 hour
**Command:**
```bash
./test_hackrf_loopback.sh --duration 3600
```

### Scenario 3: Multi-Standard Test

**Goal:** Test PAL, NTSC, SECAM support
**Commands:**
```bash
./test_hackrf_loopback.sh --mode pal --duration 30
./test_hackrf_loopback.sh --mode ntsc --duration 30
./test_hackrf_loopback.sh --mode secam --duration 30
```

### Scenario 4: Feature Integration Test

**Goal:** Test all features together
**TX:**
```bash
./src/hacktv -o hackrf -m pal -f 474000000 -s 16000000 \
    --teletext teletext_pages --nicam --audio test.wav test.png
```

**RX:**
```bash
./src/hackrx --sdr -f 474000000 -m pal -s 16000000 -d vsb \
    -o video.yuv --video-format yuv420 \
    --teletext --teletext-output teletext.txt \
    --nicam --nicam-output nicam.pcm \
    --gain 40 --verbose
```

---

## Success Criteria

A successful test should achieve:

- ✓ Sync lock within 3 seconds
- ✓ Stable frame counter (no drops)
- ✓ Video output file size: ~25 MB/second for YUV420
- ✓ Watchable video (recognizable test pattern)
- ✓ Teletext pages captured (if transmitted)
- ✓ NICAM audio audible (if transmitted)
- ✓ CPU usage < 80%
- ✓ No crashes or errors

---

## Additional Resources

- **HackRF Wiki:** https://github.com/greatscottgadgets/hackrf/wiki
- **PlutoSDR Wiki:** https://wiki.analog.com/university/tools/pluto
- **FFmpeg Documentation:** https://ffmpeg.org/documentation.html
- **PAL Standard:** ITU-R BT.470
- **NTSC Standard:** ITU-R BT.1700
- **Teletext Standard:** ETS 300 706
- **NICAM Standard:** ETS 300 163

---

## Reporting Issues

When reporting issues, please include:

1. Full command line used
2. hackrx version: `./src/hackrx --version`
3. SDR hardware model
4. Operating system
5. Sample rate and TV mode
6. Verbose output: `--verbose`
7. If possible, a sample IQ file demonstrating the issue

---

*Last updated: 2025-11-15*
