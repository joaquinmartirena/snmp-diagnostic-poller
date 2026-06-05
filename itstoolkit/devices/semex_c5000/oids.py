"""Catálogo de OIDs del SEMEX C5000 (NTCIP 1202 ASC).

Reubicación de `shared/oid_providers/semex_c5000.py`. Sin cambios de valor;
los OIDs son los mismos que el legacy. Mantener este archivo como única
fuente de OIDs del SEMEX dentro del paquete.
"""

from __future__ import annotations

# Base OID — NTCIP 1202 Actuated Signal Controller
ASC = "1.3.6.1.4.1.1206.4.2.1"

# ---------------------------------------------------------------------------
# Alarm scalars
# ---------------------------------------------------------------------------
UNIT_ALARM1 = f"{ASC}.3.7.0"
UNIT_ALARM2 = f"{ASC}.3.8.0"
SHORT_ALARM = f"{ASC}.3.9.0"
UPTIME = f"{ASC}.1.3.0"

# ---------------------------------------------------------------------------
# Coordination scalars
# ---------------------------------------------------------------------------
COORD_PATTERN = f"{ASC}.4.10.0"
COORD_SYS_PATTERN = f"{ASC}.4.14.0"
COORD_LOCAL_FREE = f"{ASC}.4.11.0"
COORD_CYCLE = f"{ASC}.4.12.0"
COORD_SYNC = f"{ASC}.4.13.0"

# ---------------------------------------------------------------------------
# Rangos del cycle poll
# ---------------------------------------------------------------------------
PHASE_GROUPS = range(1, 5)
RINGS = range(1, 5)
CHANNELS = range(1, 5)


def build_alarm_oids() -> list[str]:
    """Escalares polleados por el task `alarm`."""
    return [UNIT_ALARM1, UNIT_ALARM2, SHORT_ALARM, UPTIME]


def build_cycle_oids() -> list[tuple[str, str]]:
    """Pares ordenados (logical_key, oid) para el task `cycle`."""
    pairs: list[tuple[str, str]] = []
    for g in PHASE_GROUPS:
        pairs += [
            (f"p{g}_R", f"{ASC}.1.4.1.2.{g}"),
            (f"p{g}_Y", f"{ASC}.1.4.1.3.{g}"),
            (f"p{g}_G", f"{ASC}.1.4.1.4.{g}"),
            (f"p{g}_DW", f"{ASC}.1.4.1.5.{g}"),
            (f"p{g}_W", f"{ASC}.1.4.1.7.{g}"),
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
        ("coord_pattern", COORD_PATTERN),
        ("coord_sys_pattern", COORD_SYS_PATTERN),
        ("coord_local_free", COORD_LOCAL_FREE),
        ("coord_cycle", COORD_CYCLE),
        ("coord_sync", COORD_SYNC),
    ]
    return pairs


__all__ = [
    "ASC",
    "UNIT_ALARM1",
    "UNIT_ALARM2",
    "SHORT_ALARM",
    "UPTIME",
    "COORD_PATTERN",
    "COORD_SYS_PATTERN",
    "COORD_LOCAL_FREE",
    "COORD_CYCLE",
    "COORD_SYNC",
    "PHASE_GROUPS",
    "RINGS",
    "CHANNELS",
    "build_alarm_oids",
    "build_cycle_oids",
]
