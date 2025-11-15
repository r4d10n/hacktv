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
		"  -i, --input <file>             Input IQ file (int16 complex samples)\n"
		"  -o, --output <file>            Output video file (raw RGB)\n"
		"  -a, --audio-output <file>      Output audio file (raw PCM)\n"
		"  -m, --mode <name>              TV mode (pal, ntsc, secam). Default: pal\n"
		"  -s, --samplerate <value>       Sample rate in Hz. Default: 16000000\n"
		"  -d, --demod <type>             Demodulator type (fm, am, vsb). Default: fm\n"
		"  -f, --frequency <value>        RF frequency in Hz (for future SDR input)\n"
		"      --if <value>               IF frequency for VSB demod. Default: 6000000\n"
		"      --audio-carrier <value>    Audio carrier frequency in Hz\n"
		"      --audio-rate <value>       Audio output sample rate. Default: 48000\n"
		"      --no-audio                 Disable audio decoding\n"
		"  -v, --verbose                  Enable verbose output\n"
		"  -h, --help                     Display this help and exit\n"
		"      --version                  Display version and exit\n"
		"\n"
		"Supported TV modes:\n"
		"  pal       - PAL System I (625 lines, 25fps)\n"
		"  ntsc      - NTSC System M (525 lines, 29.97fps)\n"
		"  secam     - SECAM (625 lines, 25fps)\n"
		"  pal-mono  - PAL monochrome\n"
		"  ntsc-mono - NTSC monochrome\n"
		"\n"
		"Demodulator types:\n"
		"  fm        - FM demodulation (satellite signals)\n"
		"  am        - AM demodulation (older systems)\n"
		"  vsb       - Vestigial sideband (terrestrial PAL/NTSC/SECAM)\n"
		"\n"
		"Examples:\n"
		"  # Receive PAL signal from IQ file with VSB demodulation\n"
		"  hackrx -i test.iq -o video.rgb -m pal -d vsb -s 16000000\n"
		"\n"
		"  # Receive NTSC with FM demodulation and audio\n"
		"  hackrx -i sat.iq -o video.rgb -a audio.pcm -m ntsc -d fm\n"
		"\n"
		"  # Receive SECAM from file\n"
		"  hackrx -i secam.iq -o video.rgb -m secam -d vsb\n"
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
	{ "pal",       625, 1, { 25, 1 },    RX_COLOUR_PAL,   5500000.0 },
	{ "pal-i",     625, 1, { 25, 1 },    RX_COLOUR_PAL,   6000000.0 },
	{ "pal-mono",  625, 1, { 25, 1 },    RX_COLOUR_NONE,  5500000.0 },
	{ "ntsc",      525, 1, { 30000, 1001 }, RX_COLOUR_NTSC, 4500000.0 },
	{ "ntsc-m",    525, 1, { 30000, 1001 }, RX_COLOUR_NTSC, 4500000.0 },
	{ "ntsc-mono", 525, 1, { 30000, 1001 }, RX_COLOUR_NONE, 4500000.0 },
	{ "secam",     625, 1, { 25, 1 },    RX_COLOUR_SECAM, 6500000.0 },
	{ "secam-l",   625, 1, { 25, 1 },    RX_COLOUR_SECAM, 6500000.0 },
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
	FILE *output_fp = NULL;
	FILE *audio_fp = NULL;
	int16_t *iq_buffer;
	int iq_buffer_size = 8192;
	int samples_read;
	int verbose = 0;
	uint64_t total_samples = 0;
	int frames_written = 0;

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
		{ "verbose",       no_argument,       0, 'v' },
		{ "help",          no_argument,       0, 'h' },
		{ "version",       no_argument,       0, 'V' },
		{ 0, 0, 0, 0 }
	};

	/* Parse command line options */
	while((opt = getopt_long(argc, argv, "i:o:a:m:s:d:f:vhV", long_options, &option_index)) != -1)
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
	if(!input_file)
	{
		fprintf(stderr, "Error: Input file is required\n");
		print_usage();
		return 1;
	}

	if(!output_file)
	{
		fprintf(stderr, "Error: Output file is required\n");
		print_usage();
		return 1;
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

	/* Open output files */
	output_fp = fopen(output_file, "wb");
	if(!output_fp)
	{
		fprintf(stderr, "Error: Cannot open output file '%s'\n", output_file);
		fclose(input_fp);
		return 1;
	}

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
		fclose(output_fp);
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
		fclose(output_fp);
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
			uint32_t *framebuffer;
			int width, height;

			if(rx_get_frame(&rx, &framebuffer, &width, &height))
			{
				/* Write framebuffer to output file (raw RGB) */
				size_t pixels = width * height;
				fwrite(framebuffer, sizeof(uint32_t), pixels, output_fp);
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
	rx_free(&rx);
	fclose(input_fp);
	fclose(output_fp);
	if(audio_fp) fclose(audio_fp);

	printf("\nOutput written to:\n");
	printf("  Video: %s (%dx%d raw RGB)\n", output_file, rx.frame_width, rx.frame_height);
	if(audio_fp)
	{
		printf("  Audio: %s (%d Hz mono PCM)\n", audio_file, conf.audio_output_rate);
	}

	printf("\nTo view the video, use:\n");
	printf("  ffplay -f rawvideo -pixel_format rgb32 -video_size %dx%d -framerate %.2f %s\n",
		rx.frame_width, rx.frame_height,
		(double)conf.frame_rate.num / conf.frame_rate.den,
		output_file);

	return 0;
}
