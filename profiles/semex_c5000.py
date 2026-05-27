#!/usr/bin/env python3
"""
SEMEX_C5000_V1 profile — SEMEX C5000 traffic signal controller (NTCIP 1202 ASC).

Two independent polling tasks:
    - alarm: unit/short alarm status + uptime (restart detection).
    - cycle: phase/ring/channel status + coordination scalars.

Alarm bit meanings are not yet confirmed, so unit/short alarm values are kept
as raw hex with placeholder decoders. READ-ONLY: GET operations only.
"""

import asyncio

import common

# ---------------------------------------------------------------------------
# Base OID — NTCIP 1202 Actuated Signal Controller
# ---------------------------------------------------------------------------
ASC = "1.3.6.1.4.1.1206.4.2.1"

# Alarm scalars
OID_UNIT_ALARM1 = f"{ASC}.3.7.0"
OID_UNIT_ALARM2 = f"{ASC}.3.8.0"
OID_SHORT_ALARM = f"{ASC}.3.9.0"
OID_UPTIME      = f"{ASC}.1.3.0"

# Coordination scalars
OID_COORD_PATTERN     = f"{ASC}.4.10.0"
OID_COORD_SYS_PATTERN = f"{ASC}.4.14.0"
OID_COORD_LOCAL_FREE  = f"{ASC}.4.11.0"
OID_COORD_CYCLE       = f"{ASC}.4.12.0"
OID_COORD_SYNC        = f"{ASC}.4.13.0"

PHASE_GROUPS = range(1, 5)
RINGS        = range(1, 5)
CHANNELS     = range(1, 5)

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
# OID list builders
# ---------------------------------------------------------------------------
def build_alarm_oids():
    return [OID_UNIT_ALARM1, OID_UNIT_ALARM2, OID_SHORT_ALARM, OID_UPTIME]


def build_cycle_oids():
    """Return ordered (logical_key, oid) pairs for the cycle poll."""
    pairs = []
    for g in PHASE_GROUPS:
        pairs += [
            (f"p{g}_R",  f"{ASC}.1.4.1.2.{g}"),
            (f"p{g}_Y",  f"{ASC}.1.4.1.3.{g}"),
            (f"p{g}_G",  f"{ASC}.1.4.1.4.{g}"),
            (f"p{g}_DW", f"{ASC}.1.4.1.5.{g}"),
            (f"p{g}_W",  f"{ASC}.1.4.1.7.{g}"),
            (f"p{g}_VC", f"{ASC}.1.4.1.8.{g}"),
            (f"p{g}_PC", f"{ASC}.1.4.1.9.{g}"),
            (f"p{g}_ON", f"{ASC}.1.4.1.10.{g}"),
        ]
    for r in RINGS:
        pairs.append((f"r{r}", f"{ASC}.7.6.1.1.{r}"))
    for c in CHANNELS:
        pairs += [
            (f"c{c}_R", f"{ASC}.8.4.1.2.{c}"),
            (f"c{c}_Y", f"{ASC}.8.4.1.3.{c}"),
            (f"c{c}_G", f"{ASC}.8.4.1.4.{c}"),
        ]
    pairs += [
        ("coord_pattern",     OID_COORD_PATTERN),
        ("coord_sys_pattern", OID_COORD_SYS_PATTERN),
        ("coord_local_free",  OID_COORD_LOCAL_FREE),
        ("coord_cycle",       OID_COORD_CYCLE),
        ("coord_sync",        OID_COORD_SYNC),
    ]
    return pairs


CYCLE_PAIRS = build_cycle_oids()
CYCLE_OIDS  = [oid for _, oid in CYCLE_PAIRS]


