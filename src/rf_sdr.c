/* rf_sdr.c - SDR Hardware Input Implementation */
/*=======================================================================*/
/* Copyright 2025 - SDR Input for HackTV Receiver                        */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "rf_sdr.h"

/* Platform detection */
#ifdef HAVE_SOAPYSDR
#include <SoapySDR/Device.h>
#include <SoapySDR/Formats.h>
#endif

#ifdef HAVE_LIBIIO
#include <iio.h>
#endif

/* =======================================================================*/
/* SoapySDR Implementation                                               */
/* =======================================================================*/

#ifdef HAVE_SOAPYSDR

typedef struct {
	SoapySDRDevice *device;
	SoapySDRStream *stream;
	size_t mtu;
} soapy_ctx_t;

static int soapy_init(sdr_t *sdr)
{
	soapy_ctx_t *ctx;
	SoapySDRKwargs args = {0};
	int r;

	ctx = calloc(1, sizeof(soapy_ctx_t));
	if(!ctx) return -1;

	/* Open device */
	if(sdr->config.device_id)
	{
		SoapySDRKwargs_set(&args, "driver", sdr->config.device_id);
	}

	ctx->device = SoapySDRDevice_make(&args);
	SoapySDRKwargs_clear(&args);

	if(!ctx->device)
	{
		fprintf(stderr, "SoapySDR: Failed to open device: %s\n",
			SoapySDRDevice_lastError());
		free(ctx);
		return -1;
	}

	/* Set sample rate */
	r = SoapySDRDevice_setSampleRate(ctx->device, SOAPY_SDR_RX, 0,
		sdr->config.sample_rate);
	if(r != 0)
	{
		fprintf(stderr, "SoapySDR: Failed to set sample rate\n");
		SoapySDRDevice_unmake(ctx->device);
		free(ctx);
		return -1;
	}

	/* Set frequency */
	r = SoapySDRDevice_setFrequency(ctx->device, SOAPY_SDR_RX, 0,
		sdr->config.frequency, NULL);
	if(r != 0)
	{
		fprintf(stderr, "SoapySDR: Failed to set frequency\n");
		SoapySDRDevice_unmake(ctx->device);
		free(ctx);
		return -1;
	}

	/* Set bandwidth if specified */
	if(sdr->config.bandwidth > 0)
	{
		SoapySDRDevice_setBandwidth(ctx->device, SOAPY_SDR_RX, 0,
			sdr->config.bandwidth);
	}

	/* Set gain */
	if(sdr->config.gain_mode == 0)  /* Manual */
	{
		SoapySDRDevice_setGainMode(ctx->device, SOAPY_SDR_RX, 0, false);
		SoapySDRDevice_setGain(ctx->device, SOAPY_SDR_RX, 0, sdr->config.gain);
	}
	else  /* Automatic */
	{
		SoapySDRDevice_setGainMode(ctx->device, SOAPY_SDR_RX, 0, true);
	}

	/* Setup stream */
	ctx->stream = SoapySDRDevice_setupStream(ctx->device, SOAPY_SDR_RX,
		SOAPY_SDR_CS16, NULL, 0, NULL);
	if(!ctx->stream)
	{
		fprintf(stderr, "SoapySDR: Failed to setup stream\n");
		SoapySDRDevice_unmake(ctx->device);
		free(ctx);
		return -1;
	}

	ctx->mtu = SoapySDRDevice_getStreamMTU(ctx->device, ctx->stream);

	sdr->device_handle = ctx;

	printf("SoapySDR device initialized:\n");
	printf("  Sample rate: %.2f MHz\n", sdr->config.sample_rate / 1e6);
	printf("  Frequency: %.2f MHz\n", sdr->config.frequency / 1e6);
	printf("  Gain: %s", sdr->config.gain_mode ? "Auto" : "Manual");
	if(!sdr->config.gain_mode) printf(" (%.1f dB)", sdr->config.gain);
	printf("\n");
	printf("  MTU: %zu samples\n", ctx->mtu);

	return 0;
}

static int soapy_start(sdr_t *sdr)
{
	soapy_ctx_t *ctx = (soapy_ctx_t*)sdr->device_handle;

	int r = SoapySDRDevice_activateStream(ctx->device, ctx->stream, 0, 0, 0);
	if(r != 0)
	{
		fprintf(stderr, "SoapySDR: Failed to activate stream\n");
		return -1;
	}

	return 0;
}

