#!/usr/bin/env python3
"""
value_utils.py — Coercion and formatting helpers for pysnmp values.

Extracted from the original common.py. Pure functions only: no SNMP I/O,
no logging, no internal imports. Safe for both polling and PoC code.
"""

from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance, EndOfMibView

DEFAULT_MAX_LINE_VALUE = 500

# Sentinel values pysnmp returns when an OID has no value in an otherwise
# successful PDU. These are NOT None, but must be treated as invalid.
_NULL_TYPES = (NoSuchObject, NoSuchInstance, EndOfMibView)


def is_valid_value(val):
    return val is not None and not isinstance(val, _NULL_TYPES)


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
