/* hackrx - Analog TV Receiver */
/*=======================================================================*/
/* Copyright 2025 - Video Output Module                                  */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "video_output.h"

/* Try to include FFmpeg headers - will fail gracefully if not available */
#ifdef HAVE_FFMPEG
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
#include <libavutil/opt.h>
#include <libavutil/imgutils.h>
#endif

/* RGB32 to YUV conversion (ITU-R BT.601) */
static void _rgb_to_yuv(uint8_t r, uint8_t g, uint8_t b, uint8_t *y, uint8_t *u, uint8_t *v)
{
	/* BT.601 conversion */
	*y = (uint8_t)(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16);
	*u = (uint8_t)(((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128);
	*v = (uint8_t)(((112 * r - 94 * g - 18 * b + 128) >> 8) + 128);
}

/* Convert RGB32 frame to YUV420 planar */
static void _convert_rgb_to_yuv420(const uint32_t *rgb, uint8_t *yuv, int width, int height)
{
	int x, y;
	uint8_t *y_plane = yuv;
	uint8_t *u_plane = yuv + (width * height);
	uint8_t *v_plane = yuv + (width * height) + (width * height / 4);

	for(y = 0; y < height; y++)
	{
		for(x = 0; x < width; x++)
		{
			uint32_t pixel = rgb[y * width + x];
			uint8_t r = (pixel >> 16) & 0xFF;
			uint8_t g = (pixel >> 8) & 0xFF;
			uint8_t b = pixel & 0xFF;

			uint8_t y_val, u_val, v_val;
			_rgb_to_yuv(r, g, b, &y_val, &u_val, &v_val);

			y_plane[y * width + x] = y_val;

			/* Subsample U and V (4:2:0) */
			if((y % 2 == 0) && (x % 2 == 0))
			{
				u_plane[(y/2) * (width/2) + (x/2)] = u_val;
				v_plane[(y/2) * (width/2) + (x/2)] = v_val;
			}
		}
	}
}

/* Get format name */
const char* video_output_format_name(video_output_format_t format)
{
	switch(format)
	{
		case VIDEO_OUT_RAW_RGB: return "Raw RGB24";
		case VIDEO_OUT_RAW_YUV420: return "Raw YUV 4:2:0";
		case VIDEO_OUT_RAW_YUV422: return "Raw YUV 4:2:2";
		case VIDEO_OUT_H264: return "H.264/AVC";
		case VIDEO_OUT_FFV1: return "FFV1 Lossless";
		case VIDEO_OUT_PIPE: return "Pipe to stdout";
		default: return "None";
	}
}

/* Initialize output */
int video_output_init(video_output_t *vo,
                      video_output_format_t format,
                      const char *filename,
                      int width, int height,
                      int fps_num, int fps_den,
                      int interlaced)
{
	memset(vo, 0, sizeof(video_output_t));

	vo->format = format;
	vo->width = width;
	vo->height = height;
	vo->framerate_num = fps_num;
	vo->framerate_den = fps_den;
	vo->interlaced = interlaced;

	/* Allocate frame buffers */
	vo->rgb_buffer = calloc(width * height, sizeof(uint32_t));
	if(!vo->rgb_buffer)
	{
		fprintf(stderr, "Failed to allocate RGB buffer\n");
		return -1;
	}

	/* For YUV formats, allocate YUV buffer */
	if(format == VIDEO_OUT_RAW_YUV420 || format == VIDEO_OUT_RAW_YUV422 ||
	   format == VIDEO_OUT_H264 || format == VIDEO_OUT_FFV1)
	{
		/* YUV420 needs 1.5x size, YUV422 needs 2x size */
		int yuv_size = (format == VIDEO_OUT_RAW_YUV420 || format == VIDEO_OUT_H264 || format == VIDEO_OUT_FFV1)
		               ? (width * height * 3 / 2)
		               : (width * height * 2);

		vo->yuv_buffer = calloc(yuv_size, sizeof(uint8_t));
		if(!vo->yuv_buffer)
		{
			free(vo->rgb_buffer);
			fprintf(stderr, "Failed to allocate YUV buffer\n");
			return -1;
		}
	}

	/* Open output file */
	if(format == VIDEO_OUT_PIPE)
	{
		vo->file = stdout;
		vo->filename = strdup("stdout");
	}
	else if(format != VIDEO_OUT_NONE)
	{
		vo->filename = strdup(filename ? filename : "output.yuv");

		/* For codec formats, we'll need different extension */
		if(format == VIDEO_OUT_H264 || format == VIDEO_OUT_FFV1)
		{
#ifdef HAVE_FFMPEG
			/* FFmpeg codec initialization would go here */
			fprintf(stderr, "FFmpeg codec support enabled\n");
#else
			fprintf(stderr, "Warning: FFmpeg not available, falling back to raw YUV output\n");
			vo->format = VIDEO_OUT_RAW_YUV420;

			/* Change filename extension */
			char *new_filename = malloc(strlen(vo->filename) + 10);
			sprintf(new_filename, "%s.yuv", vo->filename);
			free(vo->filename);
			vo->filename = new_filename;
#endif
		}

		vo->file = fopen(vo->filename, "wb");
		if(!vo->file)
		{
			fprintf(stderr, "Failed to open output file: %s\n", vo->filename);
			free(vo->rgb_buffer);
			free(vo->yuv_buffer);
			free(vo->filename);
			return -1;
		}
	}

	fprintf(stderr, "Video output initialized: %dx%d %s (%d/%d fps)\n",
	        width, height, video_output_format_name(format), fps_num, fps_den);

	return 0;
}

/* Write frame */
int video_output_write_frame(video_output_t *vo, const uint32_t *rgb_data)
{
	if(!vo || !vo->file)
	{
		return -1;
	}

	switch(vo->format)
	{
		case VIDEO_OUT_RAW_RGB:
		case VIDEO_OUT_PIPE:
		{
			/* Write RGB24 data (strip alpha) */
			int i;
			uint8_t rgb24[3];

			for(i = 0; i < vo->width * vo->height; i++)
			{
				uint32_t pixel = rgb_data[i];
				rgb24[0] = (pixel >> 16) & 0xFF;  /* R */
				rgb24[1] = (pixel >> 8) & 0xFF;   /* G */
				rgb24[2] = pixel & 0xFF;          /* B */

				if(fwrite(rgb24, 1, 3, vo->file) != 3)
				{
					fprintf(stderr, "Failed to write RGB frame\n");
					return -1;
				}
			}

			vo->bytes_written += vo->width * vo->height * 3;
			break;
		}

		case VIDEO_OUT_RAW_YUV420:
		{
			/* Convert RGB to YUV420 and write */
			_convert_rgb_to_yuv420(rgb_data, vo->yuv_buffer, vo->width, vo->height);

			size_t yuv_size = vo->width * vo->height * 3 / 2;
			if(fwrite(vo->yuv_buffer, 1, yuv_size, vo->file) != yuv_size)
			{
				fprintf(stderr, "Failed to write YUV frame\n");
				return -1;
			}

			vo->bytes_written += yuv_size;
			break;
		}

		case VIDEO_OUT_H264:
		case VIDEO_OUT_FFV1:
		{
#ifdef HAVE_FFMPEG
			/* FFmpeg encoding would go here */
			fprintf(stderr, "FFmpeg encoding not yet implemented\n");
			return -1;
#else
			/* Fall back to raw YUV */
			_convert_rgb_to_yuv420(rgb_data, vo->yuv_buffer, vo->width, vo->height);
			size_t yuv_size = vo->width * vo->height * 3 / 2;
			fwrite(vo->yuv_buffer, 1, yuv_size, vo->file);
			vo->bytes_written += yuv_size;
#endif
			break;
		}

		default:
			return -1;
	}

	vo->frames_written++;

	/* Flush every 10 frames */
	if(vo->frames_written % 10 == 0)
	{
		fflush(vo->file);
	}

	return 0;
}

/* Write audio */
int video_output_write_audio(video_output_t *vo, const int16_t *audio_samples, int num_samples)
{
	if(!vo->audio_enabled || !vo->audio_file)
	{
		return 0;
	}

	size_t samples_to_write = num_samples * vo->audio_channels;
	size_t written = fwrite(audio_samples, sizeof(int16_t), samples_to_write, vo->audio_file);

	if(written != samples_to_write)
	{
		fprintf(stderr, "Failed to write audio samples\n");
		return -1;
	}

	return 0;
}

/* Close output */
int video_output_close(video_output_t *vo)
{
	if(!vo)
	{
		return -1;
	}

	fprintf(stderr, "\nVideo output statistics:\n");
	fprintf(stderr, "  Frames written: %lu\n", (unsigned long)vo->frames_written);
	fprintf(stderr, "  Bytes written: %lu\n", (unsigned long)vo->bytes_written);
	fprintf(stderr, "  Duration: %.2f seconds\n",
	        (double)vo->frames_written * vo->framerate_den / vo->framerate_num);

	if(vo->file && vo->file != stdout)
	{
		fclose(vo->file);
		vo->file = NULL;
	}

	if(vo->audio_file)
	{
		fclose(vo->audio_file);
		vo->audio_file = NULL;
	}

	return 0;
}

/* Free resources */
void video_output_free(video_output_t *vo)
{
	if(!vo)
	{
		return;
	}

	if(vo->file && vo->file != stdout)
	{
		fclose(vo->file);
	}

	if(vo->audio_file)
	{
		fclose(vo->audio_file);
	}

	free(vo->rgb_buffer);
	free(vo->yuv_buffer);
	free(vo->filename);

	memset(vo, 0, sizeof(video_output_t));
}
