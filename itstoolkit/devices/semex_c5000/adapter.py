"""Adapter del SEMEX C5000.

Es el segundo dispositivo migrado y por tanto el test real del contrato
`DeviceAdapter`. A diferencia del VMS, expone **dos tareas** asyncio en
``monitor_tasks``: ``alarm`` (estado y restart detection) y ``cycle``
(estado de fases/rings/channels + coordinación). Ambas son independientes
y comparten solo el dispositivo y el sink.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping

from itstoolkit.core.device import DeviceAdapter
from itstoolkit.core.evidence import (
    EvidenceRecord,
    EvidenceSink,
    detect_changes,
    now_ts,
)
from itstoolkit.protocols.snmp import values as snmp_values
from itstoolkit.protocols.snmp.client import SnmpClient, classify_comm_status

from . import decoders, oids


class SemexC5000Adapter(DeviceAdapter):
    """SEMEX C5000 — NTCIP 1202 ASC (Actuated Signal Controller)."""

    family = "semex_c5000"

    # -- contrato -----------------------------------------------------------

    def config_schema(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            "name": {
                "type": str,
                "required": True,
                "prompt": "Nombre del controlador: ",
            },
            "ip": {"type": str, "required": True, "prompt": "IP: "},
            "port": {"type": int, "default": 161, "prompt": "Puerto SNMP: "},
            "community": {
                "type": str,
                "default": "public",
                "prompt": "Community: ",
            },
            "alarm_interval_seconds": {
                "type": float,
                "default": 30.0,
                "prompt": "Intervalo alarm (s): ",
            },
            "cycle_interval_seconds": {
                "type": float,
                "default": 2.0,
                "prompt": "Intervalo cycle (s): ",
            },
            "cycle_change_log": {
                "type": bool,
                "default": False,
                "description": "Si True, el task cycle emite CHANGE=... entre polls.",
            },
            "vendor": {"type": str, "default": None},
            "type_label": {"type": str, "default": "SEMEX_C5000_V1"},
            "confirm_write": {
                "type": bool,
                "default": False,
                "description": (
                    "Mitad-config del doble gate de WriteGuard. El SEMEX hoy "
                    "no expone escenarios con escritura, pero la clave es "
                    "reconocida en config para mantener simetría con VMS."
                ),
            },
        }

    def monitor_tasks(
        self,
        config: Mapping[str, Any],
        sink: EvidenceSink,
    ) -> List[asyncio.Task]:
        client_alarm = SnmpClient(allow_write=False)
        client_cycle = SnmpClient(allow_write=False)
        cfg = dict(config)
        return [
            asyncio.create_task(_run_alarm_loop(client_alarm, cfg, sink)),
            asyncio.create_task(_run_cycle_loop(client_cycle, cfg, sink)),
        ]

    async def probe(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        client = SnmpClient(allow_write=False)
        transport = await client.make_transport(
            config["ip"], int(config.get("port", 161))
        )
        return await _read_state_once(client, transport, config["community"])


# ---------------------------------------------------------------------------
# Helpers de líneas (mismo layout del poller legacy)
# ---------------------------------------------------------------------------


def _build_line(
    config: Mapping[str, Any], poll: str, comm_status: str, suffix: str
) -> str:
    return (
        f"[{now_ts()}] "
        f"DEVICE={config['name']} "
        f"TYPE={config.get('type_label', 'SEMEX_C5000_V1')} "
        f"IP={config['ip']} "
        f"PORT={config['port']} "
        f"POLL={poll} "
        f"COMM_STATUS={comm_status} "
        f"{suffix}"
    )


def _append_changes(line: str, changes: List[str]) -> str:
    if changes:
        return line + " CHANGE=" + ";".join(changes)
    return line


# ---------------------------------------------------------------------------
# probe one-shot — solo alarm + uptime
# ---------------------------------------------------------------------------


async def _read_state_once(
    client: SnmpClient,
    transport: Any,
    community: str,
) -> Dict[str, Any]:
    vals, err = await client.get_many(transport, community, oids.build_alarm_oids())
    comm = classify_comm_status(err, vals)
    if comm in ("TIMEOUT", "SNMP_ERROR"):
        return {"comm_status": comm}
    a1, a1_raw = decoders.decode_unit_alarm_status1(vals.get(oids.UNIT_ALARM1))
    a2, a2_raw = decoders.decode_unit_alarm_status2(vals.get(oids.UNIT_ALARM2))
    sa, sa_raw = decoders.decode_short_alarm_status(vals.get(oids.SHORT_ALARM))
    uptime = snmp_values.value_to_int(vals.get(oids.UPTIME))
    return {
        "comm_status": comm,
        "alarm1": a1,
        "alarm1_raw": a1_raw,
        "alarm2": a2,
        "alarm2_raw": a2_raw,
        "short_alarm": sa,
        "short_alarm_raw": sa_raw,
        "uptime": uptime,
    }


# ---------------------------------------------------------------------------
# Task `alarm`
# ---------------------------------------------------------------------------


async def _run_alarm_loop(
    client: SnmpClient,
    config: Dict[str, Any],
    sink: EvidenceSink,
) -> None:
    transport = None
    prev_state: Dict[str, Any] = {}
    prev_uptime = None
    interval = float(config.get("alarm_interval_seconds", 30.0))
    alarm_oids = oids.build_alarm_oids()

    while True:
        try:
            if transport is None:
                transport = await client.make_transport(
                    config["ip"], int(config["port"])
                )
            vals, err = await client.get_many(
                transport, config["community"], alarm_oids
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            vals, err = {}, "TIMEOUT"

        comm = classify_comm_status(err, vals)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            line = _build_line(config, "alarm", comm, decoders.ALARM_FAILURE_SUFFIX)
            sink.write(EvidenceRecord(raw_line=line))
            await asyncio.sleep(interval)
            continue

        a1, a1_raw = decoders.decode_unit_alarm_status1(vals.get(oids.UNIT_ALARM1))
        a2, a2_raw = decoders.decode_unit_alarm_status2(vals.get(oids.UNIT_ALARM2))
        sa, sa_raw = decoders.decode_short_alarm_status(vals.get(oids.SHORT_ALARM))
        uptime = snmp_values.value_to_int(vals.get(oids.UPTIME))
        uptime_str = "?" if uptime is None else str(uptime)

        restart = decoders.detect_restart(uptime, prev_uptime)
        if uptime is not None:
            prev_uptime = uptime

        current_state = {
            "alarm1_raw": a1_raw,
            "alarm2_raw": a2_raw,
            "short_alarm_raw": sa_raw,
            "restart": restart,
        }
        changes: List[str] = []
        if comm == "OK":
            changes = detect_changes(
                prev_state, current_state, decoders.ALARM_KEYS, decoders.ALARM_LABELS
            )
            prev_state = current_state

        suffix = (
            f"ALARM1={a1} ALARM1_RAW={a1_raw} ALARM2={a2} ALARM2_RAW={a2_raw} "
            f"SHORT_ALARM={sa} SHORT_ALARM_RAW={sa_raw} "
            f"UPTIME={uptime_str} RESTART={restart}"
        )
        line = _append_changes(_build_line(config, "alarm", comm, suffix), changes)
        sink.write(EvidenceRecord(raw_line=line))
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Task `cycle`
# ---------------------------------------------------------------------------


async def _run_cycle_loop(
    client: SnmpClient,
    config: Dict[str, Any],
    sink: EvidenceSink,
) -> None:
    transport = None
    prev_state: Dict[str, Any] = {}
    cycle_change_log = bool(config.get("cycle_change_log", False))
    interval = float(config.get("cycle_interval_seconds", 2.0))
    cycle_pairs = oids.build_cycle_oids()
    cycle_oids = [oid for _, oid in cycle_pairs]

    while True:
        try:
            if transport is None:
                transport = await client.make_transport(
                    config["ip"], int(config["port"])
                )
            results, err = await client.get_chunked(
                transport, config["community"], cycle_oids
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            results, err = {o: None for o in cycle_oids}, "TIMEOUT"

        comm = classify_comm_status(err, results)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            line = _build_line(config, "cycle", comm, decoders.CYCLE_FAILURE_SUFFIX)
            sink.write(EvidenceRecord(raw_line=line))
            await asyncio.sleep(interval)
            continue

        by_key = {key: results.get(oid) for key, oid in cycle_pairs}
        phases, rings, channels, coord = decoders.build_cycle_summaries(by_key)

        current_state = {
            "phases": phases,
            "rings": rings,
            "channels": channels,
            "coord": coord,
        }
        changes: List[str] = []
        if comm == "OK":
            if cycle_change_log:
                changes = detect_changes(
                    prev_state,
                    current_state,
                    decoders.CYCLE_KEYS,
                    decoders.CYCLE_LABELS,
                )
            prev_state = current_state

        suffix = (
            f"PHASES={phases} RINGS={rings} CHANNELS={channels} COORD={coord}"
        )
        line = _append_changes(_build_line(config, "cycle", comm, suffix), changes)
        sink.write(EvidenceRecord(raw_line=line))
        await asyncio.sleep(interval)


__all__ = ["SemexC5000Adapter"]
