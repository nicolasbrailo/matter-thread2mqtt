# matter-thread2mqtt docker image

# TODO: Run container as user
# TODO: Use C3 as HCI/BT/BLE device for commissining, then remove commissioning mode
# TODO: Bridge matter to mqtt

# Base: Debian bookworm-slim (glibc + apt + supported by ot-br-posix bootstrap, even if we don't use it)
FROM python:3.13-slim-bookworm

RUN apt-get update

## --- dev / debug utilities --------------------------------------------------
## Purely for poking at a running container; none of this is required to run
RUN apt-get install -y --no-install-recommends \
      vim \
      file \
      less \
      curl \
      lsof \
      htop \
      procps \
      netcat-openbsd \
      dnsutils \
      iputils-ping \
      strace \
      avahi-utils


# Persistent mount for run config and settings (eg Thread network state).
# This is meant to outlive the container: mount a host directory here at run time
RUN mkdir -p /mt2mqtt-run


#
# Install ot-br-posix
#

# --- ot-br-posix build dependencies -----------------------------------------
# Curated from ot-br-posix's script/bootstrap install_packages_apt(), trimmed
# to our cmake flags: NAT64 / WEB / BACKBONE_ROUTER are OFF, so iptables, bind9,
# dhcpcd, radvd, nodejs/npm, ipset, libnetfilter-queue and the from-source
# mDNSResponder build are all dropped. mDNS backend = avahi (default); DBUS and
# REST are ON.
RUN apt-get install -y --no-install-recommends \
      ca-certificates \
      git \
      build-essential \
      cmake \
      ninja-build \
      libdbus-1-dev \
      libreadline-dev \
      libncurses-dev \
      libavahi-client-dev \
      libavahi-common-dev \
      libjsoncpp-dev \
      libprotobuf-dev \
      protobuf-compiler \
      libgmock-dev \
      libgtest-dev

# --- runtime dependencies ---------------------------------------------------
# Needed to actually RUN otbr-agent: dbus, avahi-daemon (mDNS publisher), iproute2 (entrypoint
# creates the ot-infra dummy interface with `ip link add`).
RUN apt-get install -y --no-install-recommends \
      dbus \
      avahi-daemon \
      iproute2


# Needed for commissioning: a BT stack
# creates the ot-infra dummy interface with `ip link add`).
RUN apt-get install -y --no-install-recommends \
      bluez


# --- ot-br-posix source -----------------------------------------------------
# Cloned from upstream, pinned to the exact commit verified locally. The order
# matters: clone (default branch) -> checkout the pinned commit -> THEN init
# submodules, so each submodule lands on the SHA recorded *at that commit*
# rather than at HEAD of main. Recursive picks up openthread's nested
# submodules (mbedtls, etc.) the build needs. Full clone (not --depth 1) so
# `git describe` still produces a version for OTBR's build.
# Docker caches this layer by instruction text, so pinning OTBR_REF also gives
# correct cache behaviour: bump the ARG to force a re-clone.
ARG OTBR_REF=582c551
RUN git clone https://github.com/openthread/ot-br-posix.git /src/ot-br-posix \
    && cd /src/ot-br-posix \
    && git checkout ${OTBR_REF} \
    && git submodule update --init --recursive

RUN mkdir /src/ot-br-posix/build && cd /src/ot-br-posix/build && cmake -GNinja \
    -DOTBR_INFRA_IF_NAME=lo \
    -DOTBR_BORDER_ROUTING=ON \
    -DOTBR_BACKBONE_ROUTER=OFF \
    -DOTBR_NAT64=OFF \
    -DOTBR_WEB=OFF \
    -DOTBR_REST=ON \
    -DOTBR_DBUS=ON \
    -DOTBR_VENDOR_NAME="NicoMT2M" \
    -DOTBR_PRODUCT_NAME="NicoMT2M-otbr" \
    -DOT_POSIX_SETTINGS_PATH='"/mt2mqtt-run/otbr/"' \
    /src/ot-br-posix/
RUN cd /src/ot-br-posix/build && ninja

# Make ot-br bins available through path
RUN mkdir /mt2mqtt-bin
RUN ln -s /src/ot-br-posix/build/third_party/openthread/repo/src/posix/ot-ctl /mt2mqtt-bin
RUN ln -s /src/ot-br-posix/build/src/agent/otbr-agent /mt2mqtt-bin
RUN echo "ot-ctl state" > /mt2mqtt-bin/mt2mqtt-otbr-net-state
RUN chmod +x /mt2mqtt-bin/mt2mqtt-otbr-net-state
ENV PATH="/mt2mqtt-bin:${PATH}"

# --- D-Bus policy -----------------------------------------------------------
# Built with OTBR_DBUS=ON, so otbr-agent tries to own io.openthread.BorderRouter.wpan0
# on the system bus.
RUN install -D -m 644 \
      /src/ot-br-posix/build/src/agent/otbr-agent.conf \
      /etc/dbus-1/system.d/otbr-agent.conf


#
# Install python-matter-server
#

# Clone a repo with certs we can use for provisioning
RUN mkdir -p /src/connectedhomeip
RUN git clone --depth 1 --filter=blob:none --sparse https://github.com/project-chip/connectedhomeip /src/connectedhomeip
RUN git -C /src/connectedhomeip sparse-checkout set credentials/production/paa-root-certs

# Make the matter-server module available in system python
RUN pip install --no-cache-dir "python-matter-server[server]"
RUN apt-get install -y --no-install-recommends \
      libglib2.0-0 \
      libnl-route-3-200

RUN mkdir /data
RUN ln -s /data /mt2mqtt-run/matter-server-data


# --- s6-overlay: lightweight container init / process supervisor ------------
RUN apt-get install -y --no-install-recommends xz-utils
# Bump to pull a newer s6-overlay; see github.com/just-containers/s6-overlay/releases
ARG S6_OVERLAY_VERSION=3.2.0.2
RUN set -eux; \
      base="https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}"; \
      arch="$(uname -m)"; \
      curl -fsSL "${base}/s6-overlay-noarch.tar.xz"   -o /tmp/s6-noarch.tar.xz; \
      curl -fsSL "${base}/s6-overlay-${arch}.tar.xz"  -o /tmp/s6-arch.tar.xz; \
      tar -C / -Jxpf /tmp/s6-noarch.tar.xz; \
      tar -C / -Jxpf /tmp/s6-arch.tar.xz; \
      rm -f /tmp/s6-noarch.tar.xz /tmp/s6-arch.tar.xz

# s6 handles container services startup, like an init.d
COPY s6-overlay/s6-rc.d /etc/s6-overlay/s6-rc.d

RUN echo 'for s in /run/service/*; do printf "%-22s " "$(basename "$s")"; /command/s6-svstat "$s"; done' > /mt2mqtt-bin/mt2mqtt-services.sh
RUN chmod +x /mt2mqtt-bin/mt2mqtt-services.sh

# Abort the container if startup fails
ENV S6_BEHAVIOUR_IF_STAGE2_FAILS=2

# s6-overlay's /init is PID 1
ENTRYPOINT ["/init"]


## TODO: fw host driver
COPY fw/host_driver /src/fw/host_driver
RUN make -C /src/fw/host_driver
RUN ln -s /src/fw/host_driver/host /mt2mqtt-bin/spinel_bt_mux_driver

## TODO: proxy mqtt
COPY mqtt_bridge /src/


# -- Cleanup
# apt cache not needed anymore, and it's big
RUN rm -rf /var/lib/apt/lists/*

