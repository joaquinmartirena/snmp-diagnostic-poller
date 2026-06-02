#!/usr/bin/env python3
"""
daktronics_vanguard.py — DaktronicsVanguard provider.

Daktronics Vanguard DMS controllers speak NTCIP 1203 v3, so this provider
inherits every OID from Ntcip1203V3 unchanged. It exists as the dedicated
home for any Daktronics-specific quirks (OID overrides, vendor-private
branches, MULTI indexing differences) discovered in the field.

No quirks are known today — the class is intentionally a thin subclass.
Override the relevant constants or methods here when a deviation is found,
so the rest of the toolkit keeps resolving Daktronics panels by name.
"""

from shared.oid_providers.ntcip1203_v3 import Ntcip1203V3


class DaktronicsVanguard(Ntcip1203V3):
    """NTCIP 1203 v3 provider with Daktronics Vanguard quirks (none yet)."""

    pass
