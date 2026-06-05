"""Adapter del VMS NTCIP 1203 v3.

Une el catálogo (`oids.py`), los decoders (`decoders.py`) y la cascada de
config para implementar el contrato `DeviceAdapter`. Una corrida de monitor
sobre un VMS produce una única tarea asyncio (``vms``) que cada
``interval_seconds`` lee el estado y emite una línea al `EvidenceSink`.

Soporta la nota de la migración: la diferencia Daktronics/Chainzone es solo
metadata ahora — un campo opcional ``vendor`` que se incluye en la línea de
log pero no cambia el comportamiento. Los catálogos de OID son idénticos.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional

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


class VmsNtcip1203Adapter(DeviceAdapter):
    """VMS / DMS NTCIP 1203 v3 — lectura periódica de estado y mensaje activo."""

    family = "vms_ntcip1203"

    # -- contrato -----------------------------------------------------------

    def config_schema(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            "name": {
                "type": str,
                "required": True,
                "prompt": "Nombre del panel: ",
                "description": "Identificador del panel (aparece en el log).",
            },
            "ip": {
                "type": str,
                "required": True,
                "prompt": "IP del panel: ",
                "description": "Dirección IPv4 del panel.",
            },
            "port": {
                "type": int,
                "default": 161,
                "prompt": "Puerto SNMP: ",
                "description": "Puerto UDP del agente SNMP (default NTCIP).",
            },
            "community": {
                "type": str,
                "default": "public",
                "prompt": "Community: ",
                "description": "SNMP v2c community string.",
            },
            "interval_seconds": {
                "type": float,
                "default": 60.0,
                "prompt": "Intervalo de polling (s): ",
                "description": "Cada cuántos segundos se relee el estado.",
            },
            "vendor": {
                "type": str,
                "default": None,
                "description": "Metadata informativa: 'daktronics' | 'chainzone' | etc.",
            },
            "type_label": {
                "type": str,
                "default": "VMS_NTCIP1203",
                "description": (
                    "String que se emite en el campo TYPE= del log. Útil para "
                    "preservar la distinción Daktronics/Chainzone histórica."
                ),
            },
        }

    def monitor_tasks(
        self,
        config: Mapping[str, Any],
        sink: EvidenceSink,
    ) -> List[asyncio.Task]:
        client = SnmpClient(allow_write=False)
        return [asyncio.create_task(_run_vms_loop(client, dict(config), sink))]

    async def probe(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        client = SnmpClient(allow_write=False)
        transport = await client.make_transport(config["ip"], int(config.get("port", 161)))
        try:
            return await _read_state_once(client, transport, config["community"])
        finally:
            # SnmpEngine no expone close() asincrónico; se libera con el GC.
            pass


# ---------------------------------------------------------------------------
# Implementación del loop monitor — equivalente al `run_vms` legacy
# ---------------------------------------------------------------------------


def _build_line(config: Mapping[str, Any], comm_status: str, suffix: str) -> str:
    """Construir la línea de log con el mismo layout del poller legacy."""
    return (
        f"[{now_ts()}] "
        f"DEVICE={config['name']} "
        f"TYPE={config.get('type_label', 'VMS_NTCIP1203')} "
        f"IP={config['ip']} "
        f"PORT={config['port']} "
        f"POLL=vms "
        f"COMM_STATUS={comm_status} "
        f"{suffix}"
    )


def _append_changes(line: str, changes: List[str]) -> str:
    if changes:
        return line + " CHANGE=" + ";".join(changes)
    return line


async def _read_active_multi(
    client: SnmpClient,
    transport: Any,
    community: str,
    memory_type: Optional[int],
    message_number: Optional[int],
) -> tuple[Optional[str], str]:
    """GET dmsMessageMultiString. (text, status: ok|read_error|unavailable)."""
    if memory_type is None or message_number is None:
        return None, "unavailable"
    oid = oids.multi_oid(memory_type, message_number)
    val, err = await client.get_one(transport, community, oid)
    if err:
        return None, "read_error"
    if val is None:
        return None, "unavailable"
    return snmp_values.decode_octet_text(val), "ok"


async def _read_state_once(
    client: SnmpClient,
    transport: Any,
    community: str,
) -> Dict[str, Any]:
    """Una iteración completa de lectura (sin loop ni sink). Útil para probe."""
    vals, err = await client.get_many(transport, community, oids.required_oids())
    comm = classify_comm_status(err, vals)
    if comm in ("TIMEOUT", "SNMP_ERROR"):
        return {"comm_status": comm}

    ctrl_str = decoders.decode_control_mode(vals.get(oids.CTRL_MODE))
    src_str = decoders.decode_source_mode(vals.get(oids.SRC_MODE))
    err_str, err_raw = decoders.decode_short_error_status(vals.get(oids.SHORT_ERR))
    mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))

    if mid["valid"]:
        multi_text, multi_status = await _read_active_multi(
            client, transport, community, mid["memory_type"], mid["message_number"]
        )
    else:
        multi_text, multi_status = None, "unavailable"

    return {
        "comm_status": comm,
        "ctrl": ctrl_str,
        "src": src_str,
        "err": err_str,
        "err_raw": err_raw,
        "msg_id": mid,
        "multi": multi_text,
        "multi_status": multi_status,
    }


async def _run_vms_loop(
    client: SnmpClient,
    config: Dict[str, Any],
    sink: EvidenceSink,
) -> None:
    """Loop periódico equivalente al `run_vms` legacy."""
    transport = None
    prev_state: Dict[str, Any] = {}
    interval = float(config.get("interval_seconds", 60.0))

    while True:
        try:
            if transport is None:
                transport = await client.make_transport(config["ip"], int(config["port"]))
            vals, err = await client.get_many(
                transport, config["community"], oids.required_oids()
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            vals, err = {}, "TIMEOUT"

        comm = classify_comm_status(err, vals)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            line = _build_line(config, comm, decoders.FAILURE_SUFFIX)
            sink.write(EvidenceRecord(raw_line=line))
            await asyncio.sleep(interval)
            continue

        ctrl_str = decoders.decode_control_mode(vals.get(oids.CTRL_MODE))
        src_str = decoders.decode_source_mode(vals.get(oids.SRC_MODE))
        err_str, err_raw = decoders.decode_short_error_status(vals.get(oids.SHORT_ERR))
        mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))

        if mid["valid"]:
            multi_text, multi_status = await _read_active_multi(
                client,
                transport,
                config["community"],
                mid["memory_type"],
                mid["message_number"],
            )
        else:
            multi_text, multi_status = None, "unavailable"

        if multi_status == "ok":
            multi_clean = snmp_values.sanitize_one_line(multi_text, decoders.MULTI_MAX_LEN)
            multi_field = f'MULTI="{multi_clean}"'
            multi_state = multi_clean
        elif multi_status == "read_error":
            multi_field, multi_state = "MULTI=read_error", "read_error"
        else:
            multi_field, multi_state = "MULTI=unavailable", "unavailable"

        current_state = {
            "ctrl": ctrl_str,
            "src": src_str,
            "msg": mid["raw_hex"],
            "multi": multi_state,
            "err": err_str,
            "err_raw": err_raw,
        }
        changes: List[str] = []
        if comm == "OK":
            changes = detect_changes(
                prev_state,
                current_state,
                decoders.STATE_KEYS,
                decoders.STATE_LABELS,
                quoted=("multi",),
            )
            prev_state = current_state

        suffix = decoders.build_suffix(
            ctrl_str, src_str, mid["raw_hex"], multi_field, err_str, err_raw
        )
        line = _append_changes(_build_line(config, comm, suffix), changes)
        sink.write(EvidenceRecord(raw_line=line))
        await asyncio.sleep(interval)


__all__ = ["VmsNtcip1203Adapter"]
