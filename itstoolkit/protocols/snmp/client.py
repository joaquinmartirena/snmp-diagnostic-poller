"""Cliente SNMP v2c — reubicación del antiguo `shared/snmp_client.py`.

Sin reescritura: misma semántica de GET (chunked, errores, clasificación),
misma firma pública (`SnmpClient(allow_write=..., timeout=..., retries=...)`).
El único cambio interno es que la política de escritura ya no es un booleano
embebido (`self.allow_write`) sino un `WriteGuard` del núcleo. El parámetro
`allow_write` del constructor se conserva por compatibilidad con el legacy y
se traduce internamente a `DoubleGateWriteGuard.read_only()` /
`DoubleGateWriteGuard.unsafe_allow_write()`.

A partir de Fase 4, el CLI construirá el `WriteGuard` a partir de las flags
reales (`confirm_write` en config + `--confirm-write` en CLI + `--dry-run`) y
lo inyectará vía el parámetro `write_guard=`.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
    set_cmd,
)

from itstoolkit.core.safety import DoubleGateWriteGuard, WriteGuard
from itstoolkit.core.transport import WriteNotAllowedError

from .values import is_valid_value

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
SNMP_TIMEOUT = 5
SNMP_RETRIES = 1
CHUNK_SIZE = 20  # max varbinds per GET PDU (avoid tooBig)

# Worst-to-best ranking so chunk merging keeps the most severe error.
_ERR_RANK = {None: 0, "PARTIAL": 1, "SNMP_ERROR": 2, "TIMEOUT": 3}


class SnmpClient:
    """Async SNMP v2c client. GET-only en práctica.

    Las operaciones de escritura (cuando se incorporen) consultan el
    `WriteGuard` inyectado; un guard read-only hace que cualquier SET lance
    `WriteNotAllowedError`.

    El constructor sigue aceptando `allow_write: bool` por compatibilidad con
    el legacy. Si se pasa un `write_guard` explícito, `allow_write` se ignora.
    """

    def __init__(
        self,
        allow_write: bool = False,
        timeout: float = SNMP_TIMEOUT,
        retries: int = SNMP_RETRIES,
        *,
        write_guard: Optional[WriteGuard] = None,
    ) -> None:
        if write_guard is None:
            write_guard = (
                DoubleGateWriteGuard.unsafe_allow_write()
                if allow_write
                else DoubleGateWriteGuard.read_only()
            )
        self._write_guard: WriteGuard = write_guard
        self.timeout = timeout
        self.retries = retries
        self.engine = SnmpEngine()

    # -- compat con el campo público histórico ------------------------------
    @property
    def allow_write(self) -> bool:
        """Booleano compatibilidad-legacy: refleja el `WriteGuard` interno."""
        return bool(self._write_guard.allow_write)

    @property
    def write_guard(self) -> WriteGuard:
        return self._write_guard

    # -- write guard --------------------------------------------------------
    def _require_write(self, point=None) -> None:
        # Se mantiene el mensaje histórico para no romper logs/diagnósticos que
        # lo grepean. La fuente de verdad es ahora el WriteGuard del núcleo.
        try:
            self._write_guard.assert_can_write(point)
        except WriteNotAllowedError:
            raise WriteNotAllowedError(
                "SNMP write attempted on a read-only client (allow_write=False)",
                point=point,
            )

    # -- transport ----------------------------------------------------------
    async def make_transport(self, ip, port):
        return await UdpTransportTarget.create(
            (ip, port), timeout=self.timeout, retries=self.retries
        )

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
        subs = [oids[i : i + chunk] for i in range(0, len(oids), chunk)]

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

    # -- SET operations -----------------------------------------------------
    async def set_many(self, transport, community, varbinds, *, point=None):
        """SET several OIDs in one PDU.

        ``varbinds`` es un iterable de ``(oid, pysnmp_value)`` ya tipado
        (``OctetString``, ``Integer``, etc.) — el caller es responsable de
        encodear el valor con el tipo correcto.

        Pasa por el WriteGuard antes de tocar el transporte; con un guard
        read-only se lanza ``WriteNotAllowedError`` sin enviar ningún PDU.

        Devuelve ``(values, err_kind)`` con el mismo formato que ``get_many``:
        ``values`` contiene los varbinds tal como los devolvió el agente
        (algunos agentes devuelven el valor escrito, otros el actual).
        """
        self._require_write(point)
        obj_types = [
            ObjectType(ObjectIdentity(oid), value) for oid, value in varbinds
        ]
        error_indication, error_status, error_index, var_binds = await set_cmd(
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

    async def set_one(self, transport, community, oid, value, *, point=None):
        """SET un único OID. ``value`` debe ser un objeto pysnmp ya tipado."""
        values, err = await self.set_many(
            transport, community, [(oid, value)], point=point
        )
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


__all__ = [
    "SnmpClient",
    "WriteNotAllowedError",
    "classify_comm_status",
    "SNMP_TIMEOUT",
    "SNMP_RETRIES",
    "CHUNK_SIZE",
]