static int soapy_read(sdr_t *sdr, int16_t *samples, int count)
{
	soapy_ctx_t *ctx = (soapy_ctx_t*)sdr->device_handle;
	void *buffs[] = { samples };
	int flags = 0;
	long long time_ns = 0;

	int r = SoapySDRDevice_readStream(ctx->device, ctx->stream, buffs,
		count / 2, &flags, &time_ns, 100000);  /* 100ms timeout */

	if(r < 0)
	{
		if(r == SOAPY_SDR_OVERFLOW)
		{
			sdr->overruns++;
			return 0;  /* Continue */
		}
		fprintf(stderr, "SoapySDR: Read error: %s\n",
			SoapySDR_errToStr(r));
		return -1;
	}

	sdr->samples_received += r;

	return r * 2;  /* Return number of int16 values (I and Q) */
}

static int soapy_stop(sdr_t *sdr)
{
	soapy_ctx_t *ctx = (soapy_ctx_t*)sdr->device_handle;

	SoapySDRDevice_deactivateStream(ctx->device, ctx->stream, 0, 0);

	return 0;
}

static void soapy_close(sdr_t *sdr)
{
	soapy_ctx_t *ctx = (soapy_ctx_t*)sdr->device_handle;

	if(ctx)
	{
		if(ctx->stream)
		{
			SoapySDRDevice_closeStream(ctx->device, ctx->stream);
		}
		if(ctx->device)
		{
			SoapySDRDevice_unmake(ctx->device);
		}
		free(ctx);
		sdr->device_handle = NULL;
	}
}

#endif /* HAVE_SOAPYSDR */

/* =======================================================================*/
/* PlutoSDR (libiio) Implementation                                      */
/* =======================================================================*/

#ifdef HAVE_LIBIIO

typedef struct {
	struct iio_context *ctx;
	struct iio_device *phy;
	struct iio_device *dev;
	struct iio_channel *rx0_i;
	struct iio_channel *rx0_q;
	struct iio_buffer *rxbuf;
} pluto_ctx_t;

static int pluto_init(sdr_t *sdr)
{
	pluto_ctx_t *ctx;
	int r;

	ctx = calloc(1, sizeof(pluto_ctx_t));
	if(!ctx) return -1;

	/* Create IIO context */
	if(sdr->config.device_id && strstr(sdr->config.device_id, "ip:"))
	{
		/* Network connection */
		ctx->ctx = iio_create_network_context(sdr->config.device_id + 3);
	}
	else if(sdr->config.device_id && strstr(sdr->config.device_id, "usb:"))
	{
		/* USB connection */
		ctx->ctx = iio_create_context_from_uri(sdr->config.device_id);
	}
	else
	{
		/* Default - local or auto-discover */
		ctx->ctx = iio_create_default_context();
	}

	if(!ctx->ctx)
	{
		fprintf(stderr, "PlutoSDR: Failed to create IIO context\n");
		free(ctx);
		return -1;
	}

	/* Get AD9361 phy device */
	ctx->phy = iio_context_find_device(ctx->ctx, "ad9361-phy");
	if(!ctx->phy)
	{
		fprintf(stderr, "PlutoSDR: Could not find ad9361-phy device\n");
		iio_context_destroy(ctx->ctx);
		free(ctx);
		return -1;
	}

	/* Get RX streaming device */
	ctx->dev = iio_context_find_device(ctx->ctx, "cf-ad9361-lpc");
	if(!ctx->dev)
	{
		fprintf(stderr, "PlutoSDR: Could not find streaming device\n");
		iio_context_destroy(ctx->ctx);
		free(ctx);
		return -1;
	}

	/* Configure PHY */
	struct iio_channel *phy_chn;

	/* RX LO frequency */
	phy_chn = iio_device_find_channel(ctx->phy, "altvoltage0", true);
	if(phy_chn)
	{
		iio_channel_attr_write_longlong(phy_chn, "frequency",
			(long long)sdr->config.frequency);
	}

	/* Sampling frequency */
	phy_chn = iio_device_find_channel(ctx->phy, "voltage0", false);
	if(phy_chn)
	{
		iio_channel_attr_write_longlong(phy_chn, "sampling_frequency",
			(long long)sdr->config.sample_rate);
	}

	/* RF bandwidth */
	if(sdr->config.bandwidth > 0 && phy_chn)
	{
		iio_channel_attr_write_longlong(phy_chn, "rf_bandwidth",
			(long long)sdr->config.bandwidth);
	}

	/* Gain control mode */
	if(phy_chn)
	{
		iio_channel_attr_write(phy_chn, "gain_control_mode",
			sdr->config.gain_mode ? "slow_attack" : "manual");

		if(!sdr->config.gain_mode)
		{
			iio_channel_attr_write_double(phy_chn, "hardwaregain",
				sdr->config.gain);
		}
	}

	/* Get RX channels */
	ctx->rx0_i = iio_device_find_channel(ctx->dev, "voltage0", false);
	ctx->rx0_q = iio_device_find_channel(ctx->dev, "voltage1", false);

	if(!ctx->rx0_i || !ctx->rx0_q)
	{
		fprintf(stderr, "PlutoSDR: Could not find RX channels\n");
		iio_context_destroy(ctx->ctx);
		free(ctx);
		return -1;
	}

	/* Enable channels */
	iio_channel_enable(ctx->rx0_i);
	iio_channel_enable(ctx->rx0_q);

	sdr->device_handle = ctx;

	printf("PlutoSDR device initialized:\n");
	printf("  Sample rate: %.2f MHz\n", sdr->config.sample_rate / 1e6);
	printf("  Frequency: %.2f MHz\n", sdr->config.frequency / 1e6);
	printf("  Gain: %s", sdr->config.gain_mode ? "Auto" : "Manual");
	if(!sdr->config.gain_mode) printf(" (%.1f dB)", sdr->config.gain);
	printf("\n");

	return 0;
}

