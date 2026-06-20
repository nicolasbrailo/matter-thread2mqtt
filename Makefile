.PHONY: rebuild start start-commission stop stop-commission shell logs

NAME := mt2mqtt

# shell/logs attach to whichever container is currently up: the isolated
# `mt2mqtt` (make start) or the host-net `mt2mqtt-commission` (make
# start-commission). Only one runs at a time, so first match wins.
CONTAINER = $(shell docker ps --format '{{.Names}}' | grep -E '^$(NAME)(-commission)?$$' | head -1)

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
RCP_BYID := /dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_E4:B3:23:A3:07:2C-if00
RCP      := $(shell readlink -f '$(RCP_BYID)')

start:
	mkdir -p '$(RUNDIR)' '$(LOGDIR)'
	docker run -d --name $(NAME) \
		-v '$(RUNDIR)':/mt2mqtt-run \
		-v '$(LOGDIR)':/var/log \
		--device $(RCP):/dev/ttyACM0 \
		--device /dev/net/tun --cap-add NET_ADMIN \
		mt2mqtt:dev

# Transient "commissioning mode": same image, but shares the host network
# namespace so the container can see the host's Bluetooth adapter (BT adapters
# are netns-bound — bridge-mode containers see none). BLE is only needed to
# pair a new device; once it's on Thread, matter-server reaches it over wpan0
# and you should go back to the isolated `make start`.
#
# Isolation caveat: --network host puts wpan0 and avahi in the host netns, so
# avahi must be locked to ot-infra (allow-interfaces=ot-infra) or it'll leak
# Matter mDNS onto the LAN. See NOTES "BLE commissioning needs a host adapter".
#
# MT2M_COMMISSION=1 signals the entrypoint to start bluetoothd and launch
# matter-server with --bluetooth-adapter 0 (instead of the 999 "no BLE"
# sentinel). Runs as `mt2mqtt-commission`; `shell`/`logs` auto-detect it via
# $(CONTAINER), and `stop-commission` tears it down and restarts host
# bluetooth. You can't run `start` and `start-commission` at once.
start-commission:
	mkdir -p '$(RUNDIR)' '$(LOGDIR)'
	# mask, not just stop: BlueZ is D-Bus-activated and WirePlumber's bluetooth
	# monitor pokes org.bluez constantly, respawning bluetoothd right after a
	# plain stop — it then fights the container for the adapter. mask blocks the
	# reactivation; the only cost is no host BT audio during commissioning.
	sudo systemctl mask bluetooth
	sudo systemctl stop bluetooth
	docker run -d --name $(NAME)-commission \
		--network host \
		-e MT2M_COMMISSION=1 \
		-v '$(RUNDIR)':/mt2mqtt-run \
		-v '$(LOGDIR)':/var/log \
		--device $(RCP):/dev/ttyACM0 \
		--device /dev/net/tun \
		--cap-add NET_ADMIN --cap-add NET_RAW \
		mt2mqtt:dev

stop-commission:
	docker rm -f $(NAME)-commission
	sudo systemctl unmask bluetooth
	sudo systemctl start bluetooth

stop:
	docker rm -f $(NAME)

# Attach an interactive shell to the already-running container.
shell:
	docker exec -it $(CONTAINER) bash

# Follow the entrypoint's output — the only way to see it in detached mode.
logs:
	docker logs -f $(CONTAINER)
