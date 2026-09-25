"""Matter nodes -> zigbee2mqtt-style devices.

A Device holds both the published schema (`info`, what goes to mt2m/bridge/devices) and
the adapter that maps z2m properties onto Matter (`props`). Each property is a Cap, which
is the single source of truth for it: it generates its `exposes` entry, reads its value
from matter-server's attribute cache, and validates + executes writes. So the schema and
the dispatcher can't drift apart.

Published entry, one per commissioned node:
{
  "node_id": 1, "friendly_name": "...", "available": true,
  "network": "thread",               # thread | wifi | ethernet | unknown
  "manufacturer": "...", "vendor_id": 4107, "model": "...", "product_id": 1,
  "serial_number": "...", "unique_id": "...", "software_version": "...", "hardware_version": "...",
  "interview_completed": true, "interviewing": false, "last_interview": "...", "interview_version": 6,
  "definition": {"vendor": "...", "model": "...", "description": "Extended Color Light",
                 "supports_ota": true,
                 "exposes": [ ... z2m-style exposes, each tagged with its "endpoint" ... ]},
  "endpoints": {"1": {"device_types": ["Extended Color Light"], "clusters": ["OnOff", ...]}}
}

Values use z2m units, not Matter's raw ones: brightness 0..254, color_temp in mireds,
color as hue 0..360 / saturation 0..100 and/or CIE x/y 0..1, temperature in °C, etc.
"""
import dataclasses
from collections import Counter

from chip.clusters import ClusterObjects
from chip.clusters import Objects as Clusters
from chip.clusters.Types import Nullable

# Cluster / attribute / bitmap ids, from the data model generated from the Matter spec
# (chip.clusters), so a typo is an AttributeError at import instead of a silent None.
DESCRIPTOR = Clusters.Descriptor.id
BASIC_INFO = Clusters.BasicInformation.id
ONOFF = Clusters.OnOff.id
LEVEL = Clusters.LevelControl.id
COLOR = Clusters.ColorControl.id
THREAD_DIAG = Clusters.ThreadNetworkDiagnostics.id
WIFI_DIAG = Clusters.WiFiNetworkDiagnostics.id
ETHERNET_DIAG = Clusters.EthernetNetworkDiagnostics.id
OTA_REQUESTOR = Clusters.OtaSoftwareUpdateRequestor.id
POWER_SOURCE = Clusters.PowerSource.id

DEVICE_TYPE_LIST = Clusters.Descriptor.Attributes.DeviceTypeList.attribute_id
NODE_LABEL = Clusters.BasicInformation.Attributes.NodeLabel.attribute_id
UNIQUE_ID = Clusters.BasicInformation.Attributes.UniqueID.attribute_id
ON_OFF = Clusters.OnOff.Attributes.OnOff.attribute_id
CURRENT_LEVEL = Clusters.LevelControl.Attributes.CurrentLevel.attribute_id
MIN_LEVEL = Clusters.LevelControl.Attributes.MinLevel.attribute_id
MAX_LEVEL = Clusters.LevelControl.Attributes.MaxLevel.attribute_id
COLOR_CAPABILITIES = Clusters.ColorControl.Attributes.ColorCapabilities.attribute_id
COLOR_TEMP_MIREDS = Clusters.ColorControl.Attributes.ColorTemperatureMireds.attribute_id
COLOR_TEMP_MIN = Clusters.ColorControl.Attributes.ColorTempPhysicalMinMireds.attribute_id
COLOR_TEMP_MAX = Clusters.ColorControl.Attributes.ColorTempPhysicalMaxMireds.attribute_id
CURRENT_HUE = Clusters.ColorControl.Attributes.CurrentHue.attribute_id
CURRENT_SATURATION = Clusters.ColorControl.Attributes.CurrentSaturation.attribute_id
CURRENT_X = Clusters.ColorControl.Attributes.CurrentX.attribute_id
CURRENT_Y = Clusters.ColorControl.Attributes.CurrentY.attribute_id
COLOR_MODE = Clusters.ColorControl.Attributes.ColorMode.attribute_id

