"""Build the switch data model consumed by the dashboard and A4 report."""

import re
import time

from snmp_core import (
    SFP_MEDIA, as_int, classify_sensor, format_last_change, format_uptime,
    mac_from_suffix, parse_entities, parse_sensors, table, threshold_map, walk,
)


def status_worst(statuses):
    statuses = [status for status in statuses if status]
    if not statuses:
        return "unknown"
    if "critical" in statuses:
        return "critical"
    if "warning" in statuses:
        return "warning"
    if all(status == "unknown" for status in statuses):
        return "unknown"
    return "ok"


def status_rank(status):
    return {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}.get(status, 1)


def speed_label(speed):
    if not speed:
        return "—"
    if speed >= 1000:
        value = speed / 1000
        return f"{value:g} Gbps"
    return f"{speed:g} Mbps"


def empty_data(switch, error):
    return {
        "id": switch["id"],
        "name": switch["name"],
        "host": switch["host"],
        "online": False,
        "last_error": error,
        "last_poll": int(time.time()),
        "poll_duration_ms": 0,
        "sys": {
            "name": switch["name"], "descr": "—", "object_id": "",
            "uptime_ticks": 0, "uptime_text": "—", "location": "—",
            "contact": "—", "services": 0,
        },
        "hardware": {
            "model": "—", "serial": "—", "vendor": "—", "firmware": "—",
            "hardware_rev": "—", "asset": "—", "components": [],
            "sensors": [], "psu_count": 0, "fan_count": 0,
            "sfp_count": 0, "sensor_count": 0, "chassis": None,
        },
        "health": {
            "status": "unknown", "hardware_status": "unknown",
            "optics_status": "unknown", "cpu_percent": None,
            "cpu_1min": None, "cpu_5min": None, "cpu_5sec": None,
            "memory_used": None, "memory_free": None,
            "memory_percent": None, "temperature_c": None,
            "temperature_status": "unknown", "temperature_sensor": "—",
            "psu_count": 0, "fan_count": 0, "sfp_count": 0,
            "sensor_count": 0, "alerts": [
                {"severity": "critical",
                 "text": f"No SNMP response from {switch['host']} ({error})"}
            ],
        },
        "ports": [], "sfps": [], "vlans": [], "macs": [], "neighbors": [],
        "port_summary": {
            "total": 0, "up": 0, "down": 0, "disabled": 0,
            "fiber": 0, "copper": 0, "errors": 0, "discards": 0,
            "up_percent": 0,
        },
        "mac_total": 0,
        "alerts": [
            {"severity": "critical",
             "text": f"No SNMP response from {switch['host']} ({error})"}
        ],
    }


def find_sfp_port(entity, ports):
    indexes = {port["index"] for port in ports}
    position = entity.get("parent_pos") or 0
    if position in indexes:
        return position
    match = re.search(r"(\d+)\s*$", entity.get("name", ""))
    if match and int(match.group(1)) in indexes:
        return int(match.group(1))
    haystack = f"{entity.get('name', '')} {entity.get('descr', '')}".lower()
    for port in ports:
        if port.get("name") and port["name"].lower() in haystack:
            return port["index"]
    return None


def media_for_sfp(entity):
    model = (entity.get("model") or "").upper()
    if model in SFP_MEDIA:
        return SFP_MEDIA[model]
    haystack = f"{entity.get('descr', '')} {entity.get('name', '')}".upper()
    for key, media in SFP_MEDIA.items():
        if key in haystack or media[0] in haystack:
            return media
    if "SX" in haystack:
        return ("1000BASE-SX", "Multimode fiber / 850 nm", "550 m")
    if "LX" in haystack or "LH" in haystack:
        return ("1000BASE-LX/LH", "Singlemode fiber / 1310 nm", "10 km")
    if "ZX" in haystack:
        return ("1000BASE-ZX", "Singlemode fiber / 1550 nm", "70 km")
    return ("Fiber", "Fiber transceiver", "—")


