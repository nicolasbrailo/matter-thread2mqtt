#!/usr/bin/env python3
"""Throwaway client for the headless python-matter-server WS API.

Run inside the container (the run dir is bind-mounted at /mt2mqtt-run):
    python /mt2mqtt-run/matter-ws-check.py

Connects, syncs full state, and prints the server info + commissioned nodes.
Also pulls the live Thread dataset straight from otbr-agent (via ot-ctl) and
hands it to matter-server, so the controller has the credentials it needs to
push to a device at commission time.
"""

import asyncio
import re
import subprocess

import aiohttp
from matter_server.client import MatterClient

URL = "ws://127.0.0.1:5580/ws"


def fetch_thread_dataset() -> str:
    # TODO
    return "0e080000000000010000000300001a4a0300000c35060004001fffe00208ce1b1e6984e805000708fd6d3415bd5ced9e0510294a58aa6b7baabd2149a4faa6f8db55030f4f70656e5468726561642d31366465010216de0410e175d202043a12a875d6045e814ccdb10c0402a0f7f8"
    """Return the active Thread operational dataset as hex, from otbr-agent.

    ot-ctl is a thin D-Bus client, so this only works while otbr-agent is
    running and the mesh is up. Output is the hex blob on one line followed
    by "Done"; we pick the hex line out.
    """
    # Equivalent to `echo "dataset active -x" | ot-ctl`, but passing the
    # command as args avoids piping quirks.
    out = subprocess.run(
        ["ot-ctl", "dataset", "active", "-x"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in out.splitlines():
        line = line.strip()
        if re.fullmatch(r"[0-9a-fA-F]{20,}", line):
            return line
    raise RuntimeError(f"no dataset hex found in ot-ctl output:\n{out}")


async def main() -> None:
    dataset = fetch_thread_dataset()
    print(f"thread dataset: {dataset}")

    async with aiohttp.ClientSession() as session:
        client = MatterClient(URL, session)
        await client.connect()
        print("server_info:", client.server_info)

        # start_listening pulls the full node dump and then streams events.
        # We only need the one-shot sync here, so wait for init and stop.
        init = asyncio.Event()
        listen_task = asyncio.create_task(client.start_listening(init))
        await init.wait()

        nodes = client.get_nodes()
        print(f"nodes ({len(nodes)}):")
        for node in nodes:
            print(f"  - node_id={node.node_id} available={node.available}")

        # Hand matter-server the Thread dataset it will push to new devices.
        # (Verify the method name against the installed client if this errors:
        #  grep -rn "def set_thread" .../matter_server/client/client.py)
        await client.set_thread_operational_dataset(dataset)
        print("thread dataset pushed to matter-server")

        # --- commissioning (uncomment when ready, with a real MT: code) -----
        # (BLE + Thread), device freshly reset and BLE advertising:
        print("WAITING FOR DEVICE NOW....")
        #await client.commission_with_code("04554434631", network_only=False)
        await client.commission_with_code("25417509817", network_only=False)
        print("DEVICE HAS BEEN WAITED")

        listen_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