COLOR_CAP = Clusters.ColorControl.Bitmaps.ColorCapabilitiesBitmap
BAT_OK = Clusters.PowerSource.Enums.BatChargeLevelEnum.kOk
COLOR_MODE_ENUM = Clusters.ColorControl.Enums.ColorModeEnum
# z2m names for Matter's ColorMode
COLOR_MODES = {int(COLOR_MODE_ENUM.kCurrentHueAndCurrentSaturation): "hs",
               int(COLOR_MODE_ENUM.kCurrentXAndCurrentY): "xy",
               int(COLOR_MODE_ENUM.kColorTemperatureMireds): "color_temp"}
OCCUPIED = Clusters.OccupancySensing.Bitmaps.OccupancyBitmap.kOccupied

# Device type ids live in the spec's device library, which chip.clusters doesn't generate,
# so these stay hand-written.
DEVICE_TYPES = {
    14: "Aggregator",
    17: "Power Source",
    19: "Bridged Node",
    21: "Contact Sensor",
    22: "Root Node",
    256: "On/Off Light",
    257: "Dimmable Light",
    259: "On/Off Light Switch",
    263: "Occupancy Sensor",
    266: "On/Off Plug-in Unit",
    267: "Dimmable Plug-in Unit",
    268: "Color Temperature Light",
    269: "Extended Color Light",
    770: "Temperature Sensor",
    773: "Pressure Sensor",
    775: "Humidity Sensor",
}
LIGHT_TYPES = {256, 257, 268, 269}

# BasicInformation attribute -> output key
BASIC_INFO_FIELDS = {
    Clusters.BasicInformation.Attributes.VendorName.attribute_id: "manufacturer",
    Clusters.BasicInformation.Attributes.VendorID.attribute_id: "vendor_id",
    Clusters.BasicInformation.Attributes.ProductName.attribute_id: "model",
    Clusters.BasicInformation.Attributes.ProductID.attribute_id: "product_id",
    Clusters.BasicInformation.Attributes.HardwareVersionString.attribute_id: "hardware_version",
    Clusters.BasicInformation.Attributes.SoftwareVersionString.attribute_id: "software_version",
    Clusters.BasicInformation.Attributes.SerialNumber.attribute_id: "serial_number",
    UNIQUE_ID: "unique_id",
}

# z2m access bits
PUBLISHED = 1
SETTABLE = 2
GETTABLE = 4

# A device's state goes to mt2m/<friendly_name>, so it can't be named like a bridge topic
RESERVED_NAMES = {"bridge", "ping", "discover"}


def cluster_name(cid):
    cls = ClusterObjects.ALL_CLUSTERS.get(cid)
    return cls.__name__ if cls is not None else f"cluster_{cid}"


def attr_name(cid, aid):
    cls = ClusterObjects.ALL_ATTRIBUTES.get(cid, {}).get(aid)
    return cls.__name__ if cls is not None else f"attr_{aid}"


def device_type_name(dt):
    return DEVICE_TYPES.get(dt, f"0x{dt:04x}")


def struct_tag(struct_cls, label):
    """Field tag of a struct field, from the generated descriptor."""
    return next(f.Tag for f in struct_cls.descriptor.Fields if f.Label == label)


DEVICE_TYPE_FIELD = struct_tag(Clusters.Descriptor.Structs.DeviceTypeStruct, "deviceType")


def struct_field(s, tag, name):
    """matter-server hands structs over keyed by field tag (as str); accept names too."""
    if not isinstance(s, dict):
        return None
    for k in (str(tag), tag, name):
        if k in s:
            return s[k]
    return None


def attr_tree(attrs):
    """Flat {"ep/cid/aid": val} -> {ep: {cid: {aid: val}}}"""
    tree = {}
    for key, val in attrs.items():
        try:
            ep, cid, aid = (int(x) for x in key.split("/"))
        except ValueError:
            continue
        tree.setdefault(ep, {}).setdefault(cid, {})[aid] = val
    return tree