static int pluto_start(sdr_t *sdr)
{
	pluto_ctx_t *ctx = (pluto_ctx_t*)sdr->device_handle;

	/* Create buffer */
	ctx->rxbuf = iio_device_create_buffer(ctx->dev,
		sdr->config.buffer_size ? sdr->config.buffer_size : 4096, false);

	if(!ctx->rxbuf)
	{
		fprintf(stderr, "PlutoSDR: Failed to create buffer\n");
		return -1;
	}

	return 0;
}

static int pluto_read(sdr_t *sdr, int16_t *samples, int count)
{
	pluto_ctx_t *ctx = (pluto_ctx_t*)sdr->device_handle;
	ssize_t nbytes;

	nbytes = iio_buffer_refill(ctx->rxbuf);
	if(nbytes < 0)
	{
		fprintf(stderr, "PlutoSDR: Error refilling buffer: %zd\n", nbytes);
		return -1;
	}

	/* Get pointer to buffer data */
	void *p_dat = iio_buffer_first(ctx->rxbuf, ctx->rx0_i);
	void *p_end = iio_buffer_end(ctx->rxbuf);
	ptrdiff_t p_inc = iio_buffer_step(ctx->rxbuf);

	/* Copy samples */
	int n = 0;
	for(void *p = p_dat; p < p_end && n < count; p += p_inc, n += 2)
	{
		/* PlutoSDR uses int16 I/Q samples */
		int16_t *iq = (int16_t*)p;
		samples[n] = iq[0];     /* I */
		samples[n + 1] = iq[1]; /* Q */
	}

	sdr->samples_received += n / 2;

	return n;
}

static int pluto_stop(sdr_t *sdr)
{
	pluto_ctx_t *ctx = (pluto_ctx_t*)sdr->device_handle;

	if(ctx->rxbuf)
	{
		iio_buffer_destroy(ctx->rxbuf);
		ctx->rxbuf = NULL;
	}

	return 0;
}

static void pluto_close(sdr_t *sdr)
{
	pluto_ctx_t *ctx = (pluto_ctx_t*)sdr->device_handle;

	if(ctx)
	{
		if(ctx->rxbuf)
		{
			iio_buffer_destroy(ctx->rxbuf);
		}
		if(ctx->rx0_i) iio_channel_disable(ctx->rx0_i);
		if(ctx->rx0_q) iio_channel_disable(ctx->rx0_q);
		if(ctx->ctx)
		{
			iio_context_destroy(ctx->ctx);
		}
		free(ctx);
		sdr->device_handle = NULL;
	}
}

#endif /* HAVE_LIBIIO */

/* =======================================================================*/
/* Public API Implementation                                             */
/* =======================================================================*/

int sdr_init(sdr_t *sdr, sdr_config_t *config)
{
	memset(sdr, 0, sizeof(sdr_t));
	memcpy(&sdr->config, config, sizeof(sdr_config_t));
	sdr->type = config->type;

	/* Allocate buffer */
	sdr->buffer_size = config->buffer_size ? config->buffer_size : 8192;
	sdr->buffer = calloc(sdr->buffer_size, sizeof(int16_t));
	if(!sdr->buffer)
	{
		return -1;
	}

	switch(config->type)
	{
#ifdef HAVE_SOAPYSDR
		case SDR_TYPE_SOAPYSDR:
			return soapy_init(sdr);
#endif

#ifdef HAVE_LIBIIO
		case SDR_TYPE_PLUTOSDR:
			return pluto_init(sdr);
#endif

		default:
			fprintf(stderr, "SDR type not supported in this build\n");
			free(sdr->buffer);
			return -1;
	}
}