def build_sfps(entities, sensors, ports):
    ports_by_index = {port["index"]: port for port in ports}
    sfp_entities = []
    for entity in entities:
        if entity["class_id"] != 9:
            continue
        haystack = f"{entity['name']} {entity['descr']} {entity['model']}".lower()
        if ("sfp" in haystack or "transceiver" in haystack
                or entity["model"].upper().startswith(("GLC-", "SFP-"))):
            sfp_entities.append(entity)

    sfps = []
    for entity in sfp_entities:
        port_index = find_sfp_port(entity, ports)
        port = ports_by_index.get(port_index, {})
        parent_sensors = [
            sensor for sensor in sensors.values()
            if sensor.get("parent_index") == entity["index"]
        ]
        roles = {}
        for sensor in parent_sensors:
            roles.setdefault(classify_sensor(sensor), sensor)

        thresholds = {}
        for role in ("tx", "rx", "temperature", "voltage", "bias"):
            sensor = roles.get(role)
            thresholds[role] = threshold_map(sensor) if sensor else {
                "low_alarm": None, "low_warn": None,
                "high_warn": None, "high_alarm": None,
            }

        tx = roles.get("tx", {}).get("value")
        rx = roles.get("rx", {}).get("value")
        rx_thresholds = thresholds.get("rx", {})
        tx_thresholds = thresholds.get("tx", {})
        loss = round(tx - rx, 2) if tx is not None and rx is not None else None
        margin = (round(rx - rx_thresholds["low_alarm"], 2)
                  if rx is not None and rx_thresholds.get("low_alarm") is not None
                  else None)
        budget = (round(tx - rx_thresholds["low_alarm"], 2)
                  if tx is not None and rx_thresholds.get("low_alarm") is not None
                  else None)
        tx_headroom = (round(tx - tx_thresholds["low_alarm"], 2)
                       if tx is not None and tx_thresholds.get("low_alarm") is not None
                       else None)

        sensor_statuses = [sensor["status"] for sensor in parent_sensors]
        sfp_status = status_worst(sensor_statuses) if parent_sensors else "unknown"
        alerts = []
        for sensor in parent_sensors:
            for alert in sensor.get("alerts", []):
                alerts.append({
                    "severity": "critical" if sensor["status"] == "critical" else "warning",
                    "text": alert,
                })
        if rx is not None and rx_thresholds.get("low_alarm") is not None and rx < rx_thresholds["low_alarm"]:
            sfp_status = "critical"
        elif rx is not None and rx_thresholds.get("low_warn") is not None and rx < rx_thresholds["low_warn"]:
            if sfp_status != "critical":
                sfp_status = "warning"

        media = media_for_sfp(entity)
        sensor_details = []
        for role in ("temperature", "voltage", "bias", "tx", "rx"):
            sensor = roles.get(role)
            if not sensor:
                continue
            sensor_details.append({
                "role": role,
                "name": sensor.get("entity_name") or role,
                "value": sensor.get("display"),
                "unit": sensor.get("unit"),
                "status": sensor.get("status"),
                "thresholds": threshold_map(sensor),
            })

        sfps.append({
            "port_index": port_index,
            "port_name": port.get("name", "—"),
            "alias": port.get("alias", ""),
            "link_status": port.get("status", "unknown"),
            "speed_mbps": port.get("speed_mbps", 0),
            "entity_index": entity["index"],
            "name": entity.get("name") or f"SFP {port_index or ''}".strip(),
            "descr": entity.get("descr", ""),
            "model": entity.get("model", ""),
            "serial": entity.get("serial", ""),
            "vendor": entity.get("vendor", ""),
            "module": media[0],
            "fiber": media[1],
            "reach": media[2],
            "status": sfp_status,
            "alerts": alerts,
            "temperature_c": roles.get("temperature", {}).get("value"),
            "voltage_v": roles.get("voltage", {}).get("value"),
            "bias_ma": (roles.get("bias", {}).get("value", 0) * 1000
                        if roles.get("bias") else None),
            "tx_dbm": tx,
            "rx_dbm": rx,
            "loss_db": loss,
            "margin_db": margin,
            "budget_db": budget,
            "tx_headroom_db": tx_headroom,
            "thresholds": thresholds,
            "sensors": sensor_details,
        })

    sfps.sort(key=lambda item: (item["port_index"] or 9999, item["name"]))
    return sfps


