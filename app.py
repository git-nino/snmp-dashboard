"""SNMP switch dashboard — Flask entry point.

Serves a Meraki/Cisco-style live dashboard, JSON APIs and an A4 print report.
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, render_template

from snmp_core import configure, format_uptime
from switch_model import empty_data, poll_switch, speed_label

BASE = Path(__file__).resolve().parent
CONFIG = json.loads((BASE / "config.json").read_text())
SWITCHES = CONFIG["switches"]
SWITCH_BY_ID = {switch["id"]: switch for switch in SWITCHES}
POLL_SECONDS = int(CONFIG.get("refresh_seconds", 5))
configure(CONFIG.get("snmp_timeout", 2), CONFIG.get("snmp_retries", 0))

app = Flask(__name__)
LOCK = threading.Lock()
CACHE = {}
PREVIOUS = {}
_POLLERS_STARTED = False


def summary_for(data):
    return {
        "id": data["id"],
        "name": data["name"],
        "host": data["host"],
        "online": data["online"],
        "model": data["hardware"]["model"],
        "serial": data["hardware"]["serial"],
        "uptime_text": data["sys"]["uptime_text"],
        "status": data["health"]["status"],
        "ports": data["port_summary"],
        "cpu_percent": data["health"]["cpu_percent"],
        "memory_percent": data["health"]["memory_percent"],
        "temperature_c": data["health"]["temperature_c"],
        "sfp_count": data["health"]["sfp_count"],
        "alerts": len(data["health"]["alerts"]),
        "last_poll": data["last_poll"],
    }


def poll_worker(switch):
    while True:
        try:
            with LOCK:
                previous = PREVIOUS.get(switch["id"])
            data, counters = poll_switch(switch, previous)
            with LOCK:
                CACHE[switch["id"]] = data
                PREVIOUS[switch["id"]] = counters
        except Exception as exc:  # keep one bad device from killing the poller
            with LOCK:
                CACHE[switch["id"]] = empty_data(switch, str(exc))
        time.sleep(POLL_SECONDS)


def ensure_pollers():
    global _POLLERS_STARTED
    if _POLLERS_STARTED:
        return
    _POLLERS_STARTED = True
    for switch in SWITCHES:
        thread = threading.Thread(
            target=poll_worker, args=(switch,),
            name=f"poll-{switch['id']}", daemon=True,
        )
        thread.start()


def get_switch(switch_id):
    switch = SWITCH_BY_ID.get(switch_id)
    if not switch:
        abort(404)
    return switch


def cached_or_poll(switch_id):
    with LOCK:
        data = CACHE.get(switch_id)
        previous = PREVIOUS.get(switch_id)
    if data is None:
        data, counters = poll_switch(get_switch(switch_id), previous)
        with LOCK:
            CACHE[switch_id] = data
            PREVIOUS[switch_id] = counters
    return data


def snapshot():
    with LOCK:
        return [CACHE[switch["id"]] for switch in SWITCHES
                if switch["id"] in CACHE]


@app.template_filter("num")
def filter_num(value):
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter("pct")
def filter_pct(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter("bytes")
def filter_bytes(value):
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(number) < 1024 or unit == "TB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{number:.0f} B"
        number /= 1024
    return f"{number:.1f} TB"


@app.template_filter("dbm")
def filter_dbm(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f} dBm"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter("db")
def filter_db(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} dB"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter("uptime")
def filter_uptime(value):
    return format_uptime(value)


@app.template_filter("speed")
def filter_speed(value):
    return speed_label(value)


@app.template_filter("status_label")
def filter_status_label(value):
    return {
        "ok": "Healthy", "warning": "Warning", "critical": "Critical",
        "unknown": "Unknown", "up": "Up", "down": "Down",
        "disabled": "Disabled", "fiber": "Fiber", "copper": "Copper",
    }.get(str(value).lower(), str(value).title())


@app.get("/")
def overview():
    initial = [summary_for(data) for data in snapshot()]
    return render_template(
        "overview.html", switches=SWITCHES, refresh=POLL_SECONDS,
        active="overview", initial=initial,
    )


@app.get("/switch/<switch_id>")
def switch_page(switch_id):
    switch = get_switch(switch_id)
    data = cached_or_poll(switch_id)
    return render_template(
        "switch.html", switches=SWITCHES, switch=switch,
        refresh=POLL_SECONDS, active="switch", active_switch=switch_id,
        initial=data,
    )


@app.get("/report/<switch_id>")
def report_page(switch_id):
    switch = get_switch(switch_id)
    data = cached_or_poll(switch_id)
    return render_template(
        "report.html", data=data, switch=switch,
        generated=datetime.now(), refresh=POLL_SECONDS,
    )


@app.get("/api/data")
def api_data():
    with LOCK:
        return jsonify({
            "refresh_seconds": POLL_SECONDS,
            "switches": [CACHE[switch["id"]] for switch in SWITCHES
                         if switch["id"] in CACHE],
        })


@app.get("/api/switches")
def api_switches():
    with LOCK:
        payload = []
        for switch in SWITCHES:
            data = CACHE.get(switch["id"])
            if data is None:
                payload.append({
                    "id": switch["id"], "name": switch["name"],
                    "host": switch["host"], "online": False,
                    "status": "unknown", "model": "—", "serial": "—",
                    "uptime_text": "—", "ports": {
                        "total": 0, "up": 0, "down": 0, "disabled": 0,
                        "fiber": 0, "copper": 0, "errors": 0,
                        "discards": 0, "up_percent": 0,
                    },
                    "cpu_percent": None, "memory_percent": None,
                    "temperature_c": None, "sfp_count": 0,
                    "alerts": 0, "last_poll": None,
                })
            else:
                payload.append(summary_for(data))
        return jsonify(payload)


@app.get("/api/switch/<switch_id>")
def api_switch(switch_id):
    return jsonify(cached_or_poll(switch_id))


@app.get("/api/report/<switch_id>")
def api_report(switch_id):
    get_switch(switch_id)
    return jsonify(cached_or_poll(switch_id))


@app.get("/health")
def health():
    with LOCK:
        online = sum(1 for switch in SWITCHES
                     if CACHE.get(switch["id"], {}).get("online"))
    return jsonify({"status": "ok", "switches": len(SWITCHES), "online": online})


@app.get("/favicon.ico")
def favicon():
    return "", 204


ensure_pollers()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
