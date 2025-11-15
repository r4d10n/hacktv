/* rf_sdr.h - SDR Hardware Input Interface */
/*=======================================================================*/
/* Copyright 2025 - SDR Input for HackTV Receiver                        */
/*=======================================================================*/

#ifndef _RF_SDR_H
#define _RF_SDR_H

#include <stdint.h>
#include <stdlib.h>

/* SDR device types */
typedef enum {
	SDR_TYPE_FILE,      /* File input (existing) */
	SDR_TYPE_SOAPYSDR,  /* SoapySDR (RTL-SDR, PlutoSDR, etc.) */
	SDR_TYPE_PLUTOSDR,  /* PlutoSDR native (IIO) */
} sdr_type_t;

/* SDR configuration */
typedef struct {
	sdr_type_t type;

	/* Common parameters */
	double frequency;        /* Center frequency in Hz */
	double sample_rate;      /* Sample rate in Hz */
	double bandwidth;        /* IF bandwidth in Hz */
	int gain_mode;          /* 0=manual, 1=auto */
	double gain;            /* Manual gain in dB */

	/* Device-specific */
	const char *device_id;   /* Device identifier string */
	const char *antenna;     /* Antenna port */

	/* Buffer settings */
	int buffer_size;        /* Samples per buffer */
	int num_buffers;        /* Number of buffers */
} sdr_config_t;

/* SDR device state */
typedef struct {
	sdr_type_t type;
	void *device_handle;    /* Platform-specific device handle */

	/* Configuration */
	sdr_config_t config;

	/* Status */
	int running;
	uint64_t samples_received;
	uint64_t overruns;

	/* Buffer management */
	int16_t *buffer;
	size_t buffer_size;
	size_t buffer_pos;
} sdr_t;

/* Function prototypes */

/* Initialize SDR device */
int sdr_init(sdr_t *sdr, sdr_config_t *config);

/* Start receiving */
int sdr_start(sdr_t *sdr);

/* Stop receiving */
int sdr_stop(sdr_t *sdr);

/* Read IQ samples (blocking) */
int sdr_read(sdr_t *sdr, int16_t *samples, int count);

/* Close SDR device */
void sdr_close(sdr_t *sdr);

/* Get device info */
const char* sdr_get_device_name(sdr_t *sdr);
int sdr_get_device_list(char ***devices);

/* Tuning functions */
int sdr_set_frequency(sdr_t *sdr, double frequency);
int sdr_set_sample_rate(sdr_t *sdr, double rate);
int sdr_set_gain(sdr_t *sdr, double gain);
int sdr_set_gain_mode(sdr_t *sdr, int automatic);

#endif /* _RF_SDR_H */