def as_number(value):
    """Numbers that arrived as strings -- some clients publish {"brightness": "123"}. Anything
    that doesn't look like a number is handed back untouched, for validate() to reject."""
    if isinstance(value, str):
        for parse in (int, float):
            try:
                return parse(value.strip())
            except ValueError:
                pass
    return value


def check_number(value, vmin=None, vmax=None):
    """Error string, or None if value is a number within [vmin, vmax]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"expected a number, got {value!r}"
    if (vmin is not None and value < vmin) or (vmax is not None and value > vmax):
        return f"{value} out of range [{vmin}, {vmax}]"
    return None


def valid_name(label):
    if not isinstance(label, str) or not label.strip() or label in RESERVED_NAMES:
        return False
    if "+" in label or "#" in label:  # mqtt wildcards, not allowed in a publish topic
        return False
    return label.split("/")[-1] not in ("set", "get")  # mt2m/<name> would look like a request


def json_safe(v):
    """Attribute values as plain json: structs become objects, enums/bitmaps plain ints,
    octet strings hex. Without this a struct would land in mqtt as its python repr."""
    if v is None or isinstance(v, Nullable):
        return None
    if dataclasses.is_dataclass(v):
        return {f.name: json_safe(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, (list, tuple)):
        return [json_safe(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, bool):
        return v
    if isinstance(v, int):  # IntEnum / IntFlag included
        return int(v)
    return v


def dump_node(node):
    """Every attribute the node has, named: {endpoint: {cluster: {attribute: value}}}.

    This is matter-discover.py's output as data, including the clusters the bridge has no
    capability for. Values come from the live cache, names from the generated data model.
    """
    out = {}
    for ep, clusters in sorted(attr_tree(node.node_data.attributes).items()):
        eout = {}
        for cid, attrs in sorted(clusters.items()):
            vals = {}
            for aid in sorted(attrs):
                try:
                    v = node.get_attribute_value(ep, cid, aid)
                except KeyError:
                    v = attrs[aid]  # not in the typed cache (unknown cluster): initial dump value
                vals[attr_name(cid, aid)] = json_safe(v)
            eout[cluster_name(cid)] = vals
        out[str(ep)] = eout
    return out


# --- Capabilities -------------------------------------------------------------

class Cap:
    """One z2m property on one endpoint. Subclasses define how it maps onto Matter."""
    name = None
    access = PUBLISHED | GETTABLE
    attrs = ()  # (cluster, attribute) ids backing the value; re-read from the device on /get

    def __init__(self, ep, cl):
        self.ep = ep
        self.prop = self.name  # Device suffixes it with _<ep> if the name repeats across endpoints

    def paths(self):
        return [f"{self.ep}/{cid}/{aid}" for cid, aid in self.attrs]

    def attr(self, node, cid, aid):
        # The typed cluster objects get live updates; node_data.attributes is only the initial dump
        try:
            v = node.get_attribute_value(self.ep, cid, aid)
        except KeyError:
            return None
        return None if isinstance(v, Nullable) else v

    def base(self, type_):
        return {"type": type_, "name": self.name, "property": self.prop,
                "access": self.access, "endpoint": self.ep}

    def expose(self):
        """List of z2m expose entries for this property."""
        raise NotImplementedError

    def read(self, node):
        """z2m value from matter-server's attribute cache."""
        raise NotImplementedError

    def coerce(self, value):
        """Normalise an incoming json value before validate() sees it."""
        return value

    def validate(self, value):
        """Error string, or None if value can be written."""
        return "read-only"

    async def write(self, client, node_id, value, opts):
        """opts carries the request's options: `transition` (in 1/10 s, as Matter wants it)
        and `with_on_off` (see LevelCap)."""
        raise NotImplementedError


