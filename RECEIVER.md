# HackTV Receiver (hackrx)

## Overview

**hackrx** is an analog TV receiver implementation for HackTV. It complements the existing HackTV transmitter by providing the ability to receive and decode analog TV signals from SDR hardware or IQ files.

## Features

- **Multiple Demodulation Types**:
  - FM (Frequency Modulation) - for satellite signals
  - AM (Amplitude Modulation) - for older systems
  - VSB (Vestigial Sideband) - for terrestrial PAL/NTSC/SECAM

- **Supported TV Standards**:
  - PAL (625 lines, 25 fps)
  - NTSC (525 lines, 29.97 fps)
  - SECAM (625 lines, 25 fps)
  - Monochrome versions of all above

- **Color Decoding**:
  - PAL color decoder with V-switch alternation
  - NTSC color decoder with I/Q demodulation
  - SECAM color decoder with FM subcarriers
  - Monochrome (grayscale) output

- **Audio Support**:
  - FM audio demodulation
  - Configurable audio carriers
  - PCM audio output

- **Sync Detection**:
  - Horizontal and vertical sync detection
  - AGC (Automatic Gain Control)
  - Line and frame timing recovery

## Installation

The receiver is built alongside the main hacktv transmitter:

```bash
cd src
make
make install
```

This will build both `hacktv` (transmitter) and `hackrx` (receiver).

## Usage

### Basic Usage

```bash
hackrx -i input.iq -o output.rgb -m pal -d fm -s 16000000
```

### Command Line Options

```
-i, --input <file>             Input IQ file (int16 complex samples)
-o, --output <file>            Output video file (raw RGB)
-a, --audio-output <file>      Output audio file (raw PCM)
-m, --mode <name>              TV mode (pal, ntsc, secam). Default: pal
-s, --samplerate <value>       Sample rate in Hz. Default: 16000000
-d, --demod <type>             Demodulator type (fm, am, vsb). Default: fm
-f, --frequency <value>        RF frequency in Hz (for future SDR input)
    --if <value>               IF frequency for VSB demod. Default: 6000000
    --audio-carrier <value>    Audio carrier frequency in Hz
    --audio-rate <value>       Audio output sample rate. Default: 48000
    --no-audio                 Disable audio decoding
-v, --verbose                  Enable verbose output
-h, --help                     Display help
    --version                  Display version
```

### Supported TV Modes

- `pal` - PAL System I (625 lines, 25fps, 6 MHz audio carrier)
- `pal-i` - PAL System I with 6 MHz audio
- `pal-mono` - PAL monochrome
- `ntsc` - NTSC System M (525 lines, 29.97fps, 4.5 MHz audio carrier)
- `ntsc-m` - NTSC System M
- `ntsc-mono` - NTSC monochrome
- `secam` - SECAM (625 lines, 25fps, 6.5 MHz audio carrier)
- `secam-l` - SECAM System L

### Demodulator Types

- `fm` - FM demodulation (best for satellite signals)
- `am` - AM envelope detection (for older systems)
- `vsb` - Vestigial sideband (for terrestrial broadcast signals)

## Examples

### Example 1: Receive PAL Signal from IQ File

```bash
# Generate a test PAL signal
hacktv -o test.iq -m pal -s 16000000 -t int16 test

# Receive and decode it
hackrx -i test.iq -o output.rgb -m pal -d fm -s 16000000

# View the output
ffplay -f rawvideo -pixel_format rgb32 -video_size 720x576 -framerate 25 output.rgb
```

### Example 2: Receive NTSC with Audio

```bash
# Generate NTSC signal
hacktv -o ntsc_test.iq -m ntsc -s 16000000 -t int16 test

# Receive with audio output
hackrx -i ntsc_test.iq -o video.rgb -a audio.pcm -m ntsc -d fm -s 16000000

# Play video
ffplay -f rawvideo -pixel_format rgb32 -video_size 720x480 -framerate 29.97 video.rgb

# Play audio
ffplay -f s16le -ar 48000 -ac 1 audio.pcm
```

### Example 3: Receive SECAM Signal

```bash
# Generate SECAM signal
hacktv -o secam_test.iq -m secam -s 16000000 -t int16 test

# Receive and decode
hackrx -i secam_test.iq -o secam_out.rgb -m secam -d fm -s 16000000

# View output
ffplay -f rawvideo -pixel_format rgb32 -video_size 720x576 -framerate 25 secam_out.rgb
```

