"""Low-level SNMP helpers and MIB parsing for the switch dashboard.

The dashboard deliberately uses numeric OIDs so it works without a local MIB
tree.  Standard MIBs are preferred, with a small compatibility shim for the
lab simulator's ENTITY-MIB column layout.
"""

import re
import shutil
import subprocess
import time

SNMP_WALK = shutil.which("snmpbulkwalk") or shutil.which("snmpwalk") or "snmpwalk"
SNMP_TIMEOUT = 2
SNMP_RETRIES = 0

SENSOR_TYPES = {
    1: "other", 2: "unknown", 3: "voltsAC", 4: "voltsDC", 5: "amperes",
    6: "watts", 7: "hertz", 8: "celsius", 9: "percentRH", 10: "rpm",
    11: "cm", 12: "meters", 13: "liters", 14: "kg", 15: "grams",
    16: "coulombs", 38: "dBm", 39: "dB",
}

ENTITY_CLASSES = {
    1: "other", 2: "unknown", 3: "chassis", 4: "backplane", 5: "container",
    6: "powerSupply", 7: "fan", 8: "sensor", 9: "module", 10: "port",
    11: "stack", 12: "cpu",
}

SEVERITY_NAMES = {1: "other", 2: "minor", 3: "major", 4: "critical"}
RELATION_NAMES = {
    1: "lessThan", 2: "lessOrEqual", 3: "greaterThan",
    4: "greaterOrEqual", 5: "equalTo", 6: "notEqualTo",
}

SFP_MEDIA = {
    "GLC-SX-MMD": ("1000BASE-SX", "Multimode fiber / 850 nm", "550 m"),
    "GLC-SX-MM": ("1000BASE-SX", "Multimode fiber / 850 nm", "550 m"),
    "GLC-LH-SMD": ("1000BASE-LX/LH", "Singlemode fiber / 1310 nm", "10 km"),
    "GLC-LH-SM": ("1000BASE-LX/LH", "Singlemode fiber / 1310 nm", "10 km"),
    "GLC-ZX-SMD": ("1000BASE-ZX", "Singlemode fiber / 1550 nm", "70 km"),
    "GLC-EX-SMD": ("1000BASE-EX", "Singlemode fiber / 1310 nm", "40 km"),
    "SFP-10G-SR": ("10GBASE-SR", "Multimode fiber / 850 nm", "300 m"),
    "SFP-10G-LR": ("10GBASE-LR", "Singlemode fiber / 1310 nm", "10 km"),
    "SFP-10G-ER": ("10GBASE-ER", "Singlemode fiber / 1550 nm", "40 km"),
    "SFP-H10GB-CU3M": ("10GBASE-CU", "Direct attach copper", "3 m"),
}


def configure(timeout=None, retries=None):
    global SNMP_TIMEOUT, SNMP_RETRIES
    if timeout is not None:
        SNMP_TIMEOUT = max(1, int(timeout))
    if retries is not None:
        SNMP_RETRIES = max(0, int(retries))


def parse_value(raw):
    """Turn an ``snmpwalk -On`` value into a Python scalar."""
    raw = (raw or "").strip()
    if not raw or raw.startswith("No Such") or raw.startswith("No more"):
        return None

    if ": " in raw:
        typ, val = raw.split(": ", 1)
    else:
        typ, val = "", raw
    typ = typ.strip().lower()
    val = val.strip()

    if typ == "timeticks":
        match = re.search(r"\((\d+)\)", val)
        if match:
            return int(match.group(1))
        match = re.search(r"-?\d+", val)
        return int(match.group()) if match else val

    if typ in ("integer", "integer32", "gauge32", "gauge", "counter32",
               "counter64", "unsigned32", "unsigned"):
        match = re.search(r"-?\d+", val)
        return int(match.group()) if match else val

    if typ == "oid":
        return val.lstrip(".")

    if typ in ("hex-string", "hexstring"):
        octets = re.findall(r"[0-9A-Fa-f]{2}", val)
        return ":".join(x.lower() for x in octets) if octets else val

    if typ == "string":
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        return val.replace('\\"', '"').replace("\\\\", "\\")

    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val


def walk(switch, oid):
    """Walk a subtree and return ``{suffix: value}`` relative to *oid*."""
    base = oid.lstrip(".")
    command = [
        SNMP_WALK, "-v2c", "-c", str(switch["community"]),
        "-t", str(SNMP_TIMEOUT), "-r", str(SNMP_RETRIES),
        "-On", str(switch["host"]), base,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=SNMP_TIMEOUT * 2 + 3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}

    values = {}
    for line in result.stdout.splitlines():
        if " = " not in line:
            continue
        full, raw = line.split(" = ", 1)
        full = full.strip().lstrip(".")
        if full == base:
            suffix = ""
        elif full.startswith(base + "."):
            suffix = full[len(base) + 1:]
        else:
            continue
        value = parse_value(raw)
        if value is not None:
            values[suffix] = value
    return values


