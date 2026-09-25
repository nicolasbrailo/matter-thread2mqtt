#!/usr/bin/env python3
"""Matter -> MQTT bridge, zigbee2mqtt style.

  mt2m/ping                 {}                   -> mt2m {"pong":{}}
  mt2m/discover             {}                   -> mt2m/bridge/devices (retained) + every device's state
  mt2m/bridge/request/<subject>                  -> mt2m/bridge/response/<subject>, z2m style:
                            {"status":"ok","data":{...}} or {"status":"error","error":"..."},
                            echoing "transaction" from the request if it had one.
                            subjects: device/dump {"device":"<device>"} -- every attribute the
                            node has, named (what matter-discover.py used to print)
  mt2m/<device>/set         {"state":"ON", "brightness":100, "transition":1.5}
                            options: transition (s), with_on_off (false = don't switch on
                            when setting brightness)
  mt2m/<device>/get         {"state":""}  ({} reads everything) -> mt2m/<device>
  mt2m/<device>                                  <- state, published on every change
  mt2m/<device>/availability                     <- {"state":"online"|"offline"} (retained)
  mt2m/bridge/state                              <- the bridge itself, offline via the mqtt will

<device> is a friendly_name, unique_id or node_id (tried in that order). Errors go to
mt2m as {"error": {...}}.

Threads: paho runs on the main thread; all Matter work (and the device table) lives on
the matter loop, so on_message only parses the topic and hands requests over.
"""
import asyncio
import json

import paho.mqtt.client as mqtt
from matter_server.common.models import EventType

from devices import Device, as_number, dump_node, SETTABLE, GETTABLE
from matter import Matter

SOCKET = "/mt2mqtt-run/mqtt.sock"
TOPIC = "mt2m"
DEVICES_TOPIC = TOPIC + "/bridge/devices"
BRIDGE_STATE_TOPIC = TOPIC + "/bridge/state"
STATE_DEBOUNCE = 0.2  # s; a transition fires a burst of attribute updates, publish once


def log(msg):
    print(f"[bridge] {msg}", flush=True)


