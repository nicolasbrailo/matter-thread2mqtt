#!/usr/bin/env python3
"""Discover commissioned nodes and the clusters/attributes you can control.

Run inside the container:
    python /mt2mqtt-run/matter-discover.py

For each node and endpoint, prints the clusters present, every attribute's
current value, and (for the clusters that take control commands) the commands
worth knowing. Use it to find the right NODE_ID / ENDPOINT for
matter-light-ctl.py.
"""

import asyncio

import aiohttp
from matter_server.client import MatterClient

URL = "ws://127.0.0.1:5580/ws"

# Clusters you typically *control* on a light, with handy commands. The id ->
# name fallback also covers the case where chip's registry lookup fails.
CONTROLLABLE = {
    6: ("OnOff", ["On()", "Off()", "Toggle()"]),
    8: (
        "LevelControl",
        ["MoveToLevel(level=0..254, transitionTime=<1/10s>)", "MoveToLevelWithOnOff(...)"],
    ),
    768: (
        "ColorControl",
        ["MoveToColorTemperature(...)", "MoveToHueAndSaturation(...)"],
    ),
}


def cluster_name(cid: int) -> str:
    try:
        from chip.clusters import ClusterObjects

        cls = ClusterObjects.ALL_CLUSTERS.get(cid)
        if cls is not None:
            return cls.__name__
    except Exception:
        pass
    if cid in CONTROLLABLE:
        return CONTROLLABLE[cid][0]
    return f"cluster_{cid}"


def attr_name(cid: int, aid: int) -> str:
    try:
        from chip.clusters import ClusterObjects

        acls = ClusterObjects.ALL_ATTRIBUTES.get(cid, {}).get(aid)
        if acls is not None:
            return acls.__name__
    except Exception:
        pass
    return f"attr_{aid}"


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = MatterClient(URL, session)
        await client.connect()

        init = asyncio.Event()
        listen_task = asyncio.create_task(client.start_listening(init))
        await init.wait()

        nodes = client.get_nodes()
        print(f"{len(nodes)} node(s) commissioned\n")

        for node in nodes:
            print(f"=== Node {node.node_id}  available={node.available} ===")

            # Group the flat "endpoint/cluster/attribute" attribute dict into a
            # tree: {endpoint: {cluster: {attr: value}}}. The dict lives on the
            # node's MatterNodeData (older/newer clients differ on whether it's
            # also surfaced directly on the node), so fall back accordingly.
            node_attrs = getattr(node, "attributes", None)
            if node_attrs is None:
                node_attrs = node.node_data.attributes
            tree: dict[int, dict[int, dict[int, object]]] = {}
            for key, val in node_attrs.items():
                try:
                    ep, cid, aid = (int(x) for x in key.split("/"))
                except ValueError:
                    continue  # skip non-numeric keys, if any
                tree.setdefault(ep, {}).setdefault(cid, {})[aid] = val

            for ep in sorted(tree):
                print(f"  endpoint {ep}:")
                for cid in sorted(tree[ep]):
                    cname = cluster_name(cid)
                    tag = "   <-- controllable" if cid in CONTROLLABLE else ""
                    print(f"    [{cid}] {cname}{tag}")
                    for aid in sorted(tree[ep][cid]):
                        print(f"        {aid:>3}  {attr_name(cid, aid)} = {tree[ep][cid][aid]}")
                    if cid in CONTROLLABLE:
                        for cmd in CONTROLLABLE[cid][1]:
                            print(f"          cmd: clusters.{cname}.Commands.{cmd}")
            print()

        listen_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
