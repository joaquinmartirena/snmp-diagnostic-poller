#!/usr/bin/env python3
"""
ntcip1203_v3.py — Ntcip1203V3 provider: all DMS OIDs for NTCIP 1203 v3.

OID values verified against NTCIP 1203 v03.05. These are the OIDs that used
to be hardcoded in polling/profiles/vms_ntcip1203.py; they now live here so
the profile carries no numeric OIDs.
"""

from shared.oid_providers.base import NtcipBase


class Ntcip1203V3(NtcipBase):
    """OID provider for NTCIP 1203 v3 variable message signs (DMS)."""

    # dms node base: 1.3.6.1.4.1.1206.4.2.3
    DMS_BASE = "1.3.6.1.4.1.1206.4.2.3"

    # signControl group (dms 6)
    CTRL_MODE = "1.3.6.1.4.1.1206.4.2.3.6.1.0"    # dmsControlMode      (signControl 1)
    MSG_SRC   = "1.3.6.1.4.1.1206.4.2.3.6.5.0"    # dmsMsgTableSource   (signControl 5)
    SRC_MODE  = "1.3.6.1.4.1.1206.4.2.3.6.7.0"    # dmsMessageSourceMode(signControl 7)

    # statError group (dms 9)
    SHORT_ERR = "1.3.6.1.4.1.1206.4.2.3.9.7.1.0"  # shortErrorStatus    (statError 1)

    # dmsMessageMultiString column (dms 5.8.1.3); indexed by
    # dmsMessageMemoryType . dmsMessageNumber
    MULTI_BASE = "1.3.6.1.4.1.1206.4.2.3.5.8.1.3"

    def required_oids(self):
        """Scalars polled every cycle by the VMS profile."""
        return [self.CTRL_MODE, self.SRC_MODE, self.MSG_SRC, self.SHORT_ERR]

    def multi_oid(self, memory_type, message_number):
        """Full OID for the active message's MULTI string."""
        return f"{self.MULTI_BASE}.{memory_type}.{message_number}"