class Bridge:
    """Runs on the matter loop, except for the constructor."""

    def __init__(self, mqttc):
        self.mqtt = mqttc
        self.devices = {}      # node_id -> Device
        self._attr_unsubs = {}  # node_id -> unsubscribe fn for its attribute updates
        self._pending_state = set()
        self.matter = Matter(on_connect=self.on_matter_connect,
                             on_disconnect=self.on_matter_disconnect)

    def publish(self, topic, payload, retain=False):
        self.mqtt.publish(topic, json.dumps(payload, default=str), retain=retain)

    def error(self, request, msg):
        log(f"{request}: {msg}")
        self.publish(TOPIC, {"error": {"request": request, "msg": msg}})

    # --- matter events --------------------------------------------------------

    def on_matter_connect(self, client):
        self._attr_unsubs = {}  # old client's subscriptions died with it
        for ev in (EventType.NODE_ADDED, EventType.NODE_UPDATED, EventType.NODE_REMOVED):
            client.subscribe_events(lambda *_: self.rebuild(), event_filter=ev)
        self.rebuild()

    def rebuild(self):
        """Rebuild the device table from matter-server's cache and publish it."""
        client = self.matter.client
        self.devices = {n.node_id: Device(n) for n in client.get_nodes()}
        # Attribute-update callbacks don't say which node changed, so subscribe per node
        for node_id in list(self._attr_unsubs):
            if node_id not in self.devices:
                self._attr_unsubs.pop(node_id)()
        for node_id in self.devices:
            if node_id not in self._attr_unsubs:
                self._attr_unsubs[node_id] = client.subscribe_events(
                    lambda *_, nid=node_id: self.schedule_state(nid),
                    event_filter=EventType.ATTRIBUTE_UPDATED, node_filter=node_id)
        # TODO: a removed node leaves its retained state/availability topics behind
        log(f"{len(self.devices)} device(s): {', '.join(d.friendly_name for d in self.devices.values())}")
        self.publish(DEVICES_TOPIC, [d.info for d in self.devices.values()], retain=True)
        for dev in self.devices.values():
            self.publish_availability(dev)
            self.publish_state(dev)

    def on_matter_disconnect(self):
        """matter-server is gone, so we no longer know anything about any device."""
        for dev in self.devices.values():
            self.publish_availability(dev, online=False)

    def schedule_state(self, node_id):
        if node_id not in self._pending_state:
            self._pending_state.add(node_id)
            asyncio.get_running_loop().call_later(STATE_DEBOUNCE, self._flush_state, node_id)

    def _flush_state(self, node_id):
        self._pending_state.discard(node_id)
        if dev := self.devices.get(node_id):
            self.publish_state(dev)

    def publish_availability(self, dev, online=None):
        """z2m-style availability. A node is `available` while matter-server can reach it."""
        if online is None:
            online = dev.node.available
        self.publish(f"{TOPIC}/{dev.friendly_name}/availability",
                     {"state": "online" if online else "offline"}, retain=True)

    def publish_state(self, dev):
        self.publish(f"{TOPIC}/{dev.friendly_name}", dev.state())

    # --- requests -------------------------------------------------------------

    def resolve(self, name):
        # TODO: two nodes can carry the same NodeLabel; first match wins, silently
        for key in (lambda d: d.friendly_name, lambda d: d.unique_id, lambda d: str(d.node_id)):
            for dev in self.devices.values():
                if key(dev) == name:
                    return dev
        return None

    async def discover(self):
        if self.matter.client is None:
            return self.error("discover", "matter-server not connected")
        self.rebuild()

    # --- bridge/request -> bridge/response ------------------------------------

    def respond(self, subject, transaction, data=None, error=None):
        msg = {"status": "error" if error else "ok"}
        if error:
            msg["error"] = error
        else:
            msg["data"] = {} if data is None else data
        if transaction is not None:
            msg["transaction"] = transaction
        self.publish(f"{TOPIC}/bridge/response/{subject}", msg)

    async def request(self, subject, payload):
        transaction = payload.get("transaction") if isinstance(payload, dict) else None
        try:
            if not isinstance(payload, dict):
                raise ValueError("payload must be a json object")
            handler = REQUESTS.get(subject)
            if handler is None:
                raise ValueError(f"unknown request {subject!r}; have {sorted(REQUESTS)}")
            self.respond(subject, transaction, data=await handler(self, payload))
        except Exception as e:
            log(f"bridge/request/{subject}: {e!r}")
            self.respond(subject, transaction, error=repr(e))

    async def req_device_dump(self, payload):
        """Every attribute of one node, for debugging a device the schema doesn't cover."""
        if self.matter.client is None:
            raise RuntimeError("matter-server not connected")
        name = payload.get("device")
        dev = self.resolve(name) if name is not None else None
        if dev is None:
            raise ValueError(f"unknown device {name!r}")
        return {"node_id": dev.node_id, "friendly_name": dev.friendly_name,
                "endpoints": dump_node(dev.node)}

    async def device_request(self, name, op, payload):
        request = f"{name}/{op}"
        if self.matter.client is None:
            return self.error(request, "matter-server not connected")
        dev = self.resolve(name)
        if dev is None:
            return self.error(request, f"unknown device {name!r}")
        if not isinstance(payload, dict):
            return self.error(request, "payload must be a json object")
        try:
            if op == "set":
                await self.set(request, dev, payload)
            else:
                await self.get(request, dev, payload)
        except Exception as e:
            self.error(request, repr(e))

    async def set(self, request, dev, payload):
        payload = dict(payload)
        transition = as_number(payload.pop("transition", 0))  # seconds, like z2m
        with_on_off = payload.pop("with_on_off", True)
        # TODO: transition doesn't apply to `state`: Matter's On()/Off() take no transition time,
        # so {"state":"OFF","transition":3} switches off instantly while brightness/colour fade.
        # z2m fades the level to 0 and then switches off; we could do the same.
        if isinstance(transition, bool) or not isinstance(transition, (int, float)) or transition < 0:
            return self.error(request, f"transition: expected seconds >= 0, got {transition!r}")
        if not isinstance(with_on_off, bool):
            return self.error(request, f"with_on_off: expected true or false, got {with_on_off!r}")
        opts = {"transition": round(transition * 10), "with_on_off": with_on_off}
        # Validate everything before touching the device
        writes = []
        for prop, value in payload.items():
            cap = dev.props.get(prop)
            if cap is None:
                return self.error(request, f"unknown property {prop!r}; have {sorted(dev.props)}")
            if not cap.access & SETTABLE:
                return self.error(request, f"{prop}: read-only")
            value = cap.coerce(value)
            if err := cap.validate(value):
                return self.error(request, f"{prop}: {err}")
            writes.append((cap, value))
        writes = self.order_writes(request, dev, writes)
        if writes is None:
            return
        for cap, value in writes:
            await cap.write(self.matter.client, dev.node_id, value, opts)
        # New state gets published when the device reports the attribute changes

    def order_writes(self, request, dev, writes):
        """Sort out properties that fight each other, per endpoint. None if the request is bad.

        - state OFF wins: brightness goes out as MoveToLevelWithOnOff, which would switch the
          light straight back on. {"state":"OFF","brightness":10} must just turn it off.
        - state ON goes first: ColorControl/LevelControl commands are dropped by the device while
          it's off (we don't set ExecuteIfOff), so colour set before ON would be lost.
        - state TOGGLE with anything else is ambiguous -- we can't know what it'll toggle into.
        - color_temp and color are two different colour modes; whichever ran last would win.
        """
        by_ep = {}
        for cap, value in writes:
            by_ep.setdefault(cap.ep, []).append((cap, value))

        ordered = []
        for ep, group in by_ep.items():
            names = [c.name for c, _ in group]
            if "color_temp" in names and "color" in names:
                self.error(request, f"endpoint {ep}: color_temp and color are different colour modes, set one")
                return None
            state = next((v.upper() for c, v in group if c.name == "state"), None)
            others = [c.prop for c, _ in group if c.name != "state"]
            if state and others:
                if state == "TOGGLE":
                    self.error(request, f"endpoint {ep}: can't combine state TOGGLE with {others}")
                    return None
                if state == "OFF":
                    log(f"{request}: endpoint {ep} turning off, ignoring {others}")
                    group = [(c, v) for c, v in group if c.name == "state"]
                else:
                    group.sort(key=lambda cv: cv[0].name != "state")  # ON first
            ordered.extend(group)
        return ordered

    async def get(self, request, dev, payload):
        props = list(payload) or list(dev.props)
        paths = []
        for prop in props:
            cap = dev.props.get(prop)
            if cap is None:
                return self.error(request, f"unknown property {prop!r}; have {sorted(dev.props)}")
            if not cap.access & GETTABLE:
                return self.error(request, f"{prop}: not readable")
            paths.extend(p for p in cap.paths() if p not in paths)
        # Live read from the device; refresh_attribute also updates matter-server's cache
        for path in paths:
            await self.matter.client.refresh_attribute(dev.node_id, path)
        self.publish_state(dev)


