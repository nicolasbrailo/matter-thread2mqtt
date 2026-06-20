#!/usr/bin/env python3
"""Hardcoded-command control client for one commissioned Matter light.

Run inside the container (run dir is bind-mounted at /mt2mqtt-run):
    python /mt2mqtt-run/matter-light-ctl.py

No argv parsing on purpose: edit the CONFIG block below, then run. Needs
matter-server running (ws://127.0.0.1:5580) and otbr-agent up with the mesh
attached, so the controller can reach the light over Thread.
"""

import asyncio
import sys

import aiohttp
from chip.clusters import Objects as clusters
from matter_server.client import MatterClient

# ---- CONFIG: edit these, then run ------------------------------------------
URL = "ws://127.0.0.1:5580/ws"
NODE_ID = 1        # the node id you commissioned
ENDPOINT = 1       # a light is usually on endpoint 1 (run matter-discover.py to confirm)
CMD = "off"         # one of: state | on | off | toggle | level | ctemp | color
LEVEL = 50        # 0..254, only used when CMD == "level"
MIREDS = 555       # 153..555, only used when CMD == "ctemp" (low=cool, high=warm)
HUE = 210            # 0..254, only used when CMD == "color"
SAT = 254          # 0..254, only used when CMD == "color"
TRANSITION = 30    # 1/10 s fade, used for level / ctemp / color (10 = 1.0 s)
# ----------------------------------------------------------------------------

ONOFF_ATTR = f"{ENDPOINT}/6/0"     # OnOff cluster 6, attr OnOff 0          -> bool
LEVEL_ATTR = f"{ENDPOINT}/8/0"     # LevelControl cluster 8, CurrentLevel   -> 0..254
COLORMODE_ATTR = f"{ENDPOINT}/768/8"  # ColorControl ColorMode  -> 0 hue/sat, 1 xy, 2 ctemp
CTEMP_ATTR = f"{ENDPOINT}/768/7"   # ColorControl ColorTemperatureMireds   -> 153..555
HUE_ATTR = f"{ENDPOINT}/768/0"     # ColorControl CurrentHue                -> 0..254
SAT_ATTR = f"{ENDPOINT}/768/1"     # ColorControl CurrentSaturation         -> 0..254


async def show_state(client: MatterClient) -> None:
    """Live-read on/off + brightness straight from the device."""
    on = await client.read_attribute(NODE_ID, ONOFF_ATTR)
    lvl = await client.read_attribute(NODE_ID, LEVEL_ATTR)
    print(f"node {NODE_ID} ep {ENDPOINT}: on={on} level={lvl}")


async def show_color(client: MatterClient) -> None:
    """Live-read the ColorControl state (only meaningful on a color bulb)."""
    mode = await client.read_attribute(NODE_ID, COLORMODE_ATTR)
    ctemp = await client.read_attribute(NODE_ID, CTEMP_ATTR)
    hue = await client.read_attribute(NODE_ID, HUE_ATTR)
    sat = await client.read_attribute(NODE_ID, SAT_ATTR)
    print(f"  color: mode={mode} mireds={ctemp} hue={hue} sat={sat}")


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = MatterClient(URL, session)
        await client.connect()

        # start_listening pulls the full node dump then streams events; we just
        # need it initialised so the node cache exists.
        init = asyncio.Event()
        listen_task = asyncio.create_task(client.start_listening(init))
        await init.wait()

        if CMD == "state":
            await show_state(client)
            await show_color(client)

        elif CMD == "on":
            await client.send_device_command(NODE_ID, ENDPOINT, clusters.OnOff.Commands.On())
            await show_state(client)

        elif CMD == "off":
            await client.send_device_command(NODE_ID, ENDPOINT, clusters.OnOff.Commands.Off())
            await show_state(client)

        elif CMD == "toggle":
            await client.send_device_command(NODE_ID, ENDPOINT, clusters.OnOff.Commands.Toggle())
            await show_state(client)

        elif CMD == "level":
            # WithOnOff: raising the level from 0 also switches the light on.
            await client.send_device_command(
                NODE_ID,
                ENDPOINT,
                clusters.LevelControl.Commands.MoveToLevelWithOnOff(
                    level=LEVEL,
                    transitionTime=TRANSITION,
                    optionsMask=0,
                    optionsOverride=0,
                ),
            )
            await asyncio.sleep(max(TRANSITION / 10 + 0.2, 0.5))  # let the fade finish
            await show_state(client)

        elif CMD == "ctemp":
            await client.send_device_command(
                NODE_ID,
                ENDPOINT,
                clusters.ColorControl.Commands.MoveToColorTemperature(
                    colorTemperatureMireds=MIREDS,
                    transitionTime=TRANSITION,
                    optionsMask=0,
                    optionsOverride=0,
                ),
            )
            await asyncio.sleep(max(TRANSITION / 10 + 0.2, 0.5))
            await show_color(client)

        elif CMD == "color":
            await client.send_device_command(
                NODE_ID,
                ENDPOINT,
                clusters.ColorControl.Commands.MoveToHueAndSaturation(
                    hue=HUE,
                    saturation=SAT,
                    transitionTime=TRANSITION,
                    optionsMask=0,
                    optionsOverride=0,
                ),
            )
            await asyncio.sleep(max(TRANSITION / 10 + 0.2, 0.5))
            await show_color(client)

        else:
            print(
                f"unknown CMD: {CMD!r} "
                "(use: state | on | off | toggle | level | ctemp | color)"
            )

        listen_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
