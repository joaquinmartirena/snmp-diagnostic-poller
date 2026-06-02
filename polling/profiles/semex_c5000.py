#!/usr/bin/env python3
"""
SEMEX_C5000_V1 profile — SEMEX C5000 traffic signal controller (NTCIP 1202 ASC).

Two independent polling tasks:
    - alarm: unit/short alarm status + uptime (restart detection).
    - cycle: phase/ring/channel status + coordination scalars.

Alarm bit meanings are not yet confirmed, so unit/short alarm values are kept
as raw hex with placeholder decoders. READ-ONLY: GET operations only via
SnmpClient(allow_write=False). OIDs come from shared.oid_providers
(SemexC5000Provider); none are hardcoded here.
"""

import asyncio

from shared import value_utils
from shared.snmp_client import SnmpClient, classify_comm_status
from shared.oid_providers import OidProviderRegistry
from polling import common

# OID provider for this profile (no numeric OIDs live in this file).
OIDS = OidProviderRegistry.resolve("SEMEX_C5000_V1")

PHASE_GROUPS = OIDS.PHASE_GROUPS
RINGS        = OIDS.RINGS
CHANNELS     = OIDS.CHANNELS

CYCLE_PAIRS = OIDS.build_cycle_oids()
CYCLE_OIDS  = [oid for _, oid in CYCLE_PAIRS]

# ---------------------------------------------------------------------------
# Change-detection keys
# ---------------------------------------------------------------------------
ALARM_KEYS = ["alarm1_raw", "alarm2_raw", "short_alarm_raw", "restart"]
ALARM_LABELS = {"alarm1_raw": "ALARM1_RAW", "alarm2_raw": "ALARM2_RAW",
                "short_alarm_raw": "SHORT_ALARM_RAW", "restart": "RESTART"}

CYCLE_KEYS = ["phases", "rings", "channels", "coord"]
CYCLE_LABELS = {"phases": "PHASES", "rings": "RINGS",
                "channels": "CHANNELS", "coord": "COORD"}

ALARM_FAILURE_SUFFIX = ("ALARM1=? ALARM1_RAW=? ALARM2=? ALARM2_RAW=? "
                        "SHORT_ALARM=? SHORT_ALARM_RAW=? UPTIME=? RESTART=?")
CYCLE_FAILURE_SUFFIX = "PHASES=? RINGS=? CHANNELS=? COORD=?"


# ---------------------------------------------------------------------------
# Alarm decoders (placeholders until bit meanings are confirmed)
# ---------------------------------------------------------------------------
def decode_semex_unit_alarm_status1(value):
    """Return (label, raw_hex). 'none' when zero, 'unknown' otherwise."""
    iv = value_utils.value_to_int(value)
    raw = value_utils.raw_hex_padded(value, 4)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def decode_semex_unit_alarm_status2(value):
    iv = value_utils.value_to_int(value)
    raw = value_utils.raw_hex_padded(value, 4)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def decode_semex_short_alarm_status(value):
    iv = value_utils.value_to_int(value)
    raw = value_utils.raw_hex_padded(value, 2)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def detect_restart(uptime, prev_uptime):
    """Return 'unknown' | 'no' | 'detected' based on uptime regression."""
    if uptime is None or prev_uptime is None:
        return "unknown"
    return "detected" if uptime < prev_uptime else "no"


# ---------------------------------------------------------------------------
# Cycle summary builders
# ---------------------------------------------------------------------------
def build_cycle_summaries(by_key):
    """by_key maps logical_key -> pysnmp value. Returns four summary strings."""
    phase_parts = []
    for g in PHASE_GROUPS:
        phase_parts.append(
            f"G{g}:R={value_utils.token_hex(by_key.get(f'p{g}_R'))},"
            f"Y={value_utils.token_hex(by_key.get(f'p{g}_Y'))},"
            f"G={value_utils.token_hex(by_key.get(f'p{g}_G'))},"
            f"DW={value_utils.token_hex(by_key.get(f'p{g}_DW'))},"
            f"W={value_utils.token_hex(by_key.get(f'p{g}_W'))},"
            f"VC={value_utils.token_hex(by_key.get(f'p{g}_VC'))},"
            f"PC={value_utils.token_hex(by_key.get(f'p{g}_PC'))},"
            f"ON={value_utils.token_hex(by_key.get(f'p{g}_ON'))}"
        )
    phases = "|".join(phase_parts)

    rings = "|".join(f"R{r}={value_utils.token_hex(by_key.get(f'r{r}'))}" for r in RINGS)

    chan_parts = []
    for c in CHANNELS:
        chan_parts.append(
            f"C{c}:R={value_utils.token_hex(by_key.get(f'c{c}_R'))},"
            f"Y={value_utils.token_hex(by_key.get(f'c{c}_Y'))},"
            f"G={value_utils.token_hex(by_key.get(f'c{c}_G'))}"
        )
    channels = "|".join(chan_parts)

    coord = (f"PATTERN={value_utils.token_int(by_key.get('coord_pattern'))},"
            f"SYS_PATTERN={value_utils.token_int(by_key.get('coord_sys_pattern'))},"
            f"LOCAL_FREE={value_utils.token_int(by_key.get('coord_local_free'))},"
            f"CYCLE={value_utils.token_int(by_key.get('coord_cycle'))},"
            f"SYNC={value_utils.token_int(by_key.get('coord_sync'))}")
    return phases, rings, channels, coord


