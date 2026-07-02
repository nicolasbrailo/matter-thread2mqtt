.PHONY: rebuild start start-bare stop shell logs

NAME := mt2mqtt

# shell/logs attach to the running container (only `mt2mqtt` now -- commissioning
# is no longer a separate mode; see `start`).
CONTAINER = $(shell docker ps --format '{{.Names}}' | grep -E '^$(NAME)$$' | head -1)

# Host directory bind-mounted at /mt2mqtt-run so Thread network state (and any
# future editable configs) survive `make stop` (which does `docker rm -f`) and
# can be backed up directly from the host. Override with `make start RUNDIR=...`.
RUNDIR := $(CURDIR)/mt2mqtt-run

# Host directory bind-mounted at /var/log, where all in-container logs land: the
# s6 catch-all (/var/log/s6-overlay) plus the per-service loggers
# (/var/log/{dbus,avahi,otbr-agent}). Exposed so logs are readable from the host
# and survive `make stop`. Override with `make start LOGDIR=...`.
LOGDIR := $(CURDIR)/mt2mqtt-log

rebuild:
	docker build -t mt2mqtt:dev -f ./Dockerfile .

# Pick the dongle by its stable by-id name, but resolve it to the real
# /dev/ttyACMx node — that path has no colons, so --device can parse it
# (--device splits its arg on ':', and the by-id name embeds a MAC with colons).
RCP_BYID := '/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_*'
RCP      := $(shell readlink -f '$(RCP_BYID)')

# The container runs fully isolated (its own netns: wpan0, avahi and its own system
# dbus never touch the LAN) AND can commission over BLE,
# because it reaches the HOST's BlueZ purely over the host system D-Bus socket,
# bind-mounted read-write at /run/host_dbus/system_bus_socket. D-Bus is a unix
# socket (not netns-bound), so it crosses the boundary while nothing routable
# does; the host's bluetoothd does all radio work in init_net and only
# BTP-over-GATT D-Bus traffic crosses. matter-server/run auto-detects a usable
# host BlueZ on that bus (org.bluez owned) and enables BLE; when the host has no
# working Bluetooth it degrades cleanly to an operational-only bridge.
#
# NOTE: the raw socket exposes the whole host system bus, not just org.bluez.
# TODO (step 2b): front it with an xdg-dbus-proxy scoped to org.bluez.
start:
	mkdir -p '$(RUNDIR)' '$(LOGDIR)'
	docker run -d --name $(NAME) \
		-v /run/dbus/system_bus_socket:/run/host_dbus/system_bus_socket \
		-v '$(RUNDIR)':/mt2mqtt-run \
		-v '$(LOGDIR)':/var/log \
		--device $(RCP):/dev/ttyACM0 \
		--device /dev/net/tun --cap-add NET_ADMIN \
		mt2mqtt:dev

# Bare debug shell: same image and device/volume/cap setup as `make start`, but
# overrides the /init entrypoint so s6-overlay never runs — nothing is started
# automatically. Use this to bring the stack up one service at a time (e.g. when
# testing the C6 mux) without the otbr-agent-net oneshot spinning on a net that
# isn't ready and timing out the whole container (S6_BEHAVIOUR_IF_STAGE2_FAILS=2).
#
# With no s6 supervisor there's no s6-rc; start dependencies by hand, e.g.:
#   dbus-daemon --system & avahi-daemon & ...   (see the s6 run scripts)
# Runs interactively as `mt2mqtt` and is removed on exit (--rm). `make shell`
# from another terminal opens a second shell into it.
start-bare:
	mkdir -p '$(RUNDIR)' '$(LOGDIR)'
	docker run -it --rm --name $(NAME) \
		--security-opt apparmor=unconfined \
		--entrypoint /bin/bash \
		-v /run/dbus/system_bus_socket:/run/host_dbus/system_bus_socket \
		-v '$(RUNDIR)':/mt2mqtt-run \
		-v '$(LOGDIR)':/var/log \
		--device $(RCP):/dev/ttyACM0 \
		--device /dev/net/tun --cap-add NET_ADMIN \
		mt2mqtt:dev

stop:
	docker rm -f $(NAME)

# Attach an interactive shell to the already-running container.
shell:
	docker exec -it $(CONTAINER) bash

# Follow the entrypoint's output — the only way to see it in detached mode.
logs:
	docker logs -f $(CONTAINER)
