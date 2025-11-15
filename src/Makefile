
VERSION := $(shell git log -1 --pretty='%cd' --date=format:'%Y%m%d')-$(shell git describe --dirty --always)
CC      := $(CROSS_HOST)gcc
PKGCONF := pkg-config
CFLAGS  := -g -Wall -pthread -O3 $(EXTRA_CFLAGS) -DVERSION=\"$(VERSION)\"
LDFLAGS := -g -lm -pthread $(EXTRA_LDFLAGS)
OBJS    := hacktv.o common.o fir.o vbidata.o teletext.o wss.o video.o fifo.o mac.o dance.o eurocrypt.o videocrypt.o videocrypts.o syster.o syster-ca.o acp.o vits.o vitc.o nicam728.o sis.o av.o av_test.o av_ffmpeg.o rf.o rf_file.o spdif.o cc608.o
RX_OBJS := hackrx.o receiver.o pll.o common.o fir.o nicam_decoder.o teletext_decoder.o video_output.o wss_decoder.o vitc_decoder.o
RX_PKGS :=
PKGS    := libavcodec libavformat libavdevice libswscale libswresample libavutil $(EXTRA_PKGS)

HACKRF := $(shell $(PKGCONF) --exists libhackrf && echo hackrf)
ifeq ($(HACKRF),hackrf)
	OBJS += rf_hackrf.o
	PKGS += libhackrf
	CFLAGS += -DHAVE_HACKRF
endif

SOAPYSDR := $(shell $(PKGCONF) --exists SoapySDR && echo SoapySDR)
ifeq ($(SOAPYSDR),SoapySDR)
	OBJS += rf_soapysdr.o
	PKGS += SoapySDR
	CFLAGS += -DHAVE_SOAPYSDR
endif

FL2K := $(shell $(PKGCONF) --exists libosmo-fl2k && echo fl2k)
ifeq ($(FL2K),fl2k)
	OBJS += rf_fl2k.o
	PKGS += libosmo-fl2k
	CFLAGS += -DHAVE_FL2K
endif

PLUTOSDR := $(shell $(PKGCONF) --exists libiio && echo plutosdr)
ifeq ($(PLUTOSDR),plutosdr)
	OBJS += rf_plutosdr.o
	PKGS += libiio
	CFLAGS += -DHAVE_PLUTOSDR
endif

# Receiver-specific SDR support
RX_SOAPYSDR := $(shell $(PKGCONF) --exists SoapySDR && echo SoapySDR)
ifeq ($(RX_SOAPYSDR),SoapySDR)
	RX_OBJS += rf_sdr.o
	RX_PKGS += SoapySDR
	CFLAGS += -DHAVE_RX_SOAPYSDR
endif

LIBIIO := $(shell $(PKGCONF) --exists libiio && echo libiio)
ifeq ($(LIBIIO),libiio)
	ifndef RX_SOAPYSDR
		RX_OBJS += rf_sdr.o
	endif
	RX_PKGS += libiio
	CFLAGS += -DHAVE_LIBIIO
endif

CFLAGS  += $(shell $(PKGCONF) --cflags $(PKGS))
LDFLAGS += $(shell $(PKGCONF) --libs $(PKGS))
RX_CFLAGS := $(CFLAGS) $(shell $(PKGCONF) --cflags $(RX_PKGS))
RX_LDFLAGS := $(LDFLAGS) $(shell $(PKGCONF) --libs $(RX_PKGS))

all: hacktv hackrx

hacktv: $(OBJS)
	$(CC) -o hacktv $(OBJS) $(LDFLAGS)

hackrx: $(RX_OBJS)
	$(CC) -o hackrx $(RX_OBJS) $(RX_LDFLAGS)

%.o: %.c Makefile
	$(CC) $(CFLAGS) -c $< -o $@
	@$(CC) $(CFLAGS) -MM $< -o $(@:.o=.d)

install:
	cp -f hacktv $(PREFIX)/usr/local/bin/
	cp -f hackrx $(PREFIX)/usr/local/bin/

clean:
	rm -f *.o *.d hacktv hackrx hacktv.exe hackrx.exe

-include $(OBJS:.o=.d)

