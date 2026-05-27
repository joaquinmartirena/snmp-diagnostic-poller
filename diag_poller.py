#!/usr/bin/env python3
"""
diag_poller.py — Read-only SNMP v2c diagnostic poller for ITS field devices.

Orchestration only. Device-specific OIDs and decoding live in the profile
modules under profiles/. Generic helpers live in common.py.

The tool is strictly READ-ONLY: it issues SNMP GET operations only and never
performs SET, activation, reset, or any write operation.

Usage:
    python diag_poller.py --config config.yaml   # config-driven (multi-device)
    python diag_poller.py                         # interactive single-device
"""

import asyncio
import argparse

import yaml

from profiles import PROFILE_TASKS

# Config defaults
DEFAULT_PORT           = 161
DEFAULT_COMMUNITY      = "public"
DEFAULT_VMS_INTERVAL   = 60.0
DEFAULT_ALARM_INTERVAL = 30.0
DEFAULT_CYCLE_INTERVAL = 2.0


# ===========================================================================
# Configuration
# ===========================================================================
def normalize_device(d):
    """Apply per-type defaults and validate a device config dict."""
    if "name" not in d or "type" not in d or "ip" not in d:
        raise ValueError(f"Device missing required name/type/ip: {d!r}")
    dtype = d["type"]
    if dtype not in PROFILE_TASKS:
        valid = ", ".join(sorted(PROFILE_TASKS))
        raise ValueError(f"Unknown device type '{dtype}' for {d.get('name')}. "
                         f"Valid types: {valid}")

    out = {
        "name":      str(d["name"]),
        "type":      dtype,
        "ip":        str(d["ip"]),
        "port":      int(d.get("port", DEFAULT_PORT)),
        "community": str(d.get("community", DEFAULT_COMMUNITY)),
    }
    if dtype == "VMS_NTCIP1203":
        out["interval_seconds"] = float(d.get("interval_seconds", DEFAULT_VMS_INTERVAL))
    elif dtype == "SEMEX_C5000_V1":
        out["alarm_interval_seconds"] = float(d.get("alarm_interval_seconds", DEFAULT_ALARM_INTERVAL))
        out["cycle_interval_seconds"] = float(d.get("cycle_interval_seconds", DEFAULT_CYCLE_INTERVAL))
        out["cycle_change_log"] = bool(d.get("cycle_change_log", False))
    return out


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    devices = data.get("devices")
    if not devices:
        raise ValueError("Config has no 'devices' list")
    return [normalize_device(d) for d in devices]


def prompt_config():
    """Interactive fallback: configure a single device."""
    print("=== Diagnostic Poller (interactive) ===")
    print("No --config given. Configuring one device.")
    print("Types: " + " | ".join(sorted(PROFILE_TASKS)))
    dtype = input("Device type [VMS_NTCIP1203]: ").strip() or "VMS_NTCIP1203"
    name  = input("Device name: ").strip() or "device1"
    ip    = input("Device IP: ").strip()
    port  = input(f"SNMP port [{DEFAULT_PORT}]: ").strip()
    comm  = input(f"Community [{DEFAULT_COMMUNITY}]: ").strip()

    d = {"name": name, "type": dtype, "ip": ip}
    if port:
        d["port"] = int(port)
    if comm:
        d["community"] = comm

    if dtype == "VMS_NTCIP1203":
        iv = input(f"Poll interval seconds [{int(DEFAULT_VMS_INTERVAL)}]: ").strip()
        if iv:
            d["interval_seconds"] = float(iv)
    elif dtype == "SEMEX_C5000_V1":
        ai = input(f"Alarm interval seconds [{int(DEFAULT_ALARM_INTERVAL)}]: ").strip()
        ci = input(f"Cycle interval seconds [{int(DEFAULT_CYCLE_INTERVAL)}]: ").strip()
        if ai:
            d["alarm_interval_seconds"] = float(ai)
        if ci:
            d["cycle_interval_seconds"] = float(ci)
    return [normalize_device(d)]


def parse_args():
    p = argparse.ArgumentParser(
        description="Read-only SNMP diagnostic poller (profile-based)")
    p.add_argument("--config", help="Path to YAML config file")
    return p.parse_args()


# ===========================================================================
# Async orchestration
# ===========================================================================
async def run_all(devices):
    tasks = []
    for dev in devices:
        tasks.extend(PROFILE_TASKS[dev["type"]](dev))
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def describe(dev):
    if dev["type"] == "VMS_NTCIP1203":
        extra = f"interval={dev['interval_seconds']}s"
    else:
        extra = f"alarm={dev['alarm_interval_seconds']}s cycle={dev['cycle_interval_seconds']}s"
    return f"  - {dev['name']} [{dev['type']}] {dev['ip']}:{dev['port']} {extra}"


def main():
    args = parse_args()
    devices = load_config(args.config) if args.config else prompt_config()

    print("\nMonitoring devices (read-only):")
    for d in devices:
        print(describe(d))
    print("Press Ctrl+C to stop.\n")

    try:
        asyncio.run(run_all(devices))
    except KeyboardInterrupt:
        print("\nStopping diagnostic poller...")


if __name__ == "__main__":
    main()