def build_ports(if_raw, ifx_raw, sfps, vlan_names, cisco_vlans, previous, now):
    sfp_by_port = {sfp["port_index"]: sfp for sfp in sfps if sfp["port_index"]}
    indexes = sorted(
        set(if_raw) | set(ifx_raw),
        key=lambda item: int(item) if item.isdigit() else 999999,
    )
    old_counters = previous.get("counters", {})
    old_time = previous.get("time")
    elapsed = max(now - old_time, 0.001) if old_time else 0
    counters = {}
    ports = []

    for index in indexes:
        columns = if_raw.get(index, {})
        extended = ifx_raw.get(index, {})
        name = str(extended.get("1") or columns.get("2") or f"Interface {index}")
        descr = str(columns.get("2") or name)
        alias = str(extended.get("18") or "")
        admin = as_int(columns.get("7"))
        oper = as_int(columns.get("8"))
        if_type = as_int(columns.get("3"))
        speed = as_int(extended.get("15"))
        if speed == 0:
            speed = as_int(columns.get("5")) // 1_000_000

        rx_bytes = as_int(extended.get("6"), as_int(columns.get("10")))
        tx_bytes = as_int(extended.get("10"), as_int(columns.get("16")))
        old = old_counters.get(index, {})
        old_rx = old.get("rx")
        old_tx = old.get("tx")
        if elapsed and old_rx is not None and rx_bytes >= old_rx:
            rx_mbps = (rx_bytes - old_rx) * 8 / elapsed / 1_000_000
        else:
            rx_mbps = 0
        if elapsed and old_tx is not None and tx_bytes >= old_tx:
            tx_mbps = (tx_bytes - old_tx) * 8 / elapsed / 1_000_000
        else:
            tx_mbps = 0
        counters[index] = {"rx": rx_bytes, "tx": tx_bytes}

        in_errors = as_int(columns.get("14"))
        out_errors = as_int(columns.get("20"))
        in_discards = as_int(columns.get("13"))
        out_discards = as_int(columns.get("19"))
        if oper == 1:
            status = "up"
        elif admin == 2:
            status = "disabled"
        else:
            status = "down"

        # A link that is not up cannot carry traffic; suppress any counter
        # drift the simulator may still report for it.
        if status != "up":
            rx_mbps = 0
            tx_mbps = 0

        sfp = sfp_by_port.get(int(index) if index.isdigit() else None)
        media = "fiber" if sfp else "copper"
        vlan_id = str(cisco_vlans.get(index, {}).get("2", "") or "")
        utilization = 0
        if speed:
            utilization = round(min(max(rx_mbps, tx_mbps) / speed * 100, 100), 1)

        ports.append({
            "index": int(index) if index.isdigit() else index,
            "name": name,
            "descr": descr,
            "alias": alias,
            "admin": admin,
            "oper": oper,
            "status": status,
            "status_text": {"up": "Up", "down": "Down", "disabled": "Disabled"}[status],
            "if_type": if_type,
            "speed_mbps": speed,
            "speed_label": speed_label(speed),
            "media": media,
            "type": "SFP" if sfp else "Copper",
            "vlan_id": vlan_id,
            "vlan_name": vlan_names.get(vlan_id, ""),
            "rx_mbps": round(rx_mbps, 3),
            "tx_mbps": round(tx_mbps, 3),
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "in_errors": in_errors,
            "out_errors": out_errors,
            "in_discards": in_discards,
            "out_discards": out_discards,
            "utilization": utilization,
            "last_change": format_last_change(columns.get("9")),
            "sfp": sfp,
        })
    return ports, counters


def build_vlans(vlan_raw, ports):
    vlans = []
    for index, columns in vlan_raw.items():
        vlans.append({
            "id": index,
            "name": str(columns.get("1") or ""),
            "ports": 0,
            "up": 0,
        })
    by_id = {vlan["id"]: vlan for vlan in vlans}
    for port in ports:
        vlan = by_id.get(port["vlan_id"])
        if vlan:
            vlan["ports"] += 1
            if port["status"] == "up":
                vlan["up"] += 1
    vlans.sort(key=lambda item: int(item["id"]) if item["id"].isdigit() else 999999)
    return vlans


