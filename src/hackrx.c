/* hackrx.c - Analog TV Receiver Main Program */
/*=======================================================================*/
/* Copyright 2025 - Analog TV Receiver for SDR Hardware                  */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <getopt.h>
#include <signal.h>
#include <unistd.h>
#include "receiver.h"
#include "common.h"

#if defined(HAVE_RX_SOAPYSDR) || defined(HAVE_LIBIIO)
#include "rf_sdr.h"
#define HAVE_SDR
#endif

#ifndef VERSION
#define VERSION "1.0-receiver"
#endif

static volatile sig_atomic_t _abort = 0;

static void _sigint_callback_handler(int signum)
{
	_abort = 1;
}

static void print_version(void)
{
	printf("hackrx (HackTV Receiver) %s\n", VERSION);
	printf("Analog TV receiver for SDR hardware\n");
}

static void print_usage(void)
{
	printf(
		"\n"
		"Usage: hackrx [options] <input>\n"
		"\n"
		"Input options:\n"
		"  -i, --input <file>             Input IQ file (int16 complex samples)\n"
		"      --sdr                      Use SDR hardware input\n"
		"      --device <id>              SDR device identifier\n"
		"      --gain <value>             RX gain in dB (0-70). Default: auto\n"
		"\n"
		"Output options:\n"
		"  -o, --output <file>            Output video file\n"
		"  -a, --audio-output <file>      Output audio file (raw PCM)\n"
		"      --video-format <fmt>       Video format: rgb, yuv420, yuv422, pipe. Default: rgb\n"
		"      --teletext-output <file>   Save captured teletext pages to file\n"
		"      --nicam-output <file>      Save NICAM digital audio to file (PCM)\n"
		"\n"
		"Reception settings:\n"
		"  -m, --mode <name>              TV mode (pal, ntsc, secam). Default: pal\n"
		"  -s, --samplerate <value>       Sample rate in Hz. Default: 16000000\n"
		"  -d, --demod <type>             Demodulator type (fm, am, vsb). Default: fm\n"
		"  -f, --frequency <value>        RF frequency in Hz\n"
		"      --if <value>               IF frequency for VSB demod. Default: 6000000\n"
		"      --audio-carrier <value>    Audio carrier frequency in Hz\n"
		"      --audio-rate <value>       Audio output sample rate. Default: 48000\n"
		"      --no-audio                 Disable audio decoding\n"
		"      --nicam                    Enable NICAM digital audio decoding\n"
		"      --teletext                 Enable teletext/VBI decoding\n"
		"      --wss                      Enable WSS (Widescreen Signaling) decoding\n"
		"\n"
		"Other options:\n"
		"  -v, --verbose                  Enable verbose output\n"
		"  -h, --help                     Display this help and exit\n"
		"      --version                  Display version and exit\n"
		"\n"
		"Supported TV modes:\n"
		"  PAL variants:\n"
		"    pal, pal-bg  - PAL-B/G (Western Europe, 625 lines, 5.5 MHz audio)\n"
		"    pal-i        - PAL-I (UK, Ireland, 625 lines, 6.0 MHz audio)\n"
		"    pal-dk       - PAL-D/K (Eastern Europe, China, 625 lines, 6.5 MHz audio)\n"
		"    pal-m        - PAL-M (Brazil, 525 lines, 4.5 MHz audio)\n"
		"    pal-n        - PAL-N (Argentina, 625 lines, 4.5 MHz audio)\n"
		"    pal-mono     - PAL monochrome (625 lines)\n"
		"\n"
		"  NTSC variants:\n"
		"    ntsc, ntsc-m - NTSC-M (North America, 525 lines, 4.5 MHz audio)\n"
		"    ntsc-j       - NTSC-J (Japan, 525 lines, 4.5 MHz audio)\n"
		"    ntsc-mono    - NTSC monochrome (525 lines)\n"
		"\n"
		"  SECAM variants:\n"
		"    secam, secam-dk - SECAM-D/K (Eastern Europe, 625 lines, 6.5 MHz audio)\n"
		"    secam-bg        - SECAM-B/G (Middle East, 625 lines, 5.5 MHz audio)\n"
		"    secam-l         - SECAM-L (France, 625 lines, 6.5 MHz audio)\n"
		"\n"
		"Demodulator types:\n"
		"  fm        - FM demodulation (satellite signals)\n"
		"  am        - AM demodulation (older systems)\n"
		"  vsb       - Vestigial sideband (terrestrial PAL/NTSC/SECAM)\n"
		"\n"
		"Examples:\n"
		"  # Receive PAL signal from IQ file with YUV output\n"
		"  hackrx -i test.iq -o video.yuv --video-format yuv420 -m pal -d fm -s 16000000\n"
		"\n"
		"  # Receive NTSC with audio from SDR hardware\n"
		"  hackrx --sdr -f 474000000 -o video.yuv --video-format yuv420 -a audio.pcm -m ntsc -d vsb --gain 40\n"
		"\n"
		"  # Receive PAL with NICAM and Teletext\n"
		"  hackrx --sdr -f 474000000 -o video.yuv --video-format yuv420 -m pal -d vsb \\\n"
		"         --nicam --nicam-output nicam.pcm --teletext --teletext-output pages.txt --gain 45\n"
		"\n"
		"  # Pipe to ffmpeg for direct encoding\n"
		"  hackrx -i test.iq -m pal -d fm --video-format pipe | \\\n"
		"         ffmpeg -f rawvideo -pix_fmt rgb24 -s 720x576 -r 25 -i - -c:v libx264 output.mp4\n"
		"\n"
	);
}

