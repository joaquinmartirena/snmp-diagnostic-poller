#!/usr/bin/env python3
"""
common.py — Device-agnostic helpers shared by all diagnostic profiles.

Contains only generic logic: SNMP GET helpers, value coercion/formatting,
COMM_STATUS classification, log path/rotation, and the common log prefix.
This module never imports profile modules, so profiles can safely depend on
it without creating import cycles.

READ-ONLY: only SNMP GET operations are issued anywhere in this project.
"""

import os
import asyncio
from datetime import datetime

from pysnmp.hlapi.v3arch.asyncio import (
    get_cmd, SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity
)
from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance, EndOfMibView

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
SNMP_TIMEOUT = 5
SNMP_RETRIES = 1
CHUNK_SIZE   = 20          # max varbinds per GET PDU (avoid tooBig)
DEFAULT_MAX_LINE_VALUE = 500

# Sentinel values pysnmp returns when an OID has no value in an otherwise
# successful PDU. These are NOT None, but must be treated as invalid.
_NULL_TYPES = (NoSuchObject, NoSuchInstance, EndOfMibView)


def is_valid_value(val):
    return val is not None and not isinstance(val, _NULL_TYPES)


# ===========================================================================
# Value helpers
# ===========================================================================
def to_octets(value):
    """
    Return raw bytes for OctetString-like values, else None.

    NOTE: do NOT use bytes(value) blindly. pysnmp Integer types (and plain
    Python ints) implement __index__, so bytes(Integer(5)) returns 5 zero
    bytes instead of the integer's encoding. We only treat a value as octets
    when it exposes asOctets() (OctetString family) or is real bytes.
    """
    if value is None:
        return None
    if hasattr(value, "asOctets"):
        try:
            return value.asOctets()
        except Exception:
            return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return None


def value_to_int(value):
    """Coerce a pysnmp value to int, or None if undecodable."""
    if value is None:
        return None
    octets = to_octets(value)
    if octets is not None:
        return int.from_bytes(octets, "big") if octets else 0
    try:
        return int(value)
    except Exception:
        return None


def raw_to_hex(val):
    """Compact uppercase hex of any value, '?' if unknown."""
    if val is None:
        return "?"
    octets = to_octets(val)
    if octets is not None:
        return octets.hex().upper() if octets else "00"
    try:
        return f"{int(val):02X}"
    except Exception:
        return str(val).replace(" ", "").upper()


def raw_hex_padded(value, nbytes):
    """Uppercase hex padded to nbytes*2 digits; '?' if undecodable."""
    if value is None:
        return "?"
    octets = to_octets(value)
    if octets is not None:
        h = octets.hex().upper()
        return h.rjust(nbytes * 2, "0") if h else "0" * (nbytes * 2)
    iv = value_to_int(value)
    if iv is None:
        return "?"
    return f"{iv:0{nbytes * 2}X}"


def token_hex(value):
    """Byte-status token: int -> 2-digit hex, octet -> compact hex, '?' if missing."""
    if value is None:
        return "?"
    try:
        return f"{int(value):02X}"
    except Exception:
        pass
    octets = to_octets(value)
    if octets is not None:
        return octets.hex().upper() if octets else "00"
    return "?"


def token_int(value):
    """Coordination token: int -> decimal, octet -> hex, '?' if missing."""
    if value is None:
        return "?"
    try:
        return str(int(value))
    except Exception:
        pass
    octets = to_octets(value)
    if octets is not None:
        return octets.hex().upper() if octets else "0"
    return "?"


def decode_octet_text(val):
    """
    Decode a (likely OctetString) value to text for display.
    pysnmp's prettyPrint() renders non-ASCII OctetStrings as '0x4A6F...',
    so we decode the raw bytes directly and only fall back if that fails.
    """
    octets = to_octets(val)
    if octets is not None:
        try:
            return octets.decode("ascii")
        except Exception:
            pass
        try:
            return octets.decode("latin-1")
        except Exception:
            pass
    try:
        return val.prettyPrint()
    except Exception:
        return str(val)


def sanitize_one_line(text, max_len=DEFAULT_MAX_LINE_VALUE):
    """Make an arbitrary string safe for a single horizontal log line."""
    if text is None:
        return ""
    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    text = text.replace("\t", "\\t").replace('"', '\\"')
    if len(text) > max_len:
        text = text[:max_len] + "...<truncated>"
    return text