### Example 4: Using VSB Demodulation

```bash
# VSB is better for terrestrial-like signals
hackrx -i terrestrial.iq -o video.rgb -m pal -d vsb --if 6000000 -s 16000000
```

## Output Formats

### Video Output

The video output is raw RGB data with the following format:
- Pixel format: RGB32 (RGBA, 32-bit per pixel)
- Resolution: 720x576 for PAL/SECAM, 720x480 for NTSC
- No headers or compression
- Can be viewed with ffplay or converted with ffmpeg

### Audio Output

The audio output is raw PCM data:
- Format: Signed 16-bit little-endian
- Sample rate: 48000 Hz (default, configurable)
- Channels: Mono (1 channel)

## Architecture

The receiver implements the following signal processing chain:

```
IQ Input → Demodulator → Baseband Video → Sync Detector → Line Buffer
                                                              ↓
                                                      Color Decoder
                                                              ↓
                                                      YUV → RGB
                                                              ↓
                                                        Frame Buffer
```

### Components

1. **Demodulator**: Converts RF signal to baseband video
   - FM: Phase discriminator
   - AM: Envelope detector
   - VSB: Complex mixer with carrier recovery

2. **Sync Detector**: Detects horizontal and vertical sync pulses
   - Threshold-based sync detection
   - AGC for level adjustment
   - Line and frame counting

3. **Color Decoder**: Extracts color information
   - PAL: Quadrature demodulation with V-switch
   - NTSC: I/Q demodulation
   - SECAM: FM demodulation of Dr/Db subcarriers

4. **Audio Decoder**: Extracts audio subcarrier
   - FM demodulation
   - De-emphasis filtering (TODO)
   - Resampling to output rate (TODO)

## Current Limitations

This is an initial implementation with the following limitations:

1. **Input**: Currently only supports IQ files (int16 complex samples)
   - SDR hardware input (HackRF, SoapySDR) planned for future

2. **Filtering**: FIR filters are not fully implemented
   - Works without filtering but quality could be improved

3. **Sync Detection**: Basic threshold-based sync
   - Could be improved with PLL-based sync recovery

4. **Color Decoding**: Simplified color demodulation
   - No burst phase lock
   - No chroma filtering

5. **Audio**: Basic FM demodulation only
   - No de-emphasis filtering
   - No NICAM support yet

6. **Performance**: Not optimized for real-time operation

## Future Enhancements

- SDR hardware input (HackRF, RTL-SDR, LimeSDR via SoapySDR)
- Proper FIR filtering for improved quality
- PLL-based sync and color burst locking
- NICAM digital audio decoder
- Real-time display output
- Teletext decoding
- Videocrypt descrambling
- GUI interface

## Technical Details

### Input File Format

The input IQ file must be in the following format:
- Type: int16 (signed 16-bit integers)
- Layout: Interleaved I/Q pairs [I, Q, I, Q, ...]
- Byte order: Little-endian
- Sample rate: Specified with `-s` parameter

### Signal Levels

The receiver expects the following signal levels (16-bit signed):
- Sync level: -32768 to -24576
- Blanking level: -10922
- Black level: 0
- White level: 32767

### Color Subcarriers

- PAL: 4.43361875 MHz
- NTSC: 3.579545 MHz
- SECAM Dr: 4.40625 MHz (R-Y)
- SECAM Db: 4.25 MHz (B-Y)

## Troubleshooting

### No sync detected

- Check that the input file has the correct format (int16 complex)
- Verify the sample rate matches the signal
- Try adjusting the demodulator type (fm/am/vsb)
- Use verbose mode (`-v`) to see sync status

### No color in output

- Verify the correct TV mode is selected
- Some test patterns may be monochrome
- Check that the color subcarrier is present in the signal

### Distorted video

- Check sample rate matches the transmit sample rate
- Try different demodulator types
- Verify the IF frequency for VSB mode

### No audio output

- Ensure `-a` parameter is specified
- Check the audio carrier frequency matches the transmitter
- Some modes may not have audio enabled

## License

This receiver implementation follows the same license as HackTV:
- GNU General Public License version 3 or later
- See COPYING file for details

## Author

Receiver implementation: 2025

Based on HackTV by Philip Heron <phil@sanslogic.co.uk>

## See Also

- HackTV Transmitter: `hacktv --help`
- HackTV README: `../README`
- FFmpeg documentation: https://ffmpeg.org/documentation.html