class OnOffCap(Cap):
    name = "state"
    access = PUBLISHED | SETTABLE | GETTABLE
    attrs = [(ONOFF, ON_OFF)]
    COMMANDS = {"ON": Clusters.OnOff.Commands.On,
                "OFF": Clusters.OnOff.Commands.Off,
                "TOGGLE": Clusters.OnOff.Commands.Toggle}

    # Clients send booleans and 1/0 (sometimes as strings) as well as z2m's "ON"/"OFF"
    ALIASES = {True: "ON", False: "OFF", 1: "ON", 0: "OFF", "TRUE": "ON", "FALSE": "OFF"}

    def expose(self):
        return [{**self.base("binary"), "value_on": "ON", "value_off": "OFF", "value_toggle": "TOGGLE"}]

    def coerce(self, value):
        key = as_number(value)
        if isinstance(key, str):
            key = key.strip().upper()
        # bool is an int in python, so True/1 and False/0 land on the same entries
        return self.ALIASES.get(key, key) if not isinstance(key, float) else key

    def read(self, node):
        v = self.attr(node, ONOFF, ON_OFF)
        return None if v is None else ("ON" if v else "OFF")

    def validate(self, value):
        if not isinstance(value, str) or value.upper() not in self.COMMANDS:
            return f"expected ON, OFF or TOGGLE, got {value!r}"
        return None

    async def write(self, client, node_id, value, opts):
        await client.send_device_command(node_id, self.ep, self.COMMANDS[value.upper()]())


class LevelCap(Cap):
    name = "brightness"
    access = PUBLISHED | SETTABLE | GETTABLE
    attrs = [(LEVEL, CURRENT_LEVEL)]

    def __init__(self, ep, cl):
        super().__init__(ep, cl)
        self.vmin = cl[LEVEL].get(MIN_LEVEL) or 1
        self.vmax = cl[LEVEL].get(MAX_LEVEL) or 254

    def expose(self):
        return [{**self.base("numeric"), "value_min": self.vmin, "value_max": self.vmax}]

    def read(self, node):
        return self.attr(node, LEVEL, CURRENT_LEVEL)

    def coerce(self, value):
        return as_number(value)

    def validate(self, value):
        return check_number(value, self.vmin, self.vmax)

    async def write(self, client, node_id, value, opts):
        # WithOnOff: raising the level from 0 also switches the light on. `with_on_off: false`
        # in the request picks plain MoveToLevel, which leaves a switched-off light off (and is
        # then ignored by the device, see below).
        # TODO: a device that reports MinLevel 0 accepts brightness 0, which switches it off
        # through this command. Most report 1, so validate() rejects it there.
        # TODO: optionsMask/optionsOverride 0 means the device ignores this while it's off, so
        # brightness can't be pre-set on an off light. Bit 0 is ExecuteIfOff if we want that.
        cmd = (Clusters.LevelControl.Commands.MoveToLevelWithOnOff if opts.get("with_on_off", True)
               else Clusters.LevelControl.Commands.MoveToLevel)
        await client.send_device_command(node_id, self.ep, cmd(
            level=round(value), transitionTime=opts["transition"], optionsMask=0, optionsOverride=0))


class ColorTempCap(Cap):
    name = "color_temp"
    access = PUBLISHED | SETTABLE | GETTABLE
    attrs = [(COLOR, COLOR_TEMP_MIREDS)]

    def __init__(self, ep, cl):
        super().__init__(ep, cl)
        self.vmin = cl[COLOR].get(COLOR_TEMP_MIN)
        self.vmax = cl[COLOR].get(COLOR_TEMP_MAX)

    def expose(self):
        return [{**self.base("numeric"), "unit": "mired", "value_min": self.vmin, "value_max": self.vmax}]

    def read(self, node):
        return self.attr(node, COLOR, COLOR_TEMP_MIREDS)

    def coerce(self, value):
        return as_number(value)

    def validate(self, value):
        return check_number(value, self.vmin, self.vmax)

    async def write(self, client, node_id, value, opts):
        # TODO: like LevelCap, optionsMask 0 means this is ignored while the light is off
        await client.send_device_command(node_id, self.ep, Clusters.ColorControl.Commands.MoveToColorTemperature(
            colorTemperatureMireds=round(value), transitionTime=opts["transition"],
            optionsMask=0, optionsOverride=0))