# ===========================================================================
# SNMP layer (GET only)
# ===========================================================================
def new_engine():
    return SnmpEngine()


async def make_transport(ip, port):
    return await UdpTransportTarget.create(
        (ip, port), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)


async def snmp_get_many(engine, transport, community, oids):
    """
    GET several OIDs in one PDU.
    Returns (values, err_kind):
        - values: dict keyed by the dotted OID returned by the agent; invalid sentinel values are stored as None.
        - err_kind: None on success, 'TIMEOUT' on transport/timeout failure,'SNMP_ERROR' when the agent returns a non-zero error_status.
    """
    obj_types = [ObjectType(ObjectIdentity(o)) for o in oids]
    error_indication, error_status, error_index, var_binds = await get_cmd(
        engine,
        CommunityData(community, mpModel=1),
        transport,
        ContextData(),
        *obj_types,
    )
    if error_indication:
        return {}, "TIMEOUT"
    if error_status:
        return {}, "SNMP_ERROR"

    values = {}
    for oid_obj, val in var_binds:
        values[str(oid_obj)] = val if is_valid_value(val) else None
    return values, None


# Worst-to-best ranking so chunk merging keeps the most severe error.
_ERR_RANK = {None: 0, "PARTIAL": 1, "SNMP_ERROR": 2, "TIMEOUT": 3}


async def snmp_get_chunked(engine, transport, community, oids, chunk=CHUNK_SIZE):
    """
    GET many OIDs across several PDUs, issued concurrently.
    Running the chunks in parallel keeps a poll bounded by a single chunk's
    timeout instead of the sum of all chunk timeouts (important when a device
    is unreachable). Returns (values, worst_err_kind).
    """
    subs = [oids[i:i + chunk] for i in range(0, len(oids), chunk)]

    async def _one(sub):
        try:
            return sub, await snmp_get_many(engine, transport, community, sub)
        except asyncio.CancelledError:
            raise
        except Exception:
            return sub, ({}, "TIMEOUT")

    results = {}
    worst = None
    for sub, (vals, err) in await asyncio.gather(*(_one(s) for s in subs)):
        if err:
            if _ERR_RANK[err] > _ERR_RANK[worst]:
                worst = err
            for o in sub:
                results.setdefault(o, None)
        else:
            results.update(vals)
    return results, worst


async def snmp_get_one(engine, transport, community, oid):
    """Return (value_object, err_kind). value is None on missing/sentinel."""
    values, err = await snmp_get_many(engine, transport, community, [oid])
    if err:
        return None, err
    return values.get(oid), None


def classify_comm_status(err_kind, values):
    """
    Map an err_kind plus per-OID values to a COMM_STATUS:
    - TIMEOUT / SNMP_ERROR pass through.
    - All requested OIDs present -> OK.
    - Otherwise (some OID missing) -> PARTIAL.
    """
    if err_kind in ("TIMEOUT", "SNMP_ERROR"):
        return err_kind
    missing = [o for o in values if values.get(o) is None]
    return "OK" if not missing else "PARTIAL"


# ===========================================================================
# Logging
# ===========================================================================
def get_log_path(device_name, ip):
    os.makedirs("logs", exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join("logs", f"{device_name}_{ip}_{date_str}.log")


def write_log(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_common_prefix(ts, dev, poll, comm_status):
    return (
        f"[{ts}] "
        f"DEVICE={dev['name']} "
        f"TYPE={dev['type']} "
        f"IP={dev['ip']} "
        f"PORT={dev['port']} "
        f"POLL={poll} "
        f"COMM_STATUS={comm_status}"
    )


def append_changes(line, changes):
    if changes:
        return line + " CHANGE=" + ";".join(changes)
    return line


def detect_changes(prev, current, keys, labels, quoted=()):
    """Generic field-change detector. Only reports keys present in prev."""
    changes = []
    for k in keys:
        pv = prev.get(k)
        cv = current.get(k)
        if pv is not None and pv != cv:
            if k in quoted:
                changes.append(f'{labels[k]}:"{pv}"->"{cv}"')
            else:
                changes.append(f"{labels[k]}:{pv}->{cv}")
    return changes


def emit(path, line):
    """Print to stdout and append to the daily log file."""
    print(line)
    write_log(path, line)
