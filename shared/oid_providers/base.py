#!/usr/bin/env python3
"""
base.py — NtcipBase: OIDs common to all NTCIP field devices.

Holds the standard SNMPv2-MIB system group (RFC 3418) plus the NTCIP 1201
"Global Object Definitions" node. Device-family providers (DMS, ASC, ...)
subclass this so every provider exposes the same baseline of system OIDs.

This module — like everything under shared/ — contains ONLY OID definitions
and pure helpers. It never imports from polling or pocs.
"""


class NtcipBase:
    """Baseline OIDs shared by NTCIP devices."""

    # -- SNMPv2-MIB system group (RFC 3418), 1.3.6.1.2.1.1 ------------------
    SYS_DESCR     = "1.3.6.1.2.1.1.1.0"
    SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
    SYS_UPTIME    = "1.3.6.1.2.1.1.3.0"
    SYS_CONTACT   = "1.3.6.1.2.1.1.4.0"
    SYS_NAME      = "1.3.6.1.2.1.1.5.0"
    SYS_LOCATION  = "1.3.6.1.2.1.1.6.0"

    # -- NTCIP 1201 Global Object Definitions, enterprise 1206.4.2.6 -------
    # OID values verified against NTCIP 1201 v03.15.
    GLOBAL_BASE = "1.3.6.1.4.1.1206.4.2.6"

    # globalConfiguration  ::= { global 1 }   -> 1206.4.2.6.1
    GLOBAL_SET_ID_PARAMETER    = "1.3.6.1.4.1.1206.4.2.6.1.1.0"   # globalConfiguration 1
    GLOBAL_MAX_MODULES         = "1.3.6.1.4.1.1206.4.2.6.1.2.0"   # globalConfiguration 2
    GLOBAL_MODULE_TABLE        = "1.3.6.1.4.1.1206.4.2.6.1.3"     # globalConfiguration 3 (table)
    CONTROLLER_BASE_STANDARDS  = "1.3.6.1.4.1.1206.4.2.6.1.4.0"   # globalConfiguration 4

    # globalTimeManagement ::= { global 3 }   -> 1206.4.2.6.3
    GLOBAL_TIME                = "1.3.6.1.4.1.1206.4.2.6.3.1.0"   # globalTimeManagement 1

    # moduleTableEntry columns (INDEX moduleNumber) under globalModuleTable.1
    MODULE_DEVICE_NODE_COL     = "1.3.6.1.4.1.1206.4.2.6.1.3.1.2"
    MODULE_MAKE_COL            = "1.3.6.1.4.1.1206.4.2.6.1.3.1.3"
    MODULE_MODEL_COL           = "1.3.6.1.4.1.1206.4.2.6.1.3.1.4"
    MODULE_VERSION_COL         = "1.3.6.1.4.1.1206.4.2.6.1.3.1.5"

    def system_oids(self):
        """Standard system-group scalars, useful for device identification."""
        return [
            self.SYS_DESCR,
            self.SYS_OBJECT_ID,
            self.SYS_UPTIME,
            self.SYS_NAME,
        ]

    def identity_oids(self):
        """NTCIP 1201 scalars useful for identifying/fingerprinting a device."""
        return [
            self.GLOBAL_SET_ID_PARAMETER,
            self.CONTROLLER_BASE_STANDARDS,
        ]
