/* hackrx - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - Video Output Module                                  */
/*                                                                       */
/* Supports raw YUV, RGB, and codec-encoded output (H.264, FFV1)        */
/*=======================================================================*/

#ifndef _VIDEO_OUTPUT_H
#define _VIDEO_OUTPUT_H

#include <stdint.h>
#include <stdio.h>

/* Output formats */
typedef enum {
	VIDEO_OUT_NONE = 0,
	VIDEO_OUT_RAW_RGB,      /* Raw RGB24 frames */
	VIDEO_OUT_RAW_YUV420,   /* Raw YUV 4:2:0 planar (I420) */
	VIDEO_OUT_RAW_YUV422,   /* Raw YUV 4:2:2 planar (I422) */
	VIDEO_OUT_H264,         /* H.264/AVC encoded (requires FFmpeg) */
	VIDEO_OUT_FFV1,         /* FFV1 lossless (requires FFmpeg) */
	VIDEO_OUT_PIPE          /* Pipe raw RGB to stdout for external encoding */
} video_output_format_t;

/* Video output context */
typedef struct {
	video_output_format_t format;

	int width;
	int height;
	int framerate_num;
	int framerate_den;
	int interlaced;

	/* Output file */
	FILE *file;
	char *filename;

	/* Frame buffer */
	uint32_t *rgb_buffer;     /* RGB32 frame buffer */
	uint8_t *yuv_buffer;      /* YUV conversion buffer */

	/* Codec context (if using FFmpeg) */
	void *codec_ctx;          /* Actually AVCodecContext* */
	void *format_ctx;         /* Actually AVFormatContext* */
	void *frame;              /* Actually AVFrame* */
	void *sws_ctx;            /* Actually SwsContext* for RGB->YUV */

	/* Statistics */
	uint64_t frames_written;
	uint64_t bytes_written;

	/* Audio support */
	int audio_enabled;
	int audio_sample_rate;
	int audio_channels;
	FILE *audio_file;         /* Separate audio file (PCM) */

} video_output_t;

/* Initialize video output */
extern int video_output_init(video_output_t *vo,
                              video_output_format_t format,
                              const char *filename,
                              int width, int height,
                              int fps_num, int fps_den,
                              int interlaced);

/* Write RGB frame */
extern int video_output_write_frame(video_output_t *vo, const uint32_t *rgb_data);

/* Write audio samples (if enabled) */
extern int video_output_write_audio(video_output_t *vo, const int16_t *audio_samples, int num_samples);

/* Finalize and close output */
extern int video_output_close(video_output_t *vo);

/* Free resources */
extern void video_output_free(video_output_t *vo);

/* Get format name string */
extern const char* video_output_format_name(video_output_format_t format);

#endif
