#!/bin/bash
################################################################################
# HackRF TX/RX Loopback Test Script                                            #
# Tests complete analog TV transmission and reception using HackRF hardware    #
################################################################################

set -e  # Exit on error

# Configuration
FREQ=474000000          # UHF Channel 23 (474 MHz)
SAMPLE_RATE=16000000    # 16 MHz sample rate
MODE="pal"              # TV standard (pal, ntsc, secam)
DURATION=10             # Test duration in seconds
OUTPUT_DIR="./hackrf_test_output"
TEST_IMAGE="./test_pattern.png"

# Colors for output
RED='\033[0.31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_dependencies() {
    log_info "Checking dependencies..."

    # Check for hackrf_transfer
    if ! command -v hackrf_transfer &> /dev/null; then
        log_error "hackrf_transfer not found. Please install hackrf tools."
        exit 1
    fi

    # Check for hacktv
    if [ ! -f "./src/hacktv" ]; then
        log_warn "hacktv not found in ./src/, trying to build..."
        cd src && make hacktv && cd ..
    fi

    # Check for hackrx
    if [ ! -f "./src/hackrx" ]; then
        log_warn "hackrx not found in ./src/, trying to build..."
        cd src && make hackrx && cd ..
    fi

    # Check for HackRF hardware
    if ! hackrf_info 2>&1 | grep -q "Serial number"; then
        log_error "No HackRF device found. Please connect HackRF hardware."
        exit 1
    fi

    log_info "All dependencies OK"
}

create_test_pattern() {
    log_info "Creating test pattern..."

    # Create test image if it doesn't exist
    if [ ! -f "$TEST_IMAGE" ]; then
        if command -v convert &> /dev/null; then
            # Create color bars using ImageMagick
            convert -size 720x576 pattern:horizontal -fill red -draw "rectangle 0,0 102,576" \
                    -fill green -draw "rectangle 103,0 205,576" \
                    -fill blue -draw "rectangle 206,0 308,576" \
                    -fill yellow -draw "rectangle 309,0 411,576" \
                    -fill cyan -draw "rectangle 412,0 514,576" \
                    -fill magenta -draw "rectangle 515,0 617,576" \
                    -fill white -draw "rectangle 618,0 720,576" \
                    "$TEST_IMAGE"
            log_info "Created test pattern: $TEST_IMAGE"
        else
            log_warn "ImageMagick not available, using hacktv test pattern"
            TEST_IMAGE="test"  # hacktv built-in test pattern
        fi
    fi
}

transmit_signal() {
    log_info "Starting HackRF transmission on $FREQ Hz..."
    log_info "TV Mode: $MODE, Sample Rate: $SAMPLE_RATE Hz"
    log_info "Duration: $DURATION seconds"

    # Generate and transmit signal
    timeout $DURATION ./src/hacktv \
        -o hackrf \
        -m "$MODE" \
        -s "$SAMPLE_RATE" \
        -f "$FREQ" \
        --teletext teletext_pages \
        "$TEST_IMAGE" &

    TX_PID=$!
    log_info "Transmission started (PID: $TX_PID)"

    # Wait a moment for TX to start
    sleep 2
}

receive_signal() {
    log_info "Starting HackRF reception..."

    # Ensure output directory exists
    mkdir -p "$OUTPUT_DIR"

    # Start reception
    timeout $((DURATION - 1)) ./src/hackrx \
        --sdr \
        -f "$FREQ" \
        -m "$MODE" \
        -s "$SAMPLE_RATE" \
        -d vsb \
        -o "$OUTPUT_DIR/received_video.yuv" \
        --teletext-output "$OUTPUT_DIR/teletext.txt" \
        --video-format yuv420 \
        --gain 40 \
        --verbose &

    RX_PID=$!
    log_info "Reception started (PID: $RX_PID)"
}

wait_for_completion() {
    log_info "Waiting for test to complete..."

    # Wait for both processes
    wait $TX_PID 2>/dev/null || true
    wait $RX_PID 2>/dev/null || true

    log_info "Test completed"
}

verify_output() {
    log_info "Verifying output files..."

    local success=0

    # Check video output
    if [ -f "$OUTPUT_DIR/received_video.yuv" ]; then
        local size=$(stat -c%s "$OUTPUT_DIR/received_video.yuv")
        if [ $size -gt 1000000 ]; then  # > 1MB
            log_info "✓ Video received: $(($size / 1024 / 1024)) MB"
            success=$((success + 1))
        else
            log_warn "✗ Video file too small: $size bytes"
        fi
    else
        log_warn "✗ No video output file"
    fi

    # Check teletext output
    if [ -f "$OUTPUT_DIR/teletext.txt" ]; then
        local lines=$(wc -l < "$OUTPUT_DIR/teletext.txt")
        if [ $lines -gt 10 ]; then
            log_info "✓ Teletext received: $lines lines"
            success=$((success + 1))
        fi
    fi

    if [ $success -eq 2 ]; then
        log_info "========================================="
        log_info "TEST PASSED: All outputs verified"
        log_info "========================================="
        return 0
    else
        log_warn "========================================="
        log_warn "TEST INCOMPLETE: Some outputs missing"
        log_warn "========================================="
        return 1
    fi
}

convert_to_viewable() {
    log_info "Converting output to viewable format..."

    if command -v ffmpeg &> /dev/null && [ -f "$OUTPUT_DIR/received_video.yuv" ]; then
        ffmpeg -f rawvideo -pixel_format yuv420p -video_size 720x576 -framerate 25 \
               -i "$OUTPUT_DIR/received_video.yuv" \
               -c:v libx264 -preset fast -crf 22 \
               "$OUTPUT_DIR/received_video.mp4" \
               -y 2>&1 | grep -E "(frame=|time=|size=)" || true

        if [ -f "$OUTPUT_DIR/received_video.mp4" ]; then
            log_info "✓ Created viewable video: $OUTPUT_DIR/received_video.mp4"
        fi
    else
        log_warn "ffmpeg not available, skipping video conversion"
        log_info "To view raw YUV: ffplay -f rawvideo -pixel_format yuv420p -video_size 720x576 -framerate 25 $OUTPUT_DIR/received_video.yuv"
    fi
}

cleanup() {
    log_info "Cleaning up..."
    kill $TX_PID 2>/dev/null || true
    kill $RX_PID 2>/dev/null || true
}

# Main execution
main() {
    echo "========================================"
    echo "HackRF Analog TV Loopback Test"
    echo "========================================"
    echo ""

    # Set up cleanup trap
    trap cleanup EXIT INT TERM

    # Run test sequence
    check_dependencies
    create_test_pattern
    transmit_signal
    receive_signal
    wait_for_completion
    verify_output
    convert_to_viewable

    echo ""
    log_info "Test output saved to: $OUTPUT_DIR"
    log_info "To view received video:"
    log_info "  ffplay -f rawvideo -pixel_format yuv420p -video_size 720x576 -framerate 25 $OUTPUT_DIR/received_video.yuv"
    log_info "Or play the MP4:"
    log_info "  ffplay $OUTPUT_DIR/received_video.mp4"
    echo ""
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--frequency)
            FREQ="$2"
            shift 2
            ;;
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -d|--duration)
            DURATION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -f, --frequency <hz>   RF frequency (default: 474000000)"
            echo "  -m, --mode <mode>      TV mode: pal, ntsc, secam (default: pal)"
            echo "  -d, --duration <sec>   Test duration in seconds (default: 10)"
            echo "  -h, --help             Show this help"
            echo ""
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run main
main
