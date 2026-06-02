#!/usr/bin/env python3
"""
VMS_NTCIP1203 profile — NTCIP 1203 variable message sign poller (read-only).

Polls dmsControlMode, dmsMsgSourceMode, dmsMsgTableSource and shortErrorStatus,
then reads the active MULTI string for the message currently displayed.

OIDs come from shared.oid_providers (Ntcip1203V3); none are hardcoded here.
SNMP access is read-only: the client is SnmpClient(allow_write=False).
"""

import asyncio

from shared import value_utils
from shared.snmp_client import SnmpClient, classify_comm_status
from shared.oid_providers import OidProviderRegistry
from polling import common

# OID provider for this profile (no numeric OIDs live in this file).
OIDS = OidProviderRegistry.resolve("VMS_NTCIP1203")

REQUIRED_OIDS = OIDS.required_oids()

MULTI_MAX_LEN = 500

# Change-detection keys
STATE_KEYS = ["ctrl", "src", "msg", "multi", "err", "err_raw"]
STATE_LABELS = {"ctrl": "CTRL", "src": "SRC", "msg": "MSG",
                "multi": "MULTI", "err": "ERR", "err_raw": "ERR_RAW"}

FAILURE_SUFFIX = "CTRL=? SRC=? MSG=? MULTI=? ERR=? ERR_RAW=?"


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------
def decode_control_mode(raw):
    try:
        v = int(raw)
    except Exception:
        return f"unknown({raw})"
    mapping = {2: "local", 4: "central", 5: "centralOverride"}
    return f"{mapping.get(v, 'unknown')}({v})"


def decode_source_mode(raw):
    try:
        v = int(raw)
    except Exception:
        return f"unknown({raw})"
    mapping = {8: "central", 9: "timebasedScheduler", 10:"powerRecovery", 11:"reset", 12: "commLoss", 13:"powerLoss", 14:"endDuration"}
    return f"{mapping.get(v, 'unknown')}({v})"


SHORT_ERROR_BITS = {
    0:  "reservedBit0",
    1:  "communicationsError",
    2:  "powerError",
    3:  "attachedDeviceError",
    4:  "lampError",
    5:  "pixelError",
    6:  "photocellError",
    7:  "messageError",
    8:  "controllerError",
    9:  "temperatureWarning",
    10: "climateControlError",
    11: "criticalTemperatureError",
    12: "drumRotorError",
    13: "doorOpen",
    14: "humidityWarning",
}


def decode_short_error_status(value):
    """Decode shortErrorStatus into (err_text, err_raw 4-char hex)."""
    iv = value_utils.value_to_int(value)
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


def decode_message_id_code(val):
    """
    Extract memoryType / messageNumber from dmsMsgTableSource for the MULTI
    lookup. Layout: byte0=memoryType, bytes1-2=messageNumber, bytes3-4=CRC.
    Returns dict: memory_type, message_number, crc_hex, raw_hex, valid.
    """
    result = {"memory_type": None, "message_number": None, "crc_hex": None, "raw_hex": "?", "valid": False}
    if val is None:
        return result

    raw = value_utils.to_octets(val)
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
        result["memory_type"]    = raw[0]
        result["message_number"] = int.from_bytes(raw[1:3], "big")
        result["crc_hex"]        = raw[3:5].hex().upper() if len(raw) >= 5 else None
        result["valid"]          = True
    except Exception:
        pass
    return result


async def read_current_multi(client, transport, community, memory_type, message_number):
    """GET dmsMessageMultiString. Returns (text, status: ok|read_error|unavailable)."""
    if memory_type is None or message_number is None:
        return None, "unavailable"
    oid = OIDS.multi_oid(memory_type, message_number)
    val, err = await client.get_one(transport, community, oid)
    if err:
        return None, "read_error"
    if val is None:
        return None, "unavailable"
    return value_utils.decode_octet_text(val), "ok"


# ---------------------------------------------------------------------------
# Log line suffix
# ---------------------------------------------------------------------------
def build_suffix(ctrl, src, msg_hex, multi_field, err, err_raw):
    return (f"CTRL={ctrl} SRC={src} MSG={msg_hex} "
            f"{multi_field} ERR={err} ERR_RAW={err_raw}")


# ---------------------------------------------------------------------------
# Polling task
# ---------------------------------------------------------------------------
async def run_vms(dev):
    client = SnmpClient(allow_write=False)
    transport = None
    prev_state = {}

    while True:
        ts = common.now_ts()
        log_path = common.get_log_path(dev["name"], dev["ip"])
        try:
            if transport is None:
                transport = await client.make_transport(dev["ip"], dev["port"])
            vals, err = await client.get_many(
                transport, dev["community"], REQUIRED_OIDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            vals, err = {}, "TIMEOUT"

        comm = classify_comm_status(err, vals)

        if comm in ("TIMEOUT", "SNMP_ERROR"):
            prefix = common.build_common_prefix(ts, dev, "vms", comm)
            common.emit(log_path, f"{prefix} {FAILURE_SUFFIX}")
            await asyncio.sleep(dev["interval_seconds"])
            continue

        ctrl_str = decode_control_mode(vals.get(OIDS.CTRL_MODE))
        src_str  = decode_source_mode(vals.get(OIDS.SRC_MODE))
        err_str, err_raw = decode_short_error_status(vals.get(OIDS.SHORT_ERR))
        mid = decode_message_id_code(vals.get(OIDS.MSG_SRC))

        if mid["valid"]:
            multi_text, multi_status = await read_current_multi(
                client, transport, dev["community"],
                mid["memory_type"], mid["message_number"])
        else:
            multi_text, multi_status = None, "unavailable"

        if multi_status == "ok":
            multi_clean = value_utils.sanitize_one_line(multi_text, MULTI_MAX_LEN)
            multi_field = f'MULTI="{multi_clean}"'
            multi_state = multi_clean
        elif multi_status == "read_error":
            multi_field, multi_state = "MULTI=read_error", "read_error"
        else:
            multi_field, multi_state = "MULTI=unavailable", "unavailable"

        current_state = {
            "ctrl": ctrl_str, "src": src_str, "msg": mid["raw_hex"],
            "multi": multi_state, "err": err_str, "err_raw": err_raw,
        }
        changes = []
        if comm == "OK":
            changes = common.detect_changes(prev_state, current_state, STATE_KEYS, STATE_LABELS, quoted=("multi",))
            prev_state = current_state

        prefix = common.build_common_prefix(ts, dev, "vms", comm)
        line = f"{prefix} {build_suffix(ctrl_str, src_str, mid['raw_hex'], multi_field, err_str, err_raw)}"
        common.emit(log_path, common.append_changes(line, changes))
        await asyncio.sleep(dev["interval_seconds"])


def create_vms_tasks(dev):
    """Registry entry: VMS devices run a single 'vms' polling task."""
    return [asyncio.create_task(run_vms(dev))]
