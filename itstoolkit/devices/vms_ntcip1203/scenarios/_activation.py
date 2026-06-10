"""Helpers de activación de mensajes para los escenarios POC-VMS 05-09.

Encapsulan el "ritual" estándar NTCIP 1203 de:

1. Reservar un slot (``dmsMessageStatus = modifyReq`` → ``modifying``).
2. Escribir ``dmsMessageMultiString`` + ``dmsMessageOwner`` +
    ``dmsMessageRunTimePriority`` + (opcional) ``dmsMessageBeacon`` +
    ``dmsMessagePixelService``.
3. Validar (``dmsMessageStatus = validateReq`` → ``valid``).
4. Leer ``dmsMessageCRC`` calculado por el panel.
5. Construir el ``MessageActivationCode`` (12 bytes) usando el CRC del panel
    y disparar ``dmsActivateMessage``.
6. Leer ``dmsActivateMsgError`` para verificar resultado.

Esta lógica vive separada de las clases ``Scenario`` para que POC-05/06/09
puedan compartirla sin duplicarla. Cada paso emite un ``record_step``
detallado al sink — la evidencia documenta tanto los valores que se
escribieron como los que el panel devolvió.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from pysnmp.proto.rfc1902 import Integer, OctetString

from itstoolkit.core.scenario import ScenarioContext

from .. import decoders, oids


# ---------------------------------------------------------------------------
# Construcción del MessageActivationCode (12 bytes OER-encoded)
# ---------------------------------------------------------------------------


def build_activation_code(
    *,
    duration_minutes: int,
    activate_priority: int,
    memory_type: int,
    message_number: int,
    message_crc: bytes,
    source_address: bytes = b"\x7f\x00\x00\x01",
) -> bytes:
    """Construir el ``MessageActivationCode`` (12 bytes).

    Layout (NTCIP 1203 §5.1, MessageActivationCodeStructure):

    - duration (16b BE)
    - activatePriority (8b)
    - messageMemoryType (8b)
    - messageNumber (16b BE)
    - messageCRC (16b, octets como vienen del panel)
    - sourceAddress (32b, IP en orden de red)
    """
    if not 0 <= duration_minutes <= 0xFFFF:
        raise ValueError(f"duration_minutes out of range: {duration_minutes}")
    if not 0 <= activate_priority <= 0xFF:
        raise ValueError(f"activate_priority out of range: {activate_priority}")
    if not 0 <= memory_type <= 0xFF:
        raise ValueError(f"memory_type out of range: {memory_type}")
    if not 0 <= message_number <= 0xFFFF:
        raise ValueError(f"message_number out of range: {message_number}")
    if len(message_crc) != 2:
        raise ValueError(f"message_crc must be 2 bytes, got {len(message_crc)}")
    if len(source_address) != 4:
        raise ValueError(
            f"source_address must be 4 bytes, got {len(source_address)}"
        )
    return (
        duration_minutes.to_bytes(2, "big")
        + bytes([activate_priority])
        + bytes([memory_type])
        + message_number.to_bytes(2, "big")
        + bytes(message_crc)
        + bytes(source_address)
    )


def row_oid(column_oid: str, memory_type: int, message_number: int) -> str:
    """OID completo de una columna del ``dmsMessageTable`` indexada por slot."""
    return f"{column_oid}.{memory_type}.{message_number}"


# ---------------------------------------------------------------------------
# State-machine de dmsMessageStatus
# ---------------------------------------------------------------------------


async def _wait_message_status(
    ctx: ScenarioContext,
    *,
    memory_type: int,
    message_number: int,
    desired_state: int,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.2,
) -> Tuple[Optional[int], Optional[str]]:
    """Polling de ``dmsMessageStatus.x.y`` hasta llegar al estado deseado.

    Devuelve ``(state_value, error)``: ``error`` es ``"TIMEOUT"`` si no se
    alcanzó el estado en la ventana, o el código SNMP si la lectura falló.
    """
    status_oid = row_oid(
        oids.DMS_MSG_STATUS_COL, memory_type, message_number
    )
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_val: Optional[int] = None
    # Terminal states: si la máquina cae acá no hay forma de llegar al
    # desired. Salimos al toque con el estado terminal para no consumir el
    # timeout completo (relevante p.ej. cuando validateReq lleva a error(5)).
    TERMINAL_STATES = {
        oids.MSG_STATUS_ERROR,  # 5 — validación falló
    }
    while True:
        val, err = await ctx.snmp.get_one(status_oid)
        if err is not None:
            return None, err
        try:
            last_val = int(val) if val is not None else None
        except Exception:
            last_val = None
        if last_val == desired_state:
            return last_val, None
        if last_val in TERMINAL_STATES and last_val != desired_state:
            return last_val, f"TERMINAL_STATE_{last_val}"
        if asyncio.get_event_loop().time() >= deadline:
            return last_val, "TIMEOUT_WAITING_STATE"
        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Ritual de carga del slot (write multi + estado válido)
# ---------------------------------------------------------------------------


@dataclass
class LoadedMessage:
    """Snapshot de un mensaje cargado y validado en un slot."""

    memory_type: int
    message_number: int
    multi: str
    run_time_priority: int
    crc: bytes  # 2 bytes leídos del panel
    status: int


async def load_message_into_slot(
    ctx: ScenarioContext,
    *,
    memory_type: int,
    message_number: int,
    multi: str,
    run_time_priority: int,
    owner: str = "itstoolkit-poc",
    beacon: int = 0,
    pixel_service: int = 0,
) -> Tuple[Optional[LoadedMessage], Optional[str]]:
    """Cargar un MULTI en un slot siguiendo el state machine NTCIP 1203 §A.3.

    Devuelve ``(LoadedMessage, None)`` en éxito o ``(None, reason)``.
    Cada paso emite un record en el sink (incluyendo SETs con valor escrito).
    """
    multi_str_oid = row_oid(
        oids.DMS_MSG_MULTI_STRING_COL, memory_type, message_number
    )
    owner_oid = row_oid(oids.DMS_MSG_OWNER_COL, memory_type, message_number)
    priority_oid = row_oid(
        oids.DMS_MSG_RUN_TIME_PRIORITY_COL, memory_type, message_number
    )
    beacon_oid = row_oid(oids.DMS_MSG_BEACON_COL, memory_type, message_number)
    pixel_oid = row_oid(
        oids.DMS_MSG_PIXEL_SERVICE_COL, memory_type, message_number
    )
    status_oid = row_oid(oids.DMS_MSG_STATUS_COL, memory_type, message_number)
    crc_oid = row_oid(oids.DMS_MSG_CRC_COL, memory_type, message_number)

    # Paso A — pasar el slot a 'modifying' vía modifyReq
    _, err = await ctx.snmp.set_one(
        status_oid, Integer(oids.MSG_STATUS_MODIFY_REQ)
    )
    ctx.record_step(
        "load_msg.set_status_modifyReq",
        operation="SNMP_SET",
        oid_name="dmsMessageStatus",
        oid=status_oid,
        value_read=oids.MSG_STATUS_MODIFY_REQ,
        success=err is None,
        error=err,
    )
    if err is not None:
        return None, f"set_modifyReq:{err}"

    state, err = await _wait_message_status(
        ctx,
        memory_type=memory_type,
        message_number=message_number,
        desired_state=oids.MSG_STATUS_MODIFYING,
    )
    ctx.record_step(
        "load_msg.wait_modifying",
        operation="SNMP_GET",
        oid_name="dmsMessageStatus",
        oid=status_oid,
        value_read=decoders.decode_message_status(state),
        success=err is None,
        error=err,
    )
    if err is not None:
        return None, f"wait_modifying:{err}"

    # Paso B — escribir contenido del slot
    varbinds = [
        (multi_str_oid, OctetString(multi.encode("utf-8"))),
        (owner_oid, OctetString(owner.encode("utf-8"))),
        (priority_oid, Integer(int(run_time_priority))),
        (beacon_oid, Integer(int(beacon))),
        (pixel_oid, Integer(int(pixel_service))),
    ]
    _, err = await ctx.snmp.set_many(varbinds)
    ctx.record_step(
        "load_msg.set_contents",
        operation="SNMP_SET",
        oid_name="dmsMessageMultiString+owner+priority+beacon+pixelService",
        oid=multi_str_oid,
        value_read={
            "multi": multi,
            "owner": owner,
            "runTimePriority": run_time_priority,
            "beacon": beacon,
            "pixelService": pixel_service,
        },
        success=err is None,
        error=err,
    )
    if err is not None:
        return None, f"set_contents:{err}"

    # Paso C — validar (validateReq → validating → valid)
    _, err = await ctx.snmp.set_one(
        status_oid, Integer(oids.MSG_STATUS_VALIDATE_REQ)
    )
    ctx.record_step(
        "load_msg.set_status_validateReq",
        operation="SNMP_SET",
        oid_name="dmsMessageStatus",
        oid=status_oid,
        value_read=oids.MSG_STATUS_VALIDATE_REQ,
        success=err is None,
        error=err,
    )
    if err is not None:
        return None, f"set_validateReq:{err}"

    state, err = await _wait_message_status(
        ctx,
        memory_type=memory_type,
        message_number=message_number,
        desired_state=oids.MSG_STATUS_VALID,
        timeout_seconds=10.0,
    )
    ctx.record_step(
        "load_msg.wait_valid",
        operation="SNMP_GET",
        oid_name="dmsMessageStatus",
        oid=status_oid,
        value_read=decoders.decode_message_status(state),
        success=err is None and state == oids.MSG_STATUS_VALID,
        error=err if err else (None if state == oids.MSG_STATUS_VALID else "not_valid"),
    )
    if err is not None or state != oids.MSG_STATUS_VALID:
        return None, f"validate_failed:state={state} err={err}"

    # Paso D — leer el CRC calculado por el panel
    crc_val, err = await ctx.snmp.get_one(crc_oid)
    if err is not None or crc_val is None:
        ctx.record_step(
            "load_msg.read_crc",
            operation="SNMP_GET",
            oid_name="dmsMessageCRC",
            oid=crc_oid,
            value_read=None,
            success=False,
            error=err or "NoSuchObject",
        )
        return None, f"read_crc:{err or 'NoSuchObject'}"

    crc_bytes = _coerce_crc_bytes(crc_val)
    ctx.record_step(
        "load_msg.read_crc",
        operation="SNMP_GET",
        oid_name="dmsMessageCRC",
        oid=crc_oid,
        value_read=crc_bytes.hex().upper(),
        success=True,
    )

    return (
        LoadedMessage(
            memory_type=memory_type,
            message_number=message_number,
            multi=multi,
            run_time_priority=run_time_priority,
            crc=crc_bytes,
            status=oids.MSG_STATUS_VALID,
        ),
        None,
    )


def _coerce_crc_bytes(raw: Any) -> bytes:
    """Normalizar dmsMessageCRC a 2 bytes (panel puede devolver int u OCTET)."""
    if hasattr(raw, "asOctets"):
        b = bytes(raw.asOctets())
        return b[-2:].rjust(2, b"\x00")
    try:
        return int(raw).to_bytes(2, "big")
    except Exception:
        return b"\x00\x00"


# ---------------------------------------------------------------------------
# Activación
# ---------------------------------------------------------------------------


async def activate_message(
    ctx: ScenarioContext,
    *,
    loaded: LoadedMessage,
    duration_minutes: int = 65535,
    activate_priority: Optional[int] = None,
) -> Tuple[Optional[str], Optional[int]]:
    """Disparar ``dmsActivateMessage`` y leer ``dmsActivateMsgError``.

    Devuelve ``(activate_error_text, activate_error_value)``. ``"none(2)"`` =
    éxito; cualquier otro = el panel rechazó la activación.
    """
    code = build_activation_code(
        duration_minutes=duration_minutes,
        activate_priority=(
            activate_priority
            if activate_priority is not None
            else loaded.run_time_priority
        ),
        memory_type=loaded.memory_type,
        message_number=loaded.message_number,
        message_crc=loaded.crc,
    )
    _, set_err = await ctx.snmp.set_one(
        oids.DMS_ACTIVATE_MESSAGE, OctetString(code)
    )
    ctx.record_step(
        "activate.set_activate_message",
        operation="SNMP_SET",
        oid_name="dmsActivateMessage",
        oid=oids.DMS_ACTIVATE_MESSAGE,
        value_read=code.hex().upper(),
        # genErr en el SET es esperado cuando el panel rechaza por prioridad,
        # CRC, modo, etc. — NO lo marcamos como fallo del step, dejamos que
        # la lectura de dmsActivateMsgError diga el motivo (NTCIP 1203 §5.7.3).
        success=True,
        notes=f"snmp_set_result={set_err or 'ok'}",
        duration_minutes=duration_minutes,
        activate_priority=(
            activate_priority
            if activate_priority is not None
            else loaded.run_time_priority
        ),
        memory_type=loaded.memory_type,
        message_number=loaded.message_number,
    )

    # Leer dmsActivateMsgError SIEMPRE — la norma garantiza que el panel
    # actualiza este OID antes de devolver el genErr.
    raw_err, get_err = await ctx.snmp.get_one(oids.DMS_ACTIVATE_MSG_ERROR)
    err_text = decoders.decode_activate_msg_error(raw_err)
    try:
        err_value = int(raw_err) if raw_err is not None else None
    except Exception:
        err_value = None
    ctx.record_step(
        "activate.read_activate_msg_error",
        operation="SNMP_GET",
        oid_name="dmsActivateMsgError",
        oid=oids.DMS_ACTIVATE_MSG_ERROR,
        value_read=err_text,
        success=get_err is None,
        error=get_err,
        snmp_set_result=set_err,
    )
    if get_err is not None:
        # Solo aquí sí es un fallo de transporte real: ni siquiera pudimos
        # leer el motivo del rechazo.
        return f"snmp_error:{get_err}", None
    return err_text, err_value


__all__ = [
    "build_activation_code",
    "row_oid",
    "LoadedMessage",
    "load_message_into_slot",
    "activate_message",
]
