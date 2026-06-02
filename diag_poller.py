#!/usr/bin/env python3
"""
diag_poller.py — Read-only SNMP v2c diagnostic poller for ITS field devices.

Orchestration only. Device-specific OIDs live in shared/oid_providers/,
decoding lives in polling/profiles/, and generic helpers in shared/.

The tool is strictly READ-ONLY: profiles issue SNMP GET operations only,
through SnmpClient(allow_write=False), and never perform SET, activation,
reset, or any write operation.

Usage:
    python diag_poller.py --config config.yaml   # config-driven (multi-device)
    python diag_poller.py                         # interactive single-device
"""

import asyncio
import argparse

from shared.config_loader import (
    load_config, normalize_device,
    DEFAULT_PORT, DEFAULT_COMMUNITY,
    DEFAULT_VMS_INTERVAL, DEFAULT_ALARM_INTERVAL, DEFAULT_CYCLE_INTERVAL,
)
from polling.profiles import PROFILE_TASKS


# ===========================================================================
# Configuration
# ===========================================================================
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
    return [normalize_device(d, valid_types=set(PROFILE_TASKS))]


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
    if args.config:
        devices = load_config(args.config, valid_types=set(PROFILE_TASKS))
    else:
        devices = prompt_config()

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
