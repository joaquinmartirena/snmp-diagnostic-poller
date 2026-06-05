"""Decoders del VMS NTCIP 1203 v3.

Traducen los valores crudos de pysnmp a la semántica de dominio (modo de
control, modo de fuente, bits de error, message ID). Copia funcional 1-a-1
de los decoders que vivían en `polling/profiles/vms_ntcip1203.py`, ahora
cohesionados con el catálogo de OIDs y el adapter del mismo dispositivo.

Cualquier cambio funcional acá altera el log del monitor — no hacerlo durante
la migración.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from itstoolkit.protocols.snmp import values as snmp_values


MULTI_MAX_LEN = 500

# Cambios entre polls — claves y labels del log line.
STATE_KEYS = ["ctrl", "src", "msg", "multi", "err", "err_raw"]
STATE_LABELS = {
    "ctrl": "CTRL",
    "src": "SRC",
    "msg": "MSG",
    "multi": "MULTI",
    "err": "ERR",
    "err_raw": "ERR_RAW",
}

FAILURE_SUFFIX = "CTRL=? SRC=? MSG=? MULTI=? ERR=? ERR_RAW=?"


# ---------------------------------------------------------------------------
# dmsControlMode
# ---------------------------------------------------------------------------


def decode_control_mode(raw: Any) -> str:
    try:
        v = int(raw)
    except Exception:
        return f"unknown({raw})"
    mapping = {2: "local", 4: "central", 5: "centralOverride"}
    return f"{mapping.get(v, 'unknown')}({v})"


# ---------------------------------------------------------------------------
# dmsMessageSourceMode
# ---------------------------------------------------------------------------


def decode_source_mode(raw: Any) -> str:
    try:
        v = int(raw)
    except Exception:
        return f"unknown({raw})"
    mapping = {
        8: "central",
        9: "timebasedScheduler",
        10: "powerRecovery",
        11: "reset",
        12: "commLoss",
        13: "powerLoss",
        14: "endDuration",
    }
    return f"{mapping.get(v, 'unknown')}({v})"


# ---------------------------------------------------------------------------
# shortErrorStatus
# ---------------------------------------------------------------------------

SHORT_ERROR_BITS = {
    0: "reservedBit0",
    1: "communicationsError",
    2: "powerError",
    3: "attachedDeviceError",
    4: "lampError",
    5: "pixelError",
    6: "photocellError",
    7: "messageError",
    8: "controllerError",
    9: "temperatureWarning",
    10: "climateControlError",
    11: "criticalTemperatureError",
    12: "drumRotorError",
    13: "doorOpen",
    14: "humidityWarning",
}


def decode_short_error_status(value: Any) -> Tuple[str, str]:
    """Devuelve (err_text, err_raw 4-char hex). 'none'/'0000' cuando todo OK."""
    iv = snmp_values.value_to_int(value)
    if iv is None:
        return "?", "?"
    raw_hex = f"{iv:04X}"
    if iv == 0:
        return "none", raw_hex
    names = []
    max_bit = max(16, iv.bit_length())
    for bit in range(max_bit):
        if iv & (1 << bit):
            names.append(SHORT_ERROR_BITS.get(bit, f"unknownBit{bit}"))
    return ";".join(names), raw_hex


# ---------------------------------------------------------------------------
# dmsMsgTableSource — message ID code
# ---------------------------------------------------------------------------


def decode_message_id_code(val: Any) -> Dict[str, Any]:
    """Extraer memoryType / messageNumber del dmsMsgTableSource.

    Layout: byte0=memoryType, bytes1-2=messageNumber, bytes3-4=CRC.
    """
    result: Dict[str, Any] = {
        "memory_type": None,
        "message_number": None,
        "crc_hex": None,
        "raw_hex": "?",
        "valid": False,
    }
    if val is None:
        return result

    raw = snmp_values.to_octets(val)
    if raw is None:
        try:
            iv = int(val)
            width = max(5, (iv.bit_length() + 7) // 8)
            raw = iv.to_bytes(width, "big")
        except Exception:
            result["raw_hex"] = str(val)
            return result

    result["raw_hex"] = raw.hex().upper()
    if len(raw) < 3:
        return result
    try:
        result["memory_type"] = raw[0]
        result["message_number"] = int.from_bytes(raw[1:3], "big")
        result["crc_hex"] = raw[3:5].hex().upper() if len(raw) >= 5 else None
        result["valid"] = True
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Sufijo de la línea de log
# ---------------------------------------------------------------------------


def build_suffix(
    ctrl: str,
    src: str,
    msg_hex: str,
    multi_field: str,
    err: str,
    err_raw: str,
) -> str:
    return (
        f"CTRL={ctrl} SRC={src} MSG={msg_hex} "
        f"{multi_field} ERR={err} ERR_RAW={err_raw}"
    )


__all__ = [
    "MULTI_MAX_LEN",
    "STATE_KEYS",
    "STATE_LABELS",
    "FAILURE_SUFFIX",
    "SHORT_ERROR_BITS",
    "decode_control_mode",
    "decode_source_mode",
    "decode_short_error_status",
    "decode_message_id_code",
    "build_suffix",
]