REQUESTS = {"device/dump": Bridge.req_device_dump}

bridge = None


def on_connect(client, userdata, flags, reason_code, properties):
    global bridge
    print(f"connected ({reason_code}), subscribing to {TOPIC + '/#'!r}", flush=True)
    client.subscribe(TOPIC + "/#")
    client.publish(BRIDGE_STATE_TOPIC, json.dumps({"state": "online"}), retain=True)
    if bridge is None:  # only once mqtt is up, so its first publishes aren't dropped
        bridge = Bridge(client)


def on_message(client, userdata, msg):
    rest = msg.topic.split("/")[1:]
    is_request = len(rest) >= 3 and rest[:2] == ["bridge", "request"]
    is_device = len(rest) >= 2 and rest[-1] in ("set", "get")
    if not (is_request or is_device or rest in (["ping"], ["discover"])):
        return  # our own state/devices/response publications
    print(f"rx {msg.topic} {msg.payload!r}", flush=True)
    raw = msg.payload.decode(errors="replace").strip()
    try:
        payload = json.loads(raw) if raw else {}  # an empty payload is an empty request
    except ValueError:
        print(f"ignoring {msg.topic}: payload is not json", flush=True)
        return
    if rest == ["ping"]:
        client.publish(TOPIC, json.dumps({"pong": {}}))
    elif rest == ["discover"]:
        bridge.matter.submit(bridge.discover())
    elif is_request:
        bridge.matter.submit(bridge.request("/".join(rest[2:]), payload))
    else:
        bridge.matter.submit(bridge.device_request("/".join(rest[:-1]), rest[-1], payload))


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="unix")
    client.on_connect = on_connect
    client.on_message = on_message
    # Last will: the broker publishes this for us if we die or drop off
    client.will_set(BRIDGE_STATE_TOPIC, json.dumps({"state": "offline"}), retain=True)
    # paho ignores the port for unix sockets, but rejects port<=0
    client.connect(SOCKET, 1883)
    client.loop_forever()
