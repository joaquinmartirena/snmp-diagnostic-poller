"""Cleanup post-PoC para el VMS NTCIP 1203.

El runner invoca este helper después de cada scenario si el usuario pasó
``--cleanup-after-each``. La idea: dejar el panel en un estado limpio sin
arrastrar slots de prueba ni acciones huérfanas entre PoCs sucesivos.

Estrategia (defensiva — solo toca lo nuestro):

1. **Slots de mensajes** (rango configurable, default 235-255): para cada
   slot, leer ``dmsMessageOwner``. Si el owner es ``"itstoolkit-poc"`` (la
   firma que `_activation.load_message_into_slot` deja), libera el slot
   con ``dmsMessageStatus = notUsedReq``. Si el owner es cualquier otra
   cosa, NO TOCA (puede ser un slot operativo del cliente).

2. **dmsActionTable**: para cada ``action_index`` configurado (default
   ``[2]``, que es el que usan POC-07/08), escribe el MessageIDCode "todo
   ceros" — equivale al ``DEFVAL`` documentado en la norma, desacopla la
   acción de cualquier slot.

3. **Blank de pantalla**: activa un mensaje ``blank`` (``memType=blank(7)
   / msgNum=priority / CRC=0x0000``) para que la pantalla quede limpia y
   no se quede mostrando el último MULTI de prueba.

El cleanup emite records en el mismo JSONL del scenario que lo disparó
(prefijo ``cleanup.``), así la evidencia de cada PoC incluye qué se
limpió y qué se preservó.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping

from pysnmp.proto.rfc1902 import Integer, OctetString

from itstoolkit.core.scenario import ScenarioContext

from .. import decoders, oids
from . import _activation


# Marca que `_activation.load_message_into_slot` escribe en dmsMessageOwner.
# Solo limpiamos slots cuyo owner coincida con esto.
OWNER_SIGNATURE = "itstoolkit-poc"

# Rango default de slots a inspeccionar. Cubre el rango que usan POCs 5-21.
DEFAULT_SLOT_RANGE = range(235, 256)  # 235 inclusive .. 255 inclusive

# Action_index default que usan POC-07/08.
DEFAULT_ACTION_INDEXES: List[int] = [2]


async def cleanup_vms_panel(
    ctx: ScenarioContext,
    *,
    slot_range: Iterable[int] = DEFAULT_SLOT_RANGE,
    action_indexes: Iterable[int] = DEFAULT_ACTION_INDEXES,
    blank_priority: int = 32,
) -> Mapping[str, Any]:
    """Limpiar slots de prueba + tabla de acciones + pantalla en blanco.

    Devuelve un dict con el resumen para que el caller (el runner) lo
    incluya en el record final.
    """
    slot_list = list(slot_range)
    action_list = list(action_indexes)

    freed_slots: List[int] = []
    preserved_slots: List[int] = []  # owner != itstoolkit-poc
    empty_slots: List[int] = []  # ya estaban en notUsed
    failed_slots: List[int] = []

    # Paso 1 — recorrer los slots
    for slot in slot_list:
        owner_oid = _activation.row_oid(
            oids.DMS_MSG_OWNER_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )
        status_oid = _activation.row_oid(
            oids.DMS_MSG_STATUS_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )

        # Lectura conjunta de owner + status para minimizar PDUs
        vals, err = await ctx.snmp.get_many([owner_oid, status_oid])
        if err in ("TIMEOUT", "SNMP_ERROR"):
            failed_slots.append(slot)
            continue

        owner_raw = vals.get(owner_oid)
        status_raw = vals.get(status_oid)
        try:
            status_value = int(status_raw) if status_raw is not None else None
        except Exception:
            status_value = None

        if status_value == oids.MSG_STATUS_NOT_USED:
            empty_slots.append(slot)
            continue

        owner_text = _decode_owner(owner_raw)
        if owner_text != OWNER_SIGNATURE:
            preserved_slots.append(slot)
            continue

        # Liberar: SET dmsMessageStatus = notUsedReq.
        _, set_err = await ctx.snmp.set_one(
            status_oid, Integer(oids.MSG_STATUS_NOT_USED_REQ)
        )
        if set_err is not None:
            failed_slots.append(slot)
        else:
            freed_slots.append(slot)

    ctx.record_step(
        "cleanup.scan_slots",
        operation="VERIFY",
        value_read={
            "slot_range": [slot_list[0], slot_list[-1]] if slot_list else [],
            "freed": freed_slots,
            "already_empty": empty_slots,
            "preserved_other_owner": preserved_slots,
            "failed": failed_slots,
        },
        success=not failed_slots,
    )

    # Paso 2 — resetear dmsActionMsgCode
    zero_msg_id = b"\x00" * 5  # memType(1) + msgNum(2) + CRC(2) = 5 zeros
    cleared_actions: List[int] = []
    failed_actions: List[int] = []
    for idx in action_list:
        action_oid = f"{oids.DMS_ACTION_MSG_CODE_COL}.{idx}"
        _, err = await ctx.snmp.set_one(action_oid, OctetString(zero_msg_id))
        if err is None:
            cleared_actions.append(idx)
        else:
            failed_actions.append(idx)
    ctx.record_step(
        "cleanup.reset_actions",
        operation="SNMP_SET",
        oid_name="dmsActionMsgCode",
        value_read={"cleared": cleared_actions, "failed": failed_actions},
        success=not failed_actions,
    )

    # Paso 3 — blank pantalla
    blank_code = _activation.build_activation_code(
        duration_minutes=65535,
        activate_priority=blank_priority,
        memory_type=oids.MEM_TYPE_BLANK,
        message_number=blank_priority,  # NTCIP §5.1: msgNum = priority
        message_crc=b"\x00\x00",
    )
    _, blank_err = await ctx.snmp.set_one(
        oids.DMS_ACTIVATE_MESSAGE, OctetString(blank_code)
    )
    ctx.record_step(
        "cleanup.blank_sign",
        operation="SNMP_SET",
        oid_name="dmsActivateMessage",
        value_read={"memType": "blank(7)", "code_hex": blank_code.hex().upper()},
        success=blank_err is None,
        error=blank_err,
    )

    return {
        "slots_freed": freed_slots,
        "slots_already_empty": empty_slots,
        "slots_preserved": preserved_slots,
        "slots_failed": failed_slots,
        "actions_cleared": cleared_actions,
        "actions_failed": failed_actions,
        "sign_blanked": blank_err is None,
    }


def _decode_owner(raw: Any) -> str:
    """OCTET STRING del owner → str. Devuelve '' si no decodifica."""
    if raw is None:
        return ""
    if hasattr(raw, "asOctets"):
        try:
            return bytes(raw.asOctets()).decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
    return str(raw).strip()


__all__ = [
    "cleanup_vms_panel",
    "OWNER_SIGNATURE",
    "DEFAULT_SLOT_RANGE",
    "DEFAULT_ACTION_INDEXES",
]