def table(values):
    """Group ``{suffix: value}`` into ``{index: {column: value}}``."""
    rows = {}
    for suffix, value in values.items():
        parts = suffix.split(".")
        column = parts[0]
        index = ".".join(parts[1:]) if len(parts) > 1 else ""
        rows.setdefault(index, {})[column] = value
    return rows


def as_int(value, default=0):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if match:
            return int(match.group())
    return default


def as_float(value, default=None):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def mac_from_suffix(suffix):
    try:
        parts = [int(part) for part in suffix.split(".")]
        if len(parts) == 6:
            return ":".join(f"{part:02x}" for part in parts)
    except ValueError:
        pass
    return suffix


def format_uptime(ticks):
    if not isinstance(ticks, (int, float)):
        return "—"
    seconds = int(ticks / 100)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_last_change(ticks):
    if not isinstance(ticks, (int, float)):
        return "—"
    seconds = int(ticks / 100)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


# ---------------------------------------------------------------------------
# ENTITY-MIB
# ---------------------------------------------------------------------------

def parse_entities(raw):
    """Parse the ENTITY-MIB physical table.

    Real Cisco devices use the standard column order (descr in column 1).
    The lab simulator uses a one-column-shifted layout, so both are accepted.
    """
    entities = []
    for index, columns in raw.items():
        if not index.isdigit():
            continue
        standard = "1" in columns and isinstance(columns.get("1"), str)
        if standard:
            mapping = {
                "descr": "1", "vendor_type": "2", "contained_in": "3",
                "class_id": "4", "parent_pos": "5", "name": "6",
                "hw_rev": "7", "fw_rev": "8", "sw_rev": "9",
                "serial": "10", "vendor": "11", "model": "12",
                "asset": "13", "is_fru": "14",
            }
        else:
            mapping = {
                "descr": "2", "vendor_type": "3", "contained_in": "4",
                "class_id": "5", "parent_pos": "6", "name": "7",
                "hw_rev": "8", "fw_rev": "9", "sw_rev": "10",
                "serial": "11", "vendor": "12", "model": "13",
                "asset": "14", "is_fru": "15",
            }
        entity = {"index": int(index)}
        for key, column in mapping.items():
            entity[key] = columns.get(column)
        entity["class_id"] = as_int(entity.get("class_id"))
        entity["class"] = ENTITY_CLASSES.get(entity["class_id"], "unknown")
        entity["contained_in"] = as_int(entity.get("contained_in"))
        entity["parent_pos"] = as_int(entity.get("parent_pos"))
        for key in ("descr", "name", "model", "serial", "vendor", "hw_rev",
                    "fw_rev", "sw_rev", "asset"):
            entity[key] = str(entity.get(key) or "").strip()
        entities.append(entity)
    entities.sort(key=lambda item: item["index"])
    return entities


# ---------------------------------------------------------------------------
# CISCO-ENTITY-SENSOR-MIB
# ---------------------------------------------------------------------------

def sensor_value(raw, scale, precision):
    return raw * (10 ** scale) / (10 ** precision)


def parse_sensors(raw_values, raw_thresholds, entities):
    """Combine entSensorValue and entSensorThreshold tables.

    Both arguments are the flat ``{suffix: value}`` dictionaries returned by
    :func:`walk`; they are grouped into table rows here.
    """
    by_index = {entity["index"]: entity for entity in entities}
    sensors = {}

    for index, columns in table(raw_values).items():
        if not index.isdigit():
            continue
        scale = as_int(columns.get("2"))
        precision = as_int(columns.get("3"))
        raw = as_int(columns.get("4"))
        sensor = {
            "index": int(index),
            "type_id": as_int(columns.get("1")),
            "scale": scale,
            "precision": precision,
            "value_raw": raw,
            "status_id": as_int(columns.get("5"), 1),
            "units": str(columns.get("6") or "").strip(),
            "thresholds": [],
        }
        sensor["type"] = SENSOR_TYPES.get(sensor["type_id"], "unknown")
        sensor["value"] = sensor_value(raw, scale, precision)
        entity = by_index.get(sensor["index"], {})
        sensor["entity_name"] = entity.get("name", "")
        sensor["entity_descr"] = entity.get("descr", "")
        sensor["parent_index"] = entity.get("contained_in", 0)
        sensors[index] = sensor

    # Standard entSensorThresholdTable layout:
    #   column 1 = severity, column 2 = relation, column 3 = threshold value,
    #   column 4 = evaluation flag.
    for row_index, columns in table(raw_thresholds).items():
        parts = row_index.split(".", 1)
        if len(parts) != 2:
            continue
        physical, threshold_index = parts
        sensor = sensors.get(physical)
        if not sensor:
            continue
        raw = columns.get("3")
        if raw is None:
            continue
        sensor["thresholds"].append({
            "index": as_int(threshold_index),
            "severity_id": as_int(columns.get("1")),
            "relation_id": as_int(columns.get("2")),
            "value_raw": as_int(raw),
            "value": sensor_value(as_int(raw), sensor["scale"], sensor["precision"]),
        })

    for sensor in sensors.values():
        sensor["thresholds"].sort(key=lambda item: item["index"])
        sensor["display"], sensor["unit"] = sensor_display(sensor)
        sensor["status"], sensor["alerts"] = evaluate_sensor(sensor)
    return sensors


