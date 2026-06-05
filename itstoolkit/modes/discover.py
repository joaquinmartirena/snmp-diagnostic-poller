"""Modo `discover` — walk + mapeo de puntos.

Recorre un subárbol SNMP (``getNext`` repetido hasta salir del prefijo o
agotar `max_oids`) y devuelve los pares (oid, raw_value) encontrados. Pensado
para mapear capacidades de un dispositivo desconocido o validar qué OIDs
responden contra una MIB.

A diferencia de `monitor` y `probe`, no consulta el `device_registry`: solo
necesita un transporte SNMP y un OID base. Si el dispositivo está registrado
y queremos partir desde uno de sus puntos canónicos, el CLI puede resolver
el OID a partir del catálogo (e.g. `oids.GLOBAL_BASE`) antes de llamarnos.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    next_cmd,
)

from itstoolkit.protocols.snmp.client import SNMP_RETRIES, SNMP_TIMEOUT
from itstoolkit.protocols.snmp.values import is_valid_value


async def walk(
    ip: str,
    community: str,
    base_oid: str,
    *,
    port: int = 161,
    max_oids: int = 200,
    timeout: float = SNMP_TIMEOUT,
    retries: int = SNMP_RETRIES,
) -> List[Tuple[str, Any]]:
    """Walk SNMPv2c desde ``base_oid``.

    Devuelve la lista ordenada de (oid_dotted, raw_value). Se detiene cuando:

    - El siguiente OID sale del subárbol ``base_oid``.
    - El agente responde con ``endOfMibView`` u otro sentinel inválido.
    - Se alcanza ``max_oids`` (cota de seguridad).
    """
    engine = SnmpEngine()
    transport = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)

    results: List[Tuple[str, Any]] = []
    current = base_oid

    for _ in range(max_oids):
        error_indication, error_status, error_index, var_binds = await next_cmd(
            engine,
            CommunityData(community, mpModel=1),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(current)),
            lexicographicMode=False,
        )
        if error_indication or error_status:
            break
        if not var_binds:
            break

        oid_obj, val = var_binds[0]
        oid_str = str(oid_obj)
        if not oid_str.startswith(base_oid + ".") and oid_str != base_oid:
            break
        if not is_valid_value(val):
            break

        results.append((oid_str, val))
        current = oid_str

    return results


async def run_discover(
    ip: str,
    community: str,
    base_oid: str,
    *,
    port: int = 161,
    max_oids: int = 200,
) -> List[Tuple[str, Any]]:
    """Punto de entrada llamado por el CLI."""
    return await walk(ip, community, base_oid, port=port, max_oids=max_oids)


__all__ = ["walk", "run_discover"]