# ---------------------------------------------------------------------------
# Alarm decoders (placeholders until bit meanings are confirmed)
# ---------------------------------------------------------------------------
def decode_semex_unit_alarm_status1(value):
    """Return (label, raw_hex). 'none' when zero, 'unknown' otherwise."""
    iv = common.value_to_int(value)
    raw = common.raw_hex_padded(value, 4)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def decode_semex_unit_alarm_status2(value):
    iv = common.value_to_int(value)
    raw = common.raw_hex_padded(value, 4)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def decode_semex_short_alarm_status(value):
    iv = common.value_to_int(value)
    raw = common.raw_hex_padded(value, 2)
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
            f"G{g}:R={common.token_hex(by_key.get(f'p{g}_R'))},"
            f"Y={common.token_hex(by_key.get(f'p{g}_Y'))},"
            f"G={common.token_hex(by_key.get(f'p{g}_G'))},"
            f"DW={common.token_hex(by_key.get(f'p{g}_DW'))},"
            f"W={common.token_hex(by_key.get(f'p{g}_W'))},"
            f"VC={common.token_hex(by_key.get(f'p{g}_VC'))},"
            f"PC={common.token_hex(by_key.get(f'p{g}_PC'))},"
            f"ON={common.token_hex(by_key.get(f'p{g}_ON'))}"
        )
    phases = "|".join(phase_parts)

    rings = "|".join(f"R{r}={common.token_hex(by_key.get(f'r{r}'))}" for r in RINGS)

    chan_parts = []
    for c in CHANNELS:
        chan_parts.append(
            f"C{c}:R={common.token_hex(by_key.get(f'c{c}_R'))},"
            f"Y={common.token_hex(by_key.get(f'c{c}_Y'))},"
            f"G={common.token_hex(by_key.get(f'c{c}_G'))}"
        )
    channels = "|".join(chan_parts)

    coord = (f"PATTERN={common.token_int(by_key.get('coord_pattern'))},"
            f"SYS_PATTERN={common.token_int(by_key.get('coord_sys_pattern'))},"
            f"LOCAL_FREE={common.token_int(by_key.get('coord_local_free'))},"
            f"CYCLE={common.token_int(by_key.get('coord_cycle'))},"
            f"SYNC={common.token_int(by_key.get('coord_sync'))}")
    return phases, rings, channels, coord


# ---------------------------------------------------------------------------
# Polling tasks
# ---------------------------------------------------------------------------
async def run_semex_alarm(dev):
    engine = common.new_engine()
    transport = None
    prev_state = {}
    prev_uptime = None
    alarm_oids = build_alarm_oids()

    while True:
        ts = common.now_ts()
        log_path = common.get_log_path(dev["name"], dev["ip"])
        try:
            if transport is None:
                transport = await common.make_transport(dev["ip"], dev["port"])
            vals, err = await common.snmp_get_many(
                engine, transport, dev["community"], alarm_oids)
        except asyncio.CancelledError:
            raise
        except Exception:
            vals, err = {}, "TIMEOUT"

        comm = common.classify_comm_status(err, vals)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            prefix = common.build_common_prefix(ts, dev, "alarm", comm)
            common.emit(log_path, f"{prefix} {ALARM_FAILURE_SUFFIX}")
            await asyncio.sleep(dev["alarm_interval_seconds"])
            continue

        a1, a1_raw = decode_semex_unit_alarm_status1(vals.get(OID_UNIT_ALARM1))
        a2, a2_raw = decode_semex_unit_alarm_status2(vals.get(OID_UNIT_ALARM2))
        sa, sa_raw = decode_semex_short_alarm_status(vals.get(OID_SHORT_ALARM))
        uptime = common.value_to_int(vals.get(OID_UPTIME))
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
    engine = common.new_engine()
    transport = None
    prev_state = {}
    cycle_change_log = bool(dev.get("cycle_change_log", False))

    while True:
        ts = common.now_ts()
        log_path = common.get_log_path(dev["name"], dev["ip"])
        try:
            if transport is None:
                transport = await common.make_transport(dev["ip"], dev["port"])
            results, err = await common.snmp_get_chunked(
                engine, transport, dev["community"], CYCLE_OIDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            results, err = {o: None for o in CYCLE_OIDS}, "TIMEOUT"

        comm = common.classify_comm_status(err, results)

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