class ColorCap(Cap):
    """z2m's `color`: {hue, saturation} and/or {x, y}, whichever the device supports."""
    name = "color"
    access = PUBLISHED | SETTABLE | GETTABLE
    XY_MAX = 0xFEFF  # Matter CurrentX/CurrentY are x * 65536, capped here

    def __init__(self, ep, cl):
        super().__init__(ep, cl)
        caps = cl[COLOR].get(COLOR_CAPABILITIES) or 0
        self.hs = bool(caps & COLOR_CAP.kHueSaturation)
        self.xy = bool(caps & COLOR_CAP.kXy)
        self.attrs = ([(COLOR, CURRENT_HUE), (COLOR, CURRENT_SATURATION)] if self.hs else []) + \
                     ([(COLOR, CURRENT_X), (COLOR, CURRENT_Y)] if self.xy else [])

    def feature(self, name, vmin, vmax):
        return {"type": "numeric", "name": name, "property": name, "access": self.access,
                "value_min": vmin, "value_max": vmax}

    def expose(self):
        out = []
        if self.hs:
            out.append({**self.base("composite"), "name": "color_hs",
                        "features": [self.feature("hue", 0, 360), self.feature("saturation", 0, 100)]})
        if self.xy:
            out.append({**self.base("composite"), "name": "color_xy",
                        "features": [self.feature("x", 0, 1), self.feature("y", 0, 1)]})
        return out

    def read(self, node):
        out = {}
        if self.hs:
            h, s = self.attr(node, COLOR, CURRENT_HUE), self.attr(node, COLOR, CURRENT_SATURATION)
            if h is not None:
                out["hue"] = round(h * 360 / 254)
            if s is not None:
                out["saturation"] = round(s * 100 / 254)
        if self.xy:
            x, y = self.attr(node, COLOR, CURRENT_X), self.attr(node, COLOR, CURRENT_Y)
            if x is not None:
                out["x"] = round(x / 65536, 4)
            if y is not None:
                out["y"] = round(y / 65536, 4)
        return out or None

    def coerce(self, value):
        if isinstance(value, dict):
            return {k: as_number(v) for k, v in value.items()}
        return value

    def validate(self, value):
        if isinstance(value, dict):
            if self.hs and "hue" in value and "saturation" in value:
                return check_number(value["hue"], 0, 360) or check_number(value["saturation"], 0, 100)
            if self.xy and "x" in value and "y" in value:
                return check_number(value["x"], 0, 1) or check_number(value["y"], 0, 1)
        wanted = " or ".join(f for f, ok in (("{hue, saturation}", self.hs), ("{x, y}", self.xy)) if ok)
        return f"expected {wanted}, got {value!r}"

    async def write(self, client, node_id, value, opts):
        # TODO: like LevelCap, optionsMask 0 means this is ignored while the light is off
        if self.hs and "hue" in value and "saturation" in value:
            cmd = Clusters.ColorControl.Commands.MoveToHueAndSaturation(
                hue=round(value["hue"] * 254 / 360), saturation=round(value["saturation"] * 254 / 100),
                transitionTime=opts["transition"], optionsMask=0, optionsOverride=0)
        else:
            cmd = Clusters.ColorControl.Commands.MoveToColor(
                colorX=min(round(value["x"] * 65536), self.XY_MAX),
                colorY=min(round(value["y"] * 65536), self.XY_MAX),
                transitionTime=opts["transition"], optionsMask=0, optionsOverride=0)
        await client.send_device_command(node_id, self.ep, cmd)