def build_macs(fdb_raw, bridge_raw, ports):
    bridge_map = {
        index: str(columns.get("2") or "")
        for index, columns in bridge_raw.items()
    }
    port_names = {str(port["index"]): port["name"] for port in ports}
    status_names = {1: "Other", 2: "Invalid", 3: "Learned", 4: "Self", 5: "Management"}
    macs = []
    for index, columns in fdb_raw.items():
        bridge_port = str(columns.get("2") or "")
        interface_index = bridge_map.get(bridge_port, "")
        status = as_int(columns.get("3"))
        macs.append({
            "mac": mac_from_suffix(index),
            "port": bridge_port,
            "interface": port_names.get(interface_index, "Unknown"),
            "status": status,
            "status_text": status_names.get(status, f"Status {status}"),
        })
    macs.sort(key=lambda item: (item["interface"], item["mac"]))
    return macs


def build_neighbors(lldp_raw, ports):
    port_names = {str(port["index"]): port["name"] for port in ports}
    neighbors = []
    for index, columns in lldp_raw.items():
        parts = index.split(".")
        if len(parts) < 3:
            continue
        local_port = parts[1]
        neighbors.append({
            "local_port": port_names.get(local_port, local_port),
            "remote_name": str(columns.get("6") or ""),
            "remote_port": str(columns.get("4") or ""),
            "remote_port_desc": str(columns.get("5") or ""),
            "remote_chassis": str(columns.get("2") or ""),
            "remote_descr": str(columns.get("7") or ""),
        })
    neighbors.sort(key=lambda item: item["local_port"])
    return neighbors