# ---------------------------------------------------------------------------
# Polling tasks
# ---------------------------------------------------------------------------
async def run_semex_alarm(dev):
    client = SnmpClient(allow_write=False)
    transport = None
    prev_state = {}
    prev_uptime = None
    alarm_oids = OIDS.build_alarm_oids()

    while True:
        ts = common.now_ts()
        log_path = common.get_log_path(dev["name"], dev["ip"])
        try:
            if transport is None:
                transport = await client.make_transport(dev["ip"], dev["port"])
            vals, err = await client.get_many(
                transport, dev["community"], alarm_oids)
        except asyncio.CancelledError:
            raise
        except Exception:
            vals, err = {}, "TIMEOUT"

        comm = classify_comm_status(err, vals)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            prefix = common.build_common_prefix(ts, dev, "alarm", comm)
            common.emit(log_path, f"{prefix} {ALARM_FAILURE_SUFFIX}")
            await asyncio.sleep(dev["alarm_interval_seconds"])
            continue

        a1, a1_raw = decode_semex_unit_alarm_status1(vals.get(OIDS.UNIT_ALARM1))
        a2, a2_raw = decode_semex_unit_alarm_status2(vals.get(OIDS.UNIT_ALARM2))
        sa, sa_raw = decode_semex_short_alarm_status(vals.get(OIDS.SHORT_ALARM))
        uptime = value_utils.value_to_int(vals.get(OIDS.UPTIME))
        uptime_str = "?" if uptime is None else str(uptime)

        restart = detect_restart(uptime, prev_uptime)
        if uptime is not None:
            prev_uptime = uptime

        current_state = {"alarm1_raw": a1_raw, "alarm2_raw": a2_raw, "short_alarm_raw": sa_raw, "restart": restart}
        changes = []
        if comm == "OK":
            changes = common.detect_changes(prev_state, current_state,
                                            ALARM_KEYS, ALARM_LABELS)
            prev_state = current_state

        prefix = common.build_common_prefix(ts, dev, "alarm", comm)
        line = (f"{prefix} ALARM1={a1} ALARM1_RAW={a1_raw} ALARM2={a2} ALARM2_RAW={a2_raw} "
                f"SHORT_ALARM={sa} SHORT_ALARM_RAW={sa_raw} UPTIME={uptime_str} RESTART={restart}")
        common.emit(log_path, common.append_changes(line, changes))
        await asyncio.sleep(dev["alarm_interval_seconds"])


async def run_semex_cycle(dev):
    client = SnmpClient(allow_write=False)
    transport = None
    prev_state = {}
    cycle_change_log = bool(dev.get("cycle_change_log", False))

    while True:
        ts = common.now_ts()
        log_path = common.get_log_path(dev["name"], dev["ip"])
        try:
            if transport is None:
                transport = await client.make_transport(dev["ip"], dev["port"])
            results, err = await client.get_chunked(
                transport, dev["community"], CYCLE_OIDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            results, err = {o: None for o in CYCLE_OIDS}, "TIMEOUT"

        comm = classify_comm_status(err, results)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            prefix = common.build_common_prefix(ts, dev, "cycle", comm)
            common.emit(log_path, f"{prefix} {CYCLE_FAILURE_SUFFIX}")
            await asyncio.sleep(dev["cycle_interval_seconds"])
            continue

        by_key = {key: results.get(oid) for key, oid in CYCLE_PAIRS}
        phases, rings, channels, coord = build_cycle_summaries(by_key)

        current_state = {"phases": phases, "rings": rings, "channels": channels, "coord": coord}
        changes = []
        if comm == "OK":
            if cycle_change_log:
                changes = common.detect_changes(prev_state, current_state, CYCLE_KEYS, CYCLE_LABELS)
            prev_state = current_state

        prefix = common.build_common_prefix(ts, dev, "cycle", comm)
        line = f"{prefix} PHASES={phases} RINGS={rings} CHANNELS={channels} COORD={coord}"
        common.emit(log_path, common.append_changes(line, changes))
        await asyncio.sleep(dev["cycle_interval_seconds"])


def create_semex_tasks(dev):
    """Registry entry: SEMEX devices run independent 'alarm' and 'cycle' tasks."""
    return [
        asyncio.create_task(run_semex_alarm(dev)),
        asyncio.create_task(run_semex_cycle(dev)),
    ]
