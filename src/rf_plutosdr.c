/* hacktv - Analogue video transmitter for PlutoSDR                     */
/*=======================================================================*/
/* Copyright 2025                                                        */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
#include <iio.h>
#include "rf.h"
#include "fifo.h"

#define PLUTO_BUFFER_SIZE 16384  /* Samples per buffer */

typedef struct {

	/* libiio context and devices */
	struct iio_context *ctx;
	struct iio_device *phy;
	struct iio_device *tx_dev;
	struct iio_channel *tx_i;
	struct iio_channel *tx_q;
	struct iio_buffer *txbuf;

	/* Configuration */
	uint32_t sample_rate;
	uint64_t frequency;
	double gain;

	/* Buffers */
	fifo_t buffers;
	fifo_reader_t buffers_reader;

	/* Thread */
	pthread_t thread;
	int thread_running;

	/* Stats */
	uint32_t underruns;

} plutosdr_t;

static void *_tx_thread(void *arg)
{
	plutosdr_t *rf = (plutosdr_t *) arg;
	int16_t *pbuf;
	ssize_t r;
	void *txdata;
	ptrdiff_t p_inc;

	while(rf->thread_running)
	{
		/* Get IIO buffer pointer */
		txdata = iio_buffer_first(rf->txbuf, rf->tx_i);
		if(!txdata)
		{
			fprintf(stderr, "PlutoSDR: Failed to get TX buffer pointer\n");
			break;
		}

		/* Get samples from FIFO */
		r = fifo_read(&rf->buffers_reader, (void **) &pbuf, PLUTO_BUFFER_SIZE, 0);

		if(r == 0)
		{
			/* Buffer underrun */
			if(rf->buffers_reader.prefill == NULL)
			{
				fprintf(stderr, "U");
				rf->underruns++;
			}

			/* Fill with zeros */
			memset(txdata, 0, PLUTO_BUFFER_SIZE * 2 * sizeof(int16_t));
		}
		else if(r < 0)
		{
			/* EOF */
			fifo_reader_close(&rf->buffers_reader);
			rf->thread_running = 0;
			break;
		}
		else
		{
			/* Copy IQ data to IIO buffer */
			/* PlutoSDR expects int16 I/Q interleaved */
			memcpy(txdata, pbuf, r * 2 * sizeof(int16_t));

			/* Fill remainder with zeros if needed */
			if(r < PLUTO_BUFFER_SIZE)
			{
				memset(txdata + r * 2 * sizeof(int16_t), 0,
				       (PLUTO_BUFFER_SIZE - r) * 2 * sizeof(int16_t));
			}
		}

		/* Push buffer to PlutoSDR */
		ssize_t nbytes = iio_buffer_push(rf->txbuf);
		if(nbytes < 0)
		{
			fprintf(stderr, "PlutoSDR: Failed to push buffer: %s\n", strerror(-nbytes));
			break;
		}
	}

	return(NULL);
}

static int _rf_plutosdr_close(void *private)
{
	plutosdr_t *rf = (plutosdr_t *) private;

	/* Stop thread */
	if(rf->thread_running)
	{
		rf->thread_running = 0;
		pthread_join(rf->thread, NULL);
	}

	/* Clean up IIO */
	if(rf->txbuf) iio_buffer_destroy(rf->txbuf);
	if(rf->tx_i) iio_channel_disable(rf->tx_i);
	if(rf->tx_q) iio_channel_disable(rf->tx_q);
	if(rf->ctx) iio_context_destroy(rf->ctx);

	/* Clean up buffers */
	fifo_reader_close(&rf->buffers_reader);
	fifo_free(&rf->buffers);

	/* Report stats */
	if(rf->underruns > 0)
	{
		fprintf(stderr, "\nPlutoSDR: %u buffer underruns occurred\n", rf->underruns);
	}

	free(rf);

	return(RF_OK);
}

static int _rf_plutosdr_write(void *private, const int16_t *iq_data, size_t samples)
{
	plutosdr_t *rf = (plutosdr_t *) private;

	/* Write to FIFO */
	if(fifo_write(&rf->buffers, iq_data, samples * 2 * sizeof(int16_t)) != 0)
	{
		return(RF_ERROR);
	}

	return(RF_OK);
}

