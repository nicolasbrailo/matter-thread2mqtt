#!/usr/bin/env bash
# Container init for the mt2mqtt otbr-agent image.

set -euo pipefail

# TODO move this to a systemd lite manager

# BLE is only needed for commissioning (start-commission sets MT2M_COMMISSION=1
# and shares the host netns so a BT adapter is visible).
if [ "${MT2M_COMMISSION:-}" = "1" ]; then
    echo "[entrypoint] commissioning mode: starting bluetoothd (BLE)..."
    /usr/libexec/bluetooth/bluetoothd -n -d > /mt2mqtt-run/bluetoothd.log 2>&1 &
else
    echo "[entrypoint] not commissioning (MT2M_COMMISSION!=1); skipping bluetoothd"
fi

echo "[entrypoint] setup complete."

# If a command was passed (e.g. `docker run ... bash`), run it after setup.
# Otherwise idle in the foreground so the container stays up for `make shell`.
if [ "$#" -gt 0 ]; then
    exec "$@"
else
    echo "[entrypoint] no command given; idling (use 'make shell' to attach)."
    exec sleep infinity
fi

