#!/usr/bin/env python3
"""
snmp_client.py — SNMP v2c client extracted from the original common.py.

Wraps pysnmp GET operations behind a small SnmpClient class. The class
carries an `allow_write` flag that models the read-only contract of this
toolkit structurally:

    - Polling always instantiates SnmpClient(allow_write=False).
    - Read-only PoCs may use allow_write=False.
    - Only PoC scenarios that explicitly declare requires_write=True may run
    against a client created with allow_write=True, and the PoC runner is
    responsible for enforcing the confirm_write / --confirm-write gate
    before ever constructing such a client.

Any SET-style operation goes through `_require_write()`, which raises if the
client was not granted write permission. Today no SET operation is wired up
(the toolkit is GET-only), but the guard is in place so writes can never be
issued from a read-only client once they are added.
"""

import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    get_cmd, SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity
)

from shared.value_utils import is_valid_value

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
SNMP_TIMEOUT = 5
SNMP_RETRIES = 1
CHUNK_SIZE   = 20          # max varbinds per GET PDU (avoid tooBig)

# Worst-to-best ranking so chunk merging keeps the most severe error.
_ERR_RANK = {None: 0, "PARTIAL": 1, "SNMP_ERROR": 2, "TIMEOUT": 3}


class WriteNotAllowedError(PermissionError):
    """Raised when a write is attempted on a read-only SnmpClient."""


class SnmpClient:
    """
    Async SNMP v2c client. GET-only in practice; write operations are guarded
    by `allow_write` so a read-only client can never issue a SET.
    """

    def __init__(self, allow_write=False, timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES):
        self.allow_write = bool(allow_write)
        self.timeout = timeout
        self.retries = retries
        self.engine = SnmpEngine()

    # -- write guard --------------------------------------------------------
    def _require_write(self):
        if not self.allow_write:
            raise WriteNotAllowedError(
                "SNMP write attempted on a read-only client (allow_write=False)")

    # -- transport ----------------------------------------------------------
    async def make_transport(self, ip, port):
        return await UdpTransportTarget.create(
            (ip, port), timeout=self.timeout, retries=self.retries)

    # -- GET operations -----------------------------------------------------
    async def get_many(self, transport, community, oids):
        """
        GET several OIDs in one PDU.
        Returns (values, err_kind):
            - values: dict keyed by the dotted OID returned by the agent;
              invalid sentinel values are stored as None.
            - err_kind: None on success, 'TIMEOUT' on transport/timeout
              failure, 'SNMP_ERROR' when the agent returns a non-zero
              error_status.
        """
        obj_types = [ObjectType(ObjectIdentity(o)) for o in oids]
        error_indication, error_status, error_index, var_binds = await get_cmd(
            self.engine,
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

    async def get_chunked(self, transport, community, oids, chunk=CHUNK_SIZE):
        """
        GET many OIDs across several PDUs, issued concurrently.
        Running the chunks in parallel keeps a poll bounded by a single
        chunk's timeout instead of the sum of all chunk timeouts (important
        when a device is unreachable). Returns (values, worst_err_kind).
        """
        subs = [oids[i:i + chunk] for i in range(0, len(oids), chunk)]

        async def _one(sub):
            try:
                return sub, await self.get_many(transport, community, sub)
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

    async def get_one(self, transport, community, oid):
        """Return (value_object, err_kind). value is None on missing/sentinel."""
        values, err = await self.get_many(transport, community, [oid])
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