typedef struct {
	const char *name;
	int lines;
	int interlaced;
	r64_t frame_rate;
	rx_colour_type_t colour;
	double audio_carrier;
} mode_info_t;

static const mode_info_t _modes[] = {
	/* PAL variants */
	{ "pal",       625, 1, { 25, 1 },    RX_COLOUR_PAL,   5500000.0 },  /* PAL-B/G: Western Europe */
	{ "pal-bg",    625, 1, { 25, 1 },    RX_COLOUR_PAL,   5500000.0 },  /* PAL-B/G: Western Europe */
	{ "pal-i",     625, 1, { 25, 1 },    RX_COLOUR_PAL,   6000000.0 },  /* PAL-I: UK, Ireland */
	{ "pal-dk",    625, 1, { 25, 1 },    RX_COLOUR_PAL,   6500000.0 },  /* PAL-D/K: Eastern Europe, China */
	{ "pal-m",     525, 1, { 30000, 1001 }, RX_COLOUR_PAL, 4500000.0 },  /* PAL-M: Brazil (525 lines) */
	{ "pal-n",     625, 1, { 25, 1 },    RX_COLOUR_PAL,   4500000.0 },  /* PAL-N: Argentina, Paraguay */
	{ "pal-mono",  625, 1, { 25, 1 },    RX_COLOUR_NONE,  5500000.0 },  /* PAL monochrome */

	/* NTSC variants */
	{ "ntsc",      525, 1, { 30000, 1001 }, RX_COLOUR_NTSC, 4500000.0 },  /* NTSC-M: North America */
	{ "ntsc-m",    525, 1, { 30000, 1001 }, RX_COLOUR_NTSC, 4500000.0 },  /* NTSC-M: North America */
	{ "ntsc-j",    525, 1, { 30000, 1001 }, RX_COLOUR_NTSC, 4500000.0 },  /* NTSC-J: Japan */
	{ "ntsc-mono", 525, 1, { 30000, 1001 }, RX_COLOUR_NONE, 4500000.0 },  /* NTSC monochrome */

	/* SECAM variants */
	{ "secam",     625, 1, { 25, 1 },    RX_COLOUR_SECAM, 6500000.0 },  /* SECAM-D/K: Eastern Europe */
	{ "secam-dk",  625, 1, { 25, 1 },    RX_COLOUR_SECAM, 6500000.0 },  /* SECAM-D/K: Eastern Europe */
	{ "secam-bg",  625, 1, { 25, 1 },    RX_COLOUR_SECAM, 5500000.0 },  /* SECAM-B/G: Middle East */
	{ "secam-l",   625, 1, { 25, 1 },    RX_COLOUR_SECAM, 6500000.0 },  /* SECAM-L: France (AM audio - TODO) */

	{ NULL, 0, 0, { 0, 0 }, 0, 0.0 }
};