def evaluate_sensor(sensor):
    status = "ok"
    alerts = []
    if sensor["status_id"] not in (0, 1):
        return "unknown", ["Sensor unavailable"]
    for threshold in sensor["thresholds"]:
        relation = threshold["relation_id"]
        value = sensor["value"]
        limit = threshold["value"]
        if relation == 1:
            breached = value < limit
        elif relation == 2:
            breached = value <= limit
        elif relation == 3:
            breached = value > limit
        elif relation == 4:
            breached = value >= limit
        elif relation == 5:
            breached = value == limit
        elif relation == 6:
            breached = value != limit
        else:
            breached = False
        if not breached:
            continue
        severity = threshold["severity_id"]
        label = SEVERITY_NAMES.get(severity, "threshold")
        if severity in (3, 4):
            status = "critical"
        elif severity == 2 and status != "critical":
            status = "warning"
        limit_display, limit_unit = sensor_display_value(sensor, limit)
        alerts.append(
            f"{sensor['entity_name'] or 'Sensor'} {label}: "
            f"{sensor['display']} {sensor['unit']} "
            f"{'below' if relation in (1, 2) else 'above'} "
            f"{limit_display:g} {limit_unit}"
        )
    return status, alerts


def sensor_display_value(sensor, value):
    sensor_type = sensor["type_id"]
    if sensor_type == 5:  # amperes -> mA for optics bias
        return round(value * 1000, 1), "mA"
    if sensor_type == 4:
        return round(value, 2), "V"
    if sensor_type == 8:
        return round(value, 1), "°C"
    if sensor_type == 38:
        return round(value, 1), "dBm"
    if sensor_type == 39:
        return round(value, 1), "dB"
    if sensor_type == 9:
        return round(value, 1), "%"
    if sensor_type == 10:
        return round(value, 0), "rpm"
    return round(value, 2), sensor["units"] or ""


def sensor_display(sensor):
    return sensor_display_value(sensor, sensor["value"])


def threshold_map(sensor):
    """Return low/high alarm/warning values for one sensor."""
    result = {
        "low_alarm": None, "low_warn": None,
        "high_warn": None, "high_alarm": None,
    }
    for threshold in sensor["thresholds"]:
        low = threshold["relation_id"] in (1, 2)
        high = threshold["relation_id"] in (3, 4)
        severity = threshold["severity_id"]
        value, _unit = sensor_display_value(sensor, threshold["value"])
        if low and severity in (3, 4):
            result["low_alarm"] = value if result["low_alarm"] is None else min(result["low_alarm"], value)
        elif low and severity == 2:
            result["low_warn"] = value if result["low_warn"] is None else max(result["low_warn"], value)
        elif high and severity in (3, 4):
            result["high_alarm"] = value if result["high_alarm"] is None else max(result["high_alarm"], value)
        elif high and severity == 2:
            result["high_warn"] = value if result["high_warn"] is None else min(result["high_warn"], value)
    return result


def classify_sensor(sensor):
    name = f"{sensor.get('entity_name', '')} {sensor.get('entity_descr', '')}".lower()
    if "tx" in name or "transmit" in name:
        return "tx"
    if "rx" in name or "receive" in name:
        return "rx"
    if "temp" in name:
        return "temperature"
    if "volt" in name:
        return "voltage"
    if "bias" in name or "current" in name:
        return "bias"
    sensor_type = sensor.get("type_id")
    if sensor_type == 8:
        return "temperature"
    if sensor_type == 4:
        return "voltage"
    if sensor_type == 5:
        return "bias"
    return "other"
