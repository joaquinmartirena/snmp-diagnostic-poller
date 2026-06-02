#!/usr/bin/env python3
"""
config_loader.py — YAML config loading and device normalization.

Extracted from the original diag_poller.py. Kept in `shared` so both the
polling tool and (eventually) the PoC runner can reuse device parsing.

To avoid importing `polling` from `shared` (which would break the layering
invariant), `normalize_device` does NOT know about the profile registry.
The caller passes the set of valid device types in `valid_types`; if None,
type validation is skipped here and left to the caller.
"""

import yaml

# Config defaults
DEFAULT_PORT           = 161
DEFAULT_COMMUNITY      = "public"
DEFAULT_VMS_INTERVAL   = 60.0
DEFAULT_ALARM_INTERVAL = 30.0
DEFAULT_CYCLE_INTERVAL = 2.0


def normalize_device(d, valid_types=None):
    """Apply per-type defaults and validate a device config dict."""
    if "name" not in d or "type" not in d or "ip" not in d:
        raise ValueError(f"Device missing required name/type/ip: {d!r}")
    dtype = d["type"]
    if valid_types is not None and dtype not in valid_types:
        valid = ", ".join(sorted(valid_types))
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


def load_config(path, valid_types=None):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    devices = data.get("devices")
    if not devices:
        raise ValueError("Config has no 'devices' list")
    return [normalize_device(d, valid_types) for d in devices]
