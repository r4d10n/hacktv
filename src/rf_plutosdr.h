/* hacktv - Analogue video transmitter for PlutoSDR                     */
/*=======================================================================*/
/* Copyright 2025                                                        */
/*                                                                       */
/* This program is free software: you can redistribute it and/or modify  */
/* it under the terms of the GNU General Public License as published by  */
/* the Free Software Foundation, either version 3 of the License, or     */
/* (at your option) any later version.                                   */
/*=======================================================================*/

#ifndef _RF_PLUTOSDR_H
#define _RF_PLUTOSDR_H

extern int rf_plutosdr_open(rf_t *s, const char *uri, uint32_t sample_rate, uint64_t frequency_hz, double gain_db);

#endif