int rf_plutosdr_open(rf_t *s, const char *uri, uint32_t sample_rate, uint64_t frequency_hz, double gain_db)
{
	plutosdr_t *rf;
	int r;
	long long tmp;

	rf = calloc(1, sizeof(plutosdr_t));
	if(!rf)
	{
		return(RF_OUT_OF_MEMORY);
	}

	rf->sample_rate = sample_rate;
	rf->frequency = frequency_hz;
	rf->gain = gain_db;
	rf->underruns = 0;

	/* Create IIO context */
	if(uri && strlen(uri) > 0)
	{
		rf->ctx = iio_create_context_from_uri(uri);
	}
	else
	{
		/* Auto-detect PlutoSDR */
		rf->ctx = iio_create_default_context();
	}

	if(!rf->ctx)
	{
		fprintf(stderr, "PlutoSDR: Failed to create IIO context\n");
		fprintf(stderr, "Make sure PlutoSDR is connected and drivers are installed\n");
		free(rf);
		return(RF_ERROR);
	}

	/* Get PHY device */
	rf->phy = iio_context_find_device(rf->ctx, "ad9361-phy");
	if(!rf->phy)
	{
		fprintf(stderr, "PlutoSDR: Failed to find ad9361-phy device\n");
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	/* Get TX device */
	rf->tx_dev = iio_context_find_device(rf->ctx, "cf-ad9361-dds-core-lpc");
	if(!rf->tx_dev)
	{
		fprintf(stderr, "PlutoSDR: Failed to find TX device\n");
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	/* Configure PHY */
	/* Set TX LO frequency */
	struct iio_channel *tx_lo = iio_device_find_channel(rf->phy, "altvoltage1", true);
	if(tx_lo)
	{
		iio_channel_attr_write_longlong(tx_lo, "frequency", frequency_hz);
	}
	else
	{
		fprintf(stderr, "PlutoSDR: Warning - could not find TX LO channel\n");
	}

	/* Set sample rate */
	struct iio_channel *phy_tx = iio_device_find_channel(rf->phy, "voltage0", true);
	if(phy_tx)
	{
		iio_channel_attr_write_longlong(phy_tx, "sampling_frequency", sample_rate);

		/* Set RF bandwidth (typically 1.5x sample rate) */
		iio_channel_attr_write_longlong(phy_tx, "rf_bandwidth", sample_rate * 3 / 2);

		/* Set attenuation (gain) */
		/* PlutoSDR uses attenuation in mdB (milli-dB) */
		/* gain_db=0 -> 0dB attenuation (max power) */
		/* gain_db=-20 -> 20dB attenuation */
		long long atten_mdb = (long long)(-gain_db * 1000);
		if(atten_mdb < 0) atten_mdb = 0;
		if(atten_mdb > 89750) atten_mdb = 89750;  /* Max ~90dB attenuation */
		iio_channel_attr_write_longlong(phy_tx, "hardwaregain", -atten_mdb / 1000);
	}
	else
	{
		fprintf(stderr, "PlutoSDR: Warning - could not configure PHY TX channel\n");
	}

	/* Enable TX channels */
	rf->tx_i = iio_device_find_channel(rf->tx_dev, "voltage0", true);
	rf->tx_q = iio_device_find_channel(rf->tx_dev, "voltage1", true);

	if(!rf->tx_i || !rf->tx_q)
	{
		fprintf(stderr, "PlutoSDR: Failed to find TX I/Q channels\n");
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	iio_channel_enable(rf->tx_i);
	iio_channel_enable(rf->tx_q);

	/* Create TX buffer */
	rf->txbuf = iio_device_create_buffer(rf->tx_dev, PLUTO_BUFFER_SIZE, false);
	if(!rf->txbuf)
	{
		fprintf(stderr, "PlutoSDR: Failed to create TX buffer\n");
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	/* Make buffer cyclic (continuous TX) */
	/* Note: This may not be supported on all IIO versions */
	#ifdef iio_buffer_set_blocking_mode
	iio_buffer_set_blocking_mode(rf->txbuf, true);
	#endif

	/* Initialize FIFO */
	if(fifo_init(&rf->buffers, PLUTO_BUFFER_SIZE * 8) != 0)
	{
		fprintf(stderr, "PlutoSDR: Failed to initialize FIFO\n");
		iio_buffer_destroy(rf->txbuf);
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	if(fifo_reader_open(&rf->buffers_reader, &rf->buffers, PLUTO_BUFFER_SIZE * 2, 1000000) != 0)
	{
		fprintf(stderr, "PlutoSDR: Failed to open FIFO reader\n");
		fifo_free(&rf->buffers);
		iio_buffer_destroy(rf->txbuf);
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	/* Print configuration */
	printf("PlutoSDR TX opened:\n");
	printf("  Frequency: %llu Hz (%.3f MHz)\n",
	       (unsigned long long)frequency_hz, frequency_hz / 1e6);
	printf("  Sample rate: %u Hz (%.3f MHz)\n",
	       sample_rate, sample_rate / 1e6);
	printf("  Gain: %.1f dB\n", gain_db);

	/* Read back actual values */
	if(tx_lo)
	{
		iio_channel_attr_read_longlong(tx_lo, "frequency", &tmp);
		printf("  Actual frequency: %lld Hz\n", tmp);
	}
	if(phy_tx)
	{
		iio_channel_attr_read_longlong(phy_tx, "sampling_frequency", &tmp);
		printf("  Actual sample rate: %lld Hz\n", tmp);

		iio_channel_attr_read_longlong(phy_tx, "hardwaregain", &tmp);
		printf("  Actual gain: %lld dB\n", tmp);
	}

	/* Start TX thread */
	rf->thread_running = 1;
	if(pthread_create(&rf->thread, NULL, _tx_thread, rf) != 0)
	{
		fprintf(stderr, "PlutoSDR: Failed to create TX thread\n");
		fifo_reader_close(&rf->buffers_reader);
		fifo_free(&rf->buffers);
		iio_buffer_destroy(rf->txbuf);
		iio_context_destroy(rf->ctx);
		free(rf);
		return(RF_ERROR);
	}

	/* Register callbacks */
	s->ctx = rf;
	s->write = _rf_plutosdr_write;
	s->close = _rf_plutosdr_close;

	return(RF_OK);
}