int sdr_start(sdr_t *sdr)
{
	sdr->running = 1;

	switch(sdr->type)
	{
#ifdef HAVE_SOAPYSDR
		case SDR_TYPE_SOAPYSDR:
			return soapy_start(sdr);
#endif

#ifdef HAVE_LIBIIO
		case SDR_TYPE_PLUTOSDR:
			return pluto_start(sdr);
#endif

		default:
			return -1;
	}
}

int sdr_read(sdr_t *sdr, int16_t *samples, int count)
{
	switch(sdr->type)
	{
#ifdef HAVE_SOAPYSDR
		case SDR_TYPE_SOAPYSDR:
			return soapy_read(sdr, samples, count);
#endif

#ifdef HAVE_LIBIIO
		case SDR_TYPE_PLUTOSDR:
			return pluto_read(sdr, samples, count);
#endif

		default:
			return -1;
	}
}

int sdr_stop(sdr_t *sdr)
{
	sdr->running = 0;

	switch(sdr->type)
	{
#ifdef HAVE_SOAPYSDR
		case SDR_TYPE_SOAPYSDR:
			return soapy_stop(sdr);
#endif

#ifdef HAVE_LIBIIO
		case SDR_TYPE_PLUTOSDR:
			return pluto_stop(sdr);
#endif

		default:
			return -1;
	}
}

void sdr_close(sdr_t *sdr)
{
	if(sdr->running)
	{
		sdr_stop(sdr);
	}

	switch(sdr->type)
	{
#ifdef HAVE_SOAPYSDR
		case SDR_TYPE_SOAPYSDR:
			soapy_close(sdr);
			break;
#endif

#ifdef HAVE_LIBIIO
		case SDR_TYPE_PLUTOSDR:
			pluto_close(sdr);
			break;
#endif

		default:
			break;
	}

	if(sdr->buffer)
	{
		free(sdr->buffer);
		sdr->buffer = NULL;
	}
}

const char* sdr_get_device_name(sdr_t *sdr)
{
	switch(sdr->type)
	{
		case SDR_TYPE_SOAPYSDR: return "SoapySDR";
		case SDR_TYPE_PLUTOSDR: return "PlutoSDR (IIO)";
		case SDR_TYPE_FILE: return "File";
		default: return "Unknown";
	}
}

int sdr_set_frequency(sdr_t *sdr, double frequency)
{
	sdr->config.frequency = frequency;

#ifdef HAVE_SOAPYSDR
	if(sdr->type == SDR_TYPE_SOAPYSDR)
	{
		soapy_ctx_t *ctx = (soapy_ctx_t*)sdr->device_handle;
		return SoapySDRDevice_setFrequency(ctx->device, SOAPY_SDR_RX, 0,
			frequency, NULL);
	}
#endif

#ifdef HAVE_LIBIIO
	if(sdr->type == SDR_TYPE_PLUTOSDR)
	{
		pluto_ctx_t *ctx = (pluto_ctx_t*)sdr->device_handle;
		struct iio_channel *phy_chn = iio_device_find_channel(ctx->phy,
			"altvoltage0", true);
		if(phy_chn)
		{
			return iio_channel_attr_write_longlong(phy_chn, "frequency",
				(long long)frequency);
		}
	}
#endif

	return -1;
}

int sdr_set_gain(sdr_t *sdr, double gain)
{
	sdr->config.gain = gain;

#ifdef HAVE_SOAPYSDR
	if(sdr->type == SDR_TYPE_SOAPYSDR)
	{
		soapy_ctx_t *ctx = (soapy_ctx_t*)sdr->device_handle;
		return SoapySDRDevice_setGain(ctx->device, SOAPY_SDR_RX, 0, gain);
	}
#endif

#ifdef HAVE_LIBIIO
	if(sdr->type == SDR_TYPE_PLUTOSDR)
	{
		pluto_ctx_t *ctx = (pluto_ctx_t*)sdr->device_handle;
		struct iio_channel *phy_chn = iio_device_find_channel(ctx->phy,
			"voltage0", false);
		if(phy_chn)
		{
			return iio_channel_attr_write_double(phy_chn, "hardwaregain", gain);
		}
	}
#endif

	return -1;
}
