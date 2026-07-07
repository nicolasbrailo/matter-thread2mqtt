.PHONY: rebuild start start-bare bluez-proxy stop shell logs

NAME := mt2mqtt

# shell/logs attach to the running container (only `mt2mqtt` now -- commissioning
# is no longer a separate mode; see `start`).
CONTAINER = $(shell docker ps --format '{{.Names}}' | grep -E '^$(NAME)$$' | head -1)

# Host directory bind-mounted at /mt2mqtt-run so Thread network state, the
# per-service logs under /mt2mqtt-run/logs, and any future editable configs
# survive `make stop` (which does `docker rm -f`) and can be backed up directly
# from the host. Override with `make start RUNDIR=...`.
RUNDIR := $(CURDIR)/mt2mqtt-run

rebuild:
	sudo chown -R batman:batman $(RUNDIR)
	docker build -t mt2mqtt:dev -f ./Dockerfile .

# Pick the dongle by its stable by-id name, but resolve it to the real
# /dev/ttyACMx node — that path has no colons, so --device can parse it
# (--device splits its arg on ':', and the by-id name embeds a MAC with colons).
RCP_BYID := '/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_*'
RCP      := $(shell readlink -f '$(RCP_BYID)')

# The container runs fully isolated (its own netns: wpan0, avahi and its own
# system dbus never touch the LAN) AND can commission over BLE. It reaches the
# HOST's BlueZ over a FILTERED D-Bus proxy (see `bluez-proxy` below): the proxy
# socket lives in RUNDIR, so it rides the existing /mt2mqtt-run mount -- no
# separate bind, and the container never sees the raw host system bus. The host's
# bluetoothd does all radio work in init_net; only BTP-over-GATT D-Bus traffic
# crosses. matter-server/run detects a usable BlueZ on that proxy (org.bluez
# owned) and enables BLE; if the proxy isn't running (or host BT is off) it
# degrades cleanly to an operational-only bridge. So: run `make bluez-proxy` in
# another terminal only when you want to commission; otherwise just `make start`.
start:
	mkdir -p '$(RUNDIR)/logs'
	docker run -d --name $(NAME) \
		-v '$(RUNDIR)':/mt2mqtt-run \
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
	mkdir -p '$(RUNDIR)/logs'
	docker run -it --rm --name $(NAME) \
		--security-opt apparmor=unconfined \
		--entrypoint /bin/bash \
		-v '$(RUNDIR)':/mt2mqtt-run \
		--device $(RCP):/dev/ttyACM0 \
		--device /dev/net/tun --cap-add NET_ADMIN \
		mt2mqtt:dev


# Filtered D-Bus proxy exposing ONLY org.bluez to the container, so commissioning
# can drive the host's bluetoothd without handing the container the whole host
# system bus -- which, for a root container, is ~host root (systemd
# StartTransientUnit, UDisks2 mounting host disks, NetworkManager dispatcher
# scripts). --filter default-denies; --talk=org.bluez is the only grant.
#
# Runs in the FOREGROUND as your normal user (no sudo: the logged-in user is
# at_console, the same grant the desktop BT applet uses to scan/connect). Leave
# it running in its own terminal while commissioning; Ctrl-C when done. The
# socket lives in RUNDIR, so it appears in the container at
# /mt2mqtt-run/bluez-proxy.sock via the existing mount -- matter-server/run picks
# it up automatically. When it's not running, `make start` is operational-only.
bluez-proxy:
	mkdir -p '$(RUNDIR)'
	rm -f '$(RUNDIR)/bluez-proxy.sock'
	sudo xdg-dbus-proxy \
		unix:path=/run/dbus/system_bus_socket \
		'$(RUNDIR)/bluez-proxy.sock' \
		--filter --talk=org.bluez

stop:
	docker rm -f $(NAME)

# Attach an interactive shell to the already-running container.
shell:
	docker exec -it $(CONTAINER) bash

# Tail every service log under $(RUNDIR)/logs. The s6 loggers each expose a stable
# <svc>.log symlink to their live file, and the oneshots write <name>.log directly;
# tail -F re-opens across s6-log rotation. These are host-side files (RUNDIR is
# bind-mounted), so this works even when the container is stopped.
logs:
	find '$(RUNDIR)/logs' -name '*.log' -print0 2>/dev/null | xargs -0 -r tail -n 100 -F
