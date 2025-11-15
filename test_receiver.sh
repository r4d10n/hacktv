#!/bin/bash
# Test script for HackTV Receiver (hackrx)
# This script generates test signals and receives them to verify functionality

set -e  # Exit on error

echo "=========================================="
echo "HackTV Receiver Test Script"
echo "=========================================="
echo ""

# Check if hacktv and hackrx exist
if [ ! -f "src/hacktv" ]; then
    echo "Error: hacktv not found. Please run 'make' first."
    exit 1
fi

if [ ! -f "src/hackrx" ]; then
    echo "Error: hackrx not found. Please run 'make' first."
    exit 1
fi

# Create temporary directory for test files
TESTDIR=$(mktemp -d -t hacktv-test-XXXXXX)
echo "Using temporary directory: $TESTDIR"
echo ""

# Test 1: PAL with FM demodulation
echo "=========================================="
echo "Test 1: PAL Signal with FM Demodulation"
echo "=========================================="
echo ""

echo "Generating PAL test signal..."
./src/hacktv -o "$TESTDIR/pal_fm.iq" -m pal -s 16000000 -t int16 --output-type complex test 2>&1 | head -20

if [ -f "$TESTDIR/pal_fm.iq" ]; then
    echo "✓ Test signal generated successfully"
    ls -lh "$TESTDIR/pal_fm.iq"
    echo ""

    echo "Receiving PAL signal..."
    ./src/hackrx -i "$TESTDIR/pal_fm.iq" -o "$TESTDIR/pal_output.rgb" -m pal -d fm -s 16000000 -v 2>&1 | head -30

    if [ -f "$TESTDIR/pal_output.rgb" ]; then
        echo "✓ Video output created successfully"
        ls -lh "$TESTDIR/pal_output.rgb"
        echo ""
        echo "To view the output, run:"
        echo "  ffplay -f rawvideo -pixel_format rgb32 -video_size 720x576 -framerate 25 $TESTDIR/pal_output.rgb"
        echo ""
    else
        echo "✗ Video output not created"
    fi
else
    echo "✗ Failed to generate test signal"
fi

# Test 2: NTSC with FM demodulation
echo "=========================================="
echo "Test 2: NTSC Signal with FM Demodulation"
echo "=========================================="
echo ""

echo "Generating NTSC test signal..."
./src/hacktv -o "$TESTDIR/ntsc_fm.iq" -m ntsc -s 16000000 -t int16 --output-type complex test 2>&1 | head -20

if [ -f "$TESTDIR/ntsc_fm.iq" ]; then
    echo "✓ Test signal generated successfully"
    ls -lh "$TESTDIR/ntsc_fm.iq"
    echo ""

    echo "Receiving NTSC signal..."
    ./src/hackrx -i "$TESTDIR/ntsc_fm.iq" -o "$TESTDIR/ntsc_output.rgb" -a "$TESTDIR/ntsc_audio.pcm" -m ntsc -d fm -s 16000000 -v 2>&1 | head -30

    if [ -f "$TESTDIR/ntsc_output.rgb" ]; then
        echo "✓ Video output created successfully"
        ls -lh "$TESTDIR/ntsc_output.rgb"
        echo ""
        echo "To view the output, run:"
        echo "  ffplay -f rawvideo -pixel_format rgb32 -video_size 720x480 -framerate 29.97 $TESTDIR/ntsc_output.rgb"
        echo ""
    else
        echo "✗ Video output not created"
    fi

    if [ -f "$TESTDIR/ntsc_audio.pcm" ]; then
        echo "✓ Audio output created successfully"
        ls -lh "$TESTDIR/ntsc_audio.pcm"
        echo ""
        echo "To listen to the audio, run:"
        echo "  ffplay -f s16le -ar 48000 -ac 1 $TESTDIR/ntsc_audio.pcm"
        echo ""
    fi
else
    echo "✗ Failed to generate test signal"
fi

# Test 3: Check receiver help
echo "=========================================="
echo "Test 3: Receiver Help Output"
echo "=========================================="
echo ""

./src/hackrx --help

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo ""
echo "Test files created in: $TESTDIR"
echo ""
echo "To clean up test files, run:"
echo "  rm -rf $TESTDIR"
echo ""
echo "Tests completed!"
echo ""
echo "Note: The receiver is a prototype implementation."
echo "      Color decoding and sync detection are simplified."
echo "      You may see grayscale or noisy output, which is expected."
echo ""