def poll_switch(switch, previous=None):
    started = time.monotonic()
    previous = previous or {}
    now = time.monotonic()

    system_raw = table(walk(switch, "1.3.6.1.2.1.1"))
    scalar = system_raw.get("0", {})
    sys_descr = str(scalar.get("1") or "")
    sys_name = str(scalar.get("5") or "")
    if not sys_descr and not sys_name:
        return empty_data(switch, "No SNMP response"), previous

    if_raw = table(walk(switch, "1.3.6.1.2.1.2.2.1"))
    ifx_raw = table(walk(switch, "1.3.6.1.2.1.31.1.1.1"))
    entity_raw = table(walk(switch, "1.3.6.1.2.1.47.1.1.1.1"))
    sensor_values = walk(switch, "1.3.6.1.4.1.9.9.91.1.1.1.1")
    sensor_thresholds = walk(switch, "1.3.6.1.4.1.9.9.91.1.2.1.1")

    entities = parse_entities(entity_raw)
    sensors = parse_sensors(sensor_values, sensor_thresholds, entities)

    cpu_raw = table(walk(switch, "1.3.6.1.4.1.9.9.109.1.1.1.1"))
    memory_raw = table(walk(switch, "1.3.6.1.4.1.9.9.48.1.1.1"))
    vlan_raw = table(walk(switch, "1.3.6.1.2.1.17.7.1.4.3.1.1"))
    cisco_vlans = table(walk(switch, "1.3.6.1.4.1.9.9.68.1.2.2.1"))
    bridge_raw = table(walk(switch, "1.3.6.1.2.1.17.1.4.1.2"))
    fdb_raw = table(walk(switch, "1.3.6.1.2.1.17.4.3.1"))
    lldp_raw = table(walk(switch, "1.0.8802.1.1.2.1.4.1.1"))

    vlan_names = {
        index: str(columns.get("1") or "")
        for index, columns in vlan_raw.items()
    }

    cpu_values = []
    for columns in cpu_raw.values():
        value = columns.get("8", columns.get("6"))
        if value is not None:
            cpu_values.append(as_int(value))
    cpu_percent = round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None

    memory_used = sum(as_int(columns.get("5")) for columns in memory_raw.values())
    memory_free = sum(as_int(columns.get("6")) for columns in memory_raw.values())
    memory_total = memory_used + memory_free
    memory_percent = (round(memory_used * 100 / memory_total, 1)
                      if memory_total else None)

    chassis = next((entity for entity in entities if entity["class_id"] == 3), None)
    model = (chassis or {}).get("model") or ""
    if not model:
        match = re.search(r"(Catalyst[^,]+|Nexus[^,]+|Cisco[^,]+)", sys_descr)
        model = match.group(1).strip() if match else "Cisco switch"
    serial = (chassis or {}).get("serial") or "—"
    vendor = (chassis or {}).get("vendor") or "Cisco Systems"
    firmware = (chassis or {}).get("sw_rev") or "—"
    hardware_rev = (chassis or {}).get("hw_rev") or "—"
    asset = (chassis or {}).get("asset") or "—"

    sfps = build_sfps(entities, sensors, build_ports(
        if_raw, ifx_raw, [], vlan_names, cisco_vlans, previous, now
    )[0])
    ports, counters = build_ports(
        if_raw, ifx_raw, sfps, vlan_names, cisco_vlans, previous, now
    )
    # Re-attach the SFP object to its port after the final port list is known.
    sfp_by_port = {sfp["port_index"]: sfp for sfp in sfps if sfp["port_index"]}
    for port in ports:
        port["sfp"] = sfp_by_port.get(port["index"])

    vlans = build_vlans(vlan_raw, ports)
    macs = build_macs(fdb_raw, bridge_raw, ports)
    neighbors = build_neighbors(lldp_raw, ports)

    psu_entities = [entity for entity in entities if entity["class_id"] == 6]
    fan_entities = [entity for entity in entities if entity["class_id"] == 7]
    temp_sensors = [sensor for sensor in sensors.values() if sensor["type_id"] == 8]
    chassis_temp_sensors = [
        sensor for sensor in temp_sensors if sensor.get("parent_index") == 1
    ]
    temp_pool = chassis_temp_sensors or temp_sensors
    temp_sensor = max(temp_pool, key=lambda item: item["value"]) if temp_pool else None
    temperature_c = round(temp_sensor["value"], 1) if temp_sensor else None
    temperature_status = status_worst(
        [sensor["status"] for sensor in temp_pool]
    ) if temp_pool else "ok"

    components = []
    for entity in entities:
        if entity["class_id"] not in (3, 6, 7, 9):
            continue
        component_status = "ok"
        detail = "Present"
        if entity["class_id"] == 9:
            sfp = next((item for item in sfps if item["entity_index"] == entity["index"]), None)
            if sfp:
                component_status = sfp["status"]
                detail = f"{sfp['module']} · {sfp['status'].upper()}"
            else:
                detail = "Module present"
        elif entity["class_id"] == 6:
            detail = "Power supply present"
        elif entity["class_id"] == 7:
            detail = "Fan tray present"
        elif entity["class_id"] == 3:
            detail = "Chassis"
        components.append({
            "index": entity["index"],
            "name": entity["name"] or entity["descr"] or f"Entity {entity['index']}",
            "class": entity["class"],
            "class_id": entity["class_id"],
            "model": entity["model"] or "—",
            "serial": entity["serial"] or "—",
            "vendor": entity["vendor"] or "—",
            "descr": entity["descr"] or "—",
            "status": component_status,
            "detail": detail,
        })

    sensor_list = []
    entity_names = {entity["index"]: (entity["name"] or entity["descr"]) for entity in entities}
    for sensor in sensors.values():
        sensor_list.append({
            "index": sensor["index"],
            "name": sensor.get("entity_name") or f"Sensor {sensor['index']}",
            "parent": entity_names.get(sensor.get("parent_index"), "—"),
            "type": sensor["type"],
            "value": sensor.get("display"),
            "unit": sensor.get("unit"),
            "status": sensor["status"],
            "thresholds": threshold_map(sensor),
        })
    sensor_list.sort(key=lambda item: item["index"])

    port_summary = {
        "total": len(ports),
        "up": sum(1 for port in ports if port["status"] == "up"),
        "down": sum(1 for port in ports if port["status"] == "down"),
        "disabled": sum(1 for port in ports if port["status"] == "disabled"),
        "fiber": sum(1 for port in ports if port["media"] == "fiber"),
        "copper": sum(1 for port in ports if port["media"] == "copper"),
        "errors": sum(port["in_errors"] + port["out_errors"] for port in ports),
        "discards": sum(port["in_discards"] + port["out_discards"] for port in ports),
    }
    port_summary["up_percent"] = (
        round(port_summary["up"] * 100 / port_summary["total"], 1)
        if port_summary["total"] else 0
    )

    alerts = []
    for sensor in sensors.values():
        for text in sensor.get("alerts", []):
            alerts.append({
                "severity": "critical" if sensor["status"] == "critical" else "warning",
                "text": text,
            })
    for sfp in sfps:
        alerts.extend(sfp["alerts"])
    if cpu_percent is not None and cpu_percent >= 90:
        alerts.append({"severity": "warning",
                       "text": f"CPU utilization is high ({cpu_percent:.1f}%)"})
    if memory_percent is not None and memory_percent >= 90:
        alerts.append({"severity": "warning",
                       "text": f"Memory utilization is high ({memory_percent:.1f}%)"})
    alerts.sort(key=lambda item: status_rank(item["severity"]), reverse=True)
    # Deduplicate identical alert texts.
    seen = set()
    unique_alerts = []
    for alert in alerts:
        if alert["text"] in seen:
            continue
        seen.add(alert["text"])
        unique_alerts.append(alert)
    alerts = unique_alerts

    optics_status = status_worst([sfp["status"] for sfp in sfps]) if sfps else "unknown"
    hardware_status = status_worst(
        [temperature_status]
        + (["ok"] if psu_entities else [])
        + (["ok"] if fan_entities else [])
    )
    overall_status = status_worst([hardware_status, optics_status])
    if cpu_percent is not None and cpu_percent >= 90:
        overall_status = status_worst([overall_status, "warning"])
    if memory_percent is not None and memory_percent >= 90:
        overall_status = status_worst([overall_status, "warning"])

    health = {
        "status": overall_status,
        "hardware_status": hardware_status,
        "optics_status": optics_status,
        "cpu_percent": cpu_percent,
        "cpu_1min": None,
        "cpu_5min": cpu_percent,
        "cpu_5sec": None,
        "memory_used": memory_used or None,
        "memory_free": memory_free or None,
        "memory_percent": memory_percent,
        "temperature_c": temperature_c,
        "temperature_status": temperature_status,
        "temperature_sensor": temp_sensor.get("entity_name") if temp_sensor else "—",
        "psu_count": len(psu_entities),
        "fan_count": len(fan_entities),
        "sfp_count": len(sfps),
        "sensor_count": len(sensors),
        "alerts": alerts,
    }

    data = {
        "id": switch["id"],
        "name": sys_name or switch["name"],
        "host": switch["host"],
        "online": True,
        "last_error": None,
        "last_poll": int(time.time()),
        "poll_duration_ms": round((time.monotonic() - started) * 1000),
        "sys": {
            "name": sys_name or switch["name"],
            "descr": sys_descr or "—",
            "object_id": str(scalar.get("2") or ""),
            "uptime_ticks": as_int(scalar.get("3")),
            "uptime_text": format_uptime(as_int(scalar.get("3"))),
            "location": str(scalar.get("6") or "—"),
            "contact": str(scalar.get("4") or "—"),
            "services": as_int(scalar.get("7")),
        },
        "hardware": {
            "model": model,
            "serial": serial,
            "vendor": vendor,
            "firmware": firmware,
            "hardware_rev": hardware_rev,
            "asset": asset,
            "components": components,
            "sensors": sensor_list,
            "psu_count": len(psu_entities),
            "fan_count": len(fan_entities),
            "sfp_count": len(sfps),
            "sensor_count": len(sensors),
            "chassis": chassis,
        },
        "health": health,
        "ports": ports,
        "sfps": sfps,
        "vlans": vlans,
        "macs": macs,
        "neighbors": neighbors,
        "port_summary": port_summary,
        "mac_total": len(macs),
        "alerts": alerts,
    }
    return data, {"time": now, "counters": counters}
