"""Decoders del SEMEX C5000.

Copia funcional 1-a-1 de los decoders y builders que vivían en
`polling/profiles/semex_c5000.py`. Las significaciones de bits de alarma no
están confirmadas todavía; se mantienen los placeholders ``none``/``unknown``
del legacy.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from itstoolkit.protocols.snmp import values as snmp_values

from . import oids


# ---------------------------------------------------------------------------
# Change-detection keys
# ---------------------------------------------------------------------------
ALARM_KEYS = ["alarm1_raw", "alarm2_raw", "short_alarm_raw", "restart"]
ALARM_LABELS = {
    "alarm1_raw": "ALARM1_RAW",
    "alarm2_raw": "ALARM2_RAW",
    "short_alarm_raw": "SHORT_ALARM_RAW",
    "restart": "RESTART",
}

CYCLE_KEYS = ["phases", "rings", "channels", "coord"]
CYCLE_LABELS = {
    "phases": "PHASES",
    "rings": "RINGS",
    "channels": "CHANNELS",
    "coord": "COORD",
}

ALARM_FAILURE_SUFFIX = (
    "ALARM1=? ALARM1_RAW=? ALARM2=? ALARM2_RAW=? "
    "SHORT_ALARM=? SHORT_ALARM_RAW=? UPTIME=? RESTART=?"
)
CYCLE_FAILURE_SUFFIX = "PHASES=? RINGS=? CHANNELS=? COORD=?"


# ---------------------------------------------------------------------------
# Alarm decoders (placeholders hasta que se confirmen los bits)
# ---------------------------------------------------------------------------


def decode_unit_alarm_status1(value: Any) -> Tuple[str, str]:
    iv = snmp_values.value_to_int(value)
    raw = snmp_values.raw_hex_padded(value, 4)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def decode_unit_alarm_status2(value: Any) -> Tuple[str, str]:
    iv = snmp_values.value_to_int(value)
    raw = snmp_values.raw_hex_padded(value, 4)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def decode_short_alarm_status(value: Any) -> Tuple[str, str]:
    iv = snmp_values.value_to_int(value)
    raw = snmp_values.raw_hex_padded(value, 2)
    if iv is None:
        return "?", raw
    return ("none" if iv == 0 else "unknown"), raw


def detect_restart(uptime: Any, prev_uptime: Any) -> str:
    """``unknown`` | ``no`` | ``detected`` según regresión del uptime."""
    if uptime is None or prev_uptime is None:
        return "unknown"
    return "detected" if uptime < prev_uptime else "no"


# ---------------------------------------------------------------------------
# Cycle summary builders
# ---------------------------------------------------------------------------


def build_cycle_summaries(by_key: Mapping[str, Any]) -> Tuple[str, str, str, str]:
    """``by_key`` mapea logical_key → pysnmp value. Devuelve los 4 strings."""
    phase_parts = []
    for g in oids.PHASE_GROUPS:
        phase_parts.append(
            f"G{g}:R={snmp_values.token_hex(by_key.get(f'p{g}_R'))},"
            f"Y={snmp_values.token_hex(by_key.get(f'p{g}_Y'))},"
            f"G={snmp_values.token_hex(by_key.get(f'p{g}_G'))},"
            f"DW={snmp_values.token_hex(by_key.get(f'p{g}_DW'))},"
            f"W={snmp_values.token_hex(by_key.get(f'p{g}_W'))},"
            f"VC={snmp_values.token_hex(by_key.get(f'p{g}_VC'))},"
            f"PC={snmp_values.token_hex(by_key.get(f'p{g}_PC'))},"
            f"ON={snmp_values.token_hex(by_key.get(f'p{g}_ON'))}"
        )
    phases = "|".join(phase_parts)

    rings = "|".join(
        f"R{r}={snmp_values.token_hex(by_key.get(f'r{r}'))}" for r in oids.RINGS
    )

    chan_parts = []
    for c in oids.CHANNELS:
        chan_parts.append(
            f"C{c}:R={snmp_values.token_hex(by_key.get(f'c{c}_R'))},"
            f"Y={snmp_values.token_hex(by_key.get(f'c{c}_Y'))},"
            f"G={snmp_values.token_hex(by_key.get(f'c{c}_G'))}"
        )
    channels = "|".join(chan_parts)

    coord = (
        f"PATTERN={snmp_values.token_int(by_key.get('coord_pattern'))},"
        f"SYS_PATTERN={snmp_values.token_int(by_key.get('coord_sys_pattern'))},"
        f"LOCAL_FREE={snmp_values.token_int(by_key.get('coord_local_free'))},"
        f"CYCLE={snmp_values.token_int(by_key.get('coord_cycle'))},"
        f"SYNC={snmp_values.token_int(by_key.get('coord_sync'))}"
    )
    return phases, rings, channels, coord


__all__ = [
    "ALARM_KEYS",
    "ALARM_LABELS",
    "CYCLE_KEYS",
    "CYCLE_LABELS",
    "ALARM_FAILURE_SUFFIX",
    "CYCLE_FAILURE_SUFFIX",
    "decode_unit_alarm_status1",
    "decode_unit_alarm_status2",
    "decode_short_alarm_status",
    "detect_restart",
    "build_cycle_summaries",
]