class ColorModeEnumCap(Cap):
    """z2m's `color_mode`: which of the colour modes the device is currently in. Read-only --
    it changes as a side effect of setting color_temp or color."""
    name = "color_mode"
    attrs = [(COLOR, COLOR_MODE)]

    def __init__(self, ep, cl):
        super().__init__(ep, cl)
        caps = cl[COLOR].get(COLOR_CAPABILITIES) or 0
        self.values = [name for bit, name in ((COLOR_CAP.kHueSaturation, "hs"),
                                              (COLOR_CAP.kXy, "xy"),
                                              (COLOR_CAP.kColorTemperature, "color_temp"))
                       if caps & bit]

    def expose(self):
        return [{**self.base("enum"), "values": self.values}]

    def read(self, node):
        v = self.attr(node, COLOR, COLOR_MODE)
        return None if v is None else COLOR_MODES.get(int(v))


class SensorCap(Cap):
    """Read-only value from one attribute of a sensor cluster."""

    def __init__(self, ep, cl, name, attribute, unit, conv, binary):
        self.name = name
        super().__init__(ep, cl)
        self.cid, self.aid = attribute.cluster_id, attribute.attribute_id
        self.unit, self.conv, self.binary = unit, conv, binary
        self.attrs = [(self.cid, self.aid)]

    def expose(self):
        e = self.base("binary" if self.binary else "numeric")
        if self.binary:
            e.update(value_on=True, value_off=False)
        if self.unit:
            e["unit"] = self.unit
        return [e]

    def read(self, node):
        v = self.attr(node, self.cid, self.aid)
        return None if v is None else self.conv(v)


SENSORS = [
    # name, attribute, unit, raw Matter value -> z2m value, binary
    # The units/scaling are spec conventions; chip.clusters doesn't carry them as data.
    ("temperature", Clusters.TemperatureMeasurement.Attributes.MeasuredValue, "°C", lambda v: v / 100, False),
    ("humidity", Clusters.RelativeHumidityMeasurement.Attributes.MeasuredValue, "%", lambda v: v / 100, False),
    # Matter: 0.1 kPa == 1 hPa
    ("pressure", Clusters.PressureMeasurement.Attributes.MeasuredValue, "hPa", lambda v: v, False),
    ("illuminance", Clusters.IlluminanceMeasurement.Attributes.MeasuredValue, "lx",
     lambda v: round(10 ** ((v - 1) / 10000), 1) if v else 0, False),
    ("occupancy", Clusters.OccupancySensing.Attributes.Occupancy, None, lambda v: bool(v & OCCUPIED), True),
    ("contact", Clusters.BooleanState.Attributes.StateValue, None, lambda v: bool(v), True),
    # Matter reports battery charge in half percent; z2m publishes plain percent
    ("battery", Clusters.PowerSource.Attributes.BatPercentRemaining, "%", lambda v: v / 2, False),
    ("battery_low", Clusters.PowerSource.Attributes.BatChargeLevel, None, lambda v: int(v) != BAT_OK, True),
]
BATTERY = {"battery", "battery_low"}


def sensor_caps(ep, cl, only=None):
    """Sensor caps for the attributes this endpoint actually reports. A mains-powered device has
    PowerSource without any Bat* attribute, so presence of the cluster alone isn't enough."""
    return [SensorCap(ep, cl, name, attribute, unit, conv, binary)
            for name, attribute, unit, conv, binary in SENSORS
            if (only is None or name in only)
            and attribute.attribute_id in cl.get(attribute.cluster_id, {})]


def endpoint_caps(ep, cl, device_types):
    """-> (kind, actuator caps, sensor caps). Actuators get grouped as a z2m light/switch."""
    act = []
    if ONOFF in cl:
        act.append(OnOffCap(ep, cl))
        if LEVEL in cl:
            act.append(LevelCap(ep, cl))
        if COLOR in cl:
            caps = cl[COLOR].get(COLOR_CAPABILITIES) or 0
            if caps & COLOR_CAP.kColorTemperature:
                act.append(ColorTempCap(ep, cl))
            if caps & (COLOR_CAP.kHueSaturation | COLOR_CAP.kXy):
                act.append(ColorCap(ep, cl))
            act.append(ColorModeEnumCap(ep, cl))
    is_light = LEVEL in cl or COLOR in cl or LIGHT_TYPES & set(device_types)
    return ("light" if is_light else "switch"), act, sensor_caps(ep, cl)