static const mode_info_t* find_mode(const char *name)
{
	int i;

	for(i = 0; _modes[i].name != NULL; i++)
	{
		if(strcasecmp(name, _modes[i].name) == 0)
		{
			return &_modes[i];
		}
	}

	return NULL;
}

int main(int argc, char *argv[])
{
	int opt;
	int option_index;
	rx_t rx;
	rx_config_t conf;
	const char *input_file = NULL;
	const char *output_file = NULL;
	const char *audio_file = NULL;
	const char *mode_name = "pal";
	const char *demod_name = "fm";
	const mode_info_t *mode;
	FILE *input_fp = NULL;
	FILE *audio_fp = NULL;
	int16_t *iq_buffer;
	int iq_buffer_size = 8192;
	int samples_read;
	int verbose = 0;
	uint64_t total_samples = 0;
	int frames_written = 0;

#ifdef HAVE_SDR
	/* SDR-specific variables */
	int use_sdr = 0;
	const char *sdr_device = NULL;
	double sdr_gain = -1.0;  /* -1 = auto */
	sdr_t *sdr = NULL;
	sdr_config_t sdr_conf;
#endif

	/* Default configuration */
	memset(&conf, 0, sizeof(rx_config_t));
	conf.sample_rate = 16000000;
	conf.demod_type = RX_DEMOD_FM;
	conf.enable_audio = 1;
	conf.audio_output_rate = 48000;
	conf.rf_frequency = 0;
	conf.if_frequency = 6000000.0;

	static const struct option long_options[] = {
		{ "input",         required_argument, 0, 'i' },
		{ "output",        required_argument, 0, 'o' },
		{ "audio-output",  required_argument, 0, 'a' },
		{ "mode",          required_argument, 0, 'm' },
		{ "samplerate",    required_argument, 0, 's' },
		{ "demod",         required_argument, 0, 'd' },
		{ "frequency",     required_argument, 0, 'f' },
		{ "if",            required_argument, 0, 'I' },
		{ "audio-carrier", required_argument, 0, 'A' },
		{ "audio-rate",    required_argument, 0, 'R' },
		{ "no-audio",      no_argument,       0, 'N' },
		{ "sdr",           no_argument,       0, 'S' },
		{ "device",        required_argument, 0, 'D' },
		{ "gain",          required_argument, 0, 'g' },
		{ "nicam",         no_argument,       0, 'M' },
		{ "nicam-output",  required_argument, 0, 'O' },
		{ "teletext",      no_argument,       0, 'T' },
		{ "teletext-output", required_argument, 0, 'X' },
		{ "wss",           no_argument,       0, 'W' },
		{ "video-format",  required_argument, 0, 'F' },
		{ "verbose",       no_argument,       0, 'v' },
		{ "help",          no_argument,       0, 'h' },
		{ "version",       no_argument,       0, 'V' },
		{ 0, 0, 0, 0 }
	};

	/* Parse command line options */
	while((opt = getopt_long(argc, argv, "i:o:a:m:s:d:f:g:vhV", long_options, &option_index)) != -1)
	{
		switch(opt)
		{
			case 'i':
				input_file = optarg;
				break;
			case 'o':
				output_file = optarg;
				break;
			case 'a':
				audio_file = optarg;
				break;
			case 'm':
				mode_name = optarg;
				break;
			case 's':
				conf.sample_rate = atoi(optarg);
				break;
			case 'd':
				demod_name = optarg;
				break;
			case 'f':
				conf.rf_frequency = atof(optarg);
				break;
			case 'I':
				conf.if_frequency = atof(optarg);
				break;
			case 'A':
				conf.audio_carrier = atof(optarg);
				break;
			case 'R':
				conf.audio_output_rate = atoi(optarg);
				break;
			case 'N':
				conf.enable_audio = 0;
				break;
#ifdef HAVE_SDR
			case 'S':
				use_sdr = 1;
				break;
			case 'D':
				sdr_device = optarg;
				break;
			case 'g':
				sdr_gain = atof(optarg);
				break;
#endif
			case 'M':
				conf.enable_nicam = 1;
				break;
			case 'O':
				/* NICAM audio output file - handled later */
				break;
			case 'T':
				conf.enable_teletext = 1;
				break;
			case 'X':
				conf.teletext_output = optarg;
				conf.enable_teletext = 1;
				break;
			case 'W':
				conf.enable_wss = 1;
				break;
			case 'F':
				if(strcasecmp(optarg, "rgb") == 0)
					conf.video_output_format = VIDEO_OUT_RAW_RGB;
				else if(strcasecmp(optarg, "yuv420") == 0)
					conf.video_output_format = VIDEO_OUT_RAW_YUV420;
				else if(strcasecmp(optarg, "yuv422") == 0)
					conf.video_output_format = VIDEO_OUT_RAW_YUV422;
				else if(strcasecmp(optarg, "pipe") == 0)
					conf.video_output_format = VIDEO_OUT_PIPE;
				else
				{
					fprintf(stderr, "Unknown video format: %s\n", optarg);
					return 1;
				}
				break;
			case 'v':
				verbose = 1;
				break;
			case 'h':
				print_usage();
				return 0;
			case 'V':
				print_version();
				return 0;
			default:
				print_usage();
				return 1;
		}
	}

	/* Validate input */
#ifdef HAVE_SDR
	if(!input_file && !use_sdr)
	{
		fprintf(stderr, "Error: Either input file (-i) or SDR mode (--sdr) is required\n");
		print_usage();
		return 1;
	}

	if(use_sdr && !conf.rf_frequency)
	{
		fprintf(stderr, "Error: RF frequency (-f) is required for SDR mode\n");
		print_usage();
		return 1;
	}
#else
	if(!input_file)
	{
		fprintf(stderr, "Error: Input file is required\n");
		print_usage();
		return 1;
	}
#endif

	/* Set video output file in config */
	if(output_file)
	{
		conf.video_output_file = output_file;

		/* Default to raw RGB if format not specified */
		if(conf.video_output_format == VIDEO_OUT_NONE)
		{
			conf.video_output_format = VIDEO_OUT_RAW_RGB;
		}
	}

	/* Find TV mode */
	mode = find_mode(mode_name);
	if(!mode)
	{
		fprintf(stderr, "Error: Unknown mode '%s'\n", mode_name);
		return 1;
	}

	conf.lines = mode->lines;
	conf.interlaced = mode->interlaced;
	conf.frame_rate = mode->frame_rate;
	conf.colour_type = mode->colour;

	/* Use mode's default audio carrier if not specified */
	if(conf.audio_carrier == 0.0)
	{
		conf.audio_carrier = mode->audio_carrier;
	}

	/* Parse demodulator type */
	if(strcasecmp(demod_name, "fm") == 0)
	{
		conf.demod_type = RX_DEMOD_FM;
	}
	else if(strcasecmp(demod_name, "am") == 0)
	{
		conf.demod_type = RX_DEMOD_AM;
	}
	else if(strcasecmp(demod_name, "vsb") == 0)
	{
		conf.demod_type = RX_DEMOD_VSB;
	}
	else
	{
		fprintf(stderr, "Error: Unknown demodulator type '%s'\n", demod_name);
		return 1;
	}

	print_version();
	printf("\n");

	/* Open input file */
	input_fp = fopen(input_file, "rb");
	if(!input_fp)
	{
		fprintf(stderr, "Error: Cannot open input file '%s'\n", input_file);
		return 1;
	}

	/* Audio output file handling */
	if(audio_file && conf.enable_audio)
	{
		audio_fp = fopen(audio_file, "wb");
		if(!audio_fp)
		{
			fprintf(stderr, "Warning: Cannot open audio file '%s'\n", audio_file);
		}
	}

	/* Initialize receiver */
	if(rx_init(&rx, &conf) != 0)
	{
		fprintf(stderr, "Error: Failed to initialize receiver\n");
		fclose(input_fp);
		if(audio_fp) fclose(audio_fp);
		return 1;
	}

	printf("\n");
	printf("Starting reception...\n");
	printf("Press Ctrl+C to stop\n\n");

	/* Set up signal handler */
	signal(SIGINT, _sigint_callback_handler);
	signal(SIGTERM, _sigint_callback_handler);

	/* Allocate IQ buffer */
	iq_buffer = malloc(iq_buffer_size * sizeof(int16_t));
	if(!iq_buffer)
	{
		fprintf(stderr, "Error: Failed to allocate IQ buffer\n");
		rx_free(&rx);
		fclose(input_fp);
		if(audio_fp) fclose(audio_fp);
		return 1;
	}

	/* Main reception loop */
	int last_frame_count = 0;
	while(!_abort)
	{
		/* Read IQ samples from file */
		/* Format: int16 interleaved I/Q */
		samples_read = fread(iq_buffer, sizeof(int16_t), iq_buffer_size, input_fp);

		if(samples_read <= 0)
		{
			/* End of file */
			if(verbose)
			{
				printf("\nEnd of input file reached\n");
			}
			break;
		}

		/* Process samples */
		rx_process_samples(&rx, iq_buffer, samples_read);
		total_samples += samples_read / 2;  /* Divide by 2 for I/Q pairs */

		/* Check if we have a new frame to write */
		if(rx.frames_decoded > last_frame_count)
		{
			/* Frame writing is now handled automatically by video_output in receiver.c */
			if(rx.frames_decoded > last_frame_count)
			{
				frames_written++;
				last_frame_count = rx.frames_decoded;

				if(verbose || (frames_written % 25 == 0))
				{
					printf("\rFrames: %d | Samples: %lu | Sync: %s    ",
						frames_written,
						(unsigned long)total_samples,
						rx.sync.in_sync ? "LOCKED" : "SEARCHING");
					fflush(stdout);
				}
			}
		}

		/* Write audio if available */
		if(audio_fp && conf.enable_audio)
		{
			int16_t *audio;
			int audio_count;

			if(rx_get_audio(&rx, &audio, &audio_count) > 0)
			{
				fwrite(audio, sizeof(int16_t), audio_count, audio_fp);
			}
		}
	}

	printf("\n\nReception complete.\n");
	printf("Total frames decoded: %d\n", frames_written);
	printf("Total samples processed: %lu\n", (unsigned long)total_samples);
	printf("Sync errors: %d\n", rx.sync_errors);

	/* Cleanup */
	free(iq_buffer);
	rx_free(&rx);  /* This also closes video_output */
	fclose(input_fp);
	if(audio_fp) fclose(audio_fp);

	printf("\nReception complete!\n");
	printf("  Frames decoded: %d\n", frames_written);
	printf("  Samples processed: %lu\n", (unsigned long)total_samples);

	if(output_file)
	{
		const char *pixel_format = (conf.video_output_format == VIDEO_OUT_RAW_YUV420) ? "yuv420p" :
		                            (conf.video_output_format == VIDEO_OUT_RAW_YUV422) ? "yuv422p" : "rgb24";
		printf("\nTo view the video:\n");
		printf("  ffplay -f rawvideo -pixel_format %s -video_size %dx%d -framerate %.2f %s\n",
			pixel_format,
			rx.frame_width, rx.frame_height,
			(double)conf.frame_rate.num / conf.frame_rate.den,
			output_file);
	}

	if(conf.teletext_output)
	{
		printf("\nTeletext pages saved to: %s\n", conf.teletext_output);
	}

	return 0;
}