# --- Device -------------------------------------------------------------------

class Device:
    def __init__(self, node):
        self.node = node
        self.node_id = node.node_id
        tree = attr_tree(node.node_data.attributes)
        root = tree.get(0, {})
        basic = root.get(BASIC_INFO, {})

        label = basic.get(NODE_LABEL)
        self.friendly_name = label if valid_name(label) else f"matter_{self.node_id}"
        self.unique_id = basic.get(UNIQUE_ID)

        endpoints = {}
        groups = []  # (ep, kind, actuators, sensors)
        device_types = []  # names, non-root endpoints, for definition.description
        for ep in sorted(tree):
            cl = tree[ep]
            dts = [struct_field(d, DEVICE_TYPE_FIELD, "deviceType")
                   for d in cl.get(DESCRIPTOR, {}).get(DEVICE_TYPE_LIST) or []]
            dts = [dt for dt in dts if dt is not None]
            endpoints[str(ep)] = {
                "device_types": [device_type_name(dt) for dt in dts],
                "clusters": [cluster_name(cid) for cid in sorted(cl)],
            }
            if ep != 0:
                groups.append((ep, *endpoint_caps(ep, cl, dts)))
                device_types.extend(endpoints[str(ep)]["device_types"])
            else:
                # PowerSource usually sits on the root endpoint, and battery is a device-level
                # property in z2m, so take just that from endpoint 0
                groups.append((ep, None, [], sensor_caps(ep, cl, only=BATTERY)))

        # Like z2m, a property name repeated across endpoints gets suffixed: state_1, state_2
        caps = [c for _, _, act, sens in groups for c in act + sens]
        counts = Counter(c.name for c in caps)
        for c in caps:
            if counts[c.name] > 1:
                c.prop = f"{c.name}_{c.ep}"
        self.props = {c.prop: c for c in caps}

        exposes = []
        for ep, kind, act, sens in groups:
            if act:
                exposes.append({"type": kind, "endpoint": ep,
                                "features": [e for c in act for e in c.expose()]})
            exposes.extend(e for c in sens for e in c.expose())

        if THREAD_DIAG in root:
            network = "thread"
        elif WIFI_DIAG in root:
            network = "wifi"
        elif ETHERNET_DIAG in root:
            network = "ethernet"
        else:
            network = "unknown"

        # Matter interviews a node (reads its whole data model) right after commissioning, but
        # matter-server only hands a node to clients once that's done, so from here it's always
        # finished -- there's no "interviewing" state to report. Hardcoded for z2m compatibility;
        # last_interview / interview_version below are the real data.
        self.info = {"node_id": self.node_id, "friendly_name": self.friendly_name,
                     "available": node.available, "network": network,
                     "interview_completed": True, "interviewing": False,
                     "last_interview": node.node_data.last_interview,
                     "interview_version": node.node_data.interview_version}
        for aid, key in BASIC_INFO_FIELDS.items():
            if aid in basic:
                self.info[key] = basic[aid]
        # z2m keeps what a device *is* (and can do) under `definition`, separate from the
        # per-node facts above. vendor/model repeat manufacturer/model, as they do in z2m.
        self.info["definition"] = {
            "vendor": self.info.get("manufacturer"),
            "model": self.info.get("model"),
            "description": ", ".join(dict.fromkeys(device_types)) or None,
            "supports_ota": OTA_REQUESTOR in root,
            "exposes": exposes,
        }
        self.info["endpoints"] = endpoints

    def state(self):
        """Current z2m state, from matter-server's (live-updated) attribute cache."""
        return {prop: cap.read(self.node) for prop, cap in self.props.items()}
