"""Catálogo de OIDs del VMS NTCIP 1203 v3.

Reúne en un único archivo lo que en el legacy estaba repartido entre
`shared/oid_providers/base.py` (system group + NTCIP 1201) y
`shared/oid_providers/ntcip1203_v3.py` (dms node).

OID values verificados contra:
- RFC 3418 (SNMPv2-MIB system group).
- NTCIP 1201 v03.15 (Global Object Definitions).
- NTCIP 1203 v03.05 (DMS).

INVARIANTE: ningún OID se hardcodea fuera de este módulo dentro del paquete.
Los decoders, el adapter y los escenarios resuelven OIDs por nombre acá.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SNMPv2-MIB system group (RFC 3418) — 1.3.6.1.2.1.1
# ---------------------------------------------------------------------------
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"

# ---------------------------------------------------------------------------
# NTCIP 1201 Global Object Definitions — enterprise 1206.4.2.6
# ---------------------------------------------------------------------------
GLOBAL_BASE = "1.3.6.1.4.1.1206.4.2.6"

GLOBAL_SET_ID_PARAMETER = "1.3.6.1.4.1.1206.4.2.6.1.1.0"
GLOBAL_MAX_MODULES = "1.3.6.1.4.1.1206.4.2.6.1.2.0"
GLOBAL_MODULE_TABLE = "1.3.6.1.4.1.1206.4.2.6.1.3"
CONTROLLER_BASE_STANDARDS = "1.3.6.1.4.1.1206.4.2.6.1.4.0"

GLOBAL_TIME = "1.3.6.1.4.1.1206.4.2.6.3.1.0"

MODULE_DEVICE_NODE_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.2"
MODULE_MAKE_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.3"
MODULE_MODEL_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.4"
MODULE_VERSION_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.5"

# ---------------------------------------------------------------------------
# NTCIP 1203 v3 DMS — 1.3.6.1.4.1.1206.4.2.3
# ---------------------------------------------------------------------------
DMS_BASE = "1.3.6.1.4.1.1206.4.2.3"

# signControl group (dms 6)
CTRL_MODE = "1.3.6.1.4.1.1206.4.2.3.6.1.0"  # dmsControlMode
MSG_SRC = "1.3.6.1.4.1.1206.4.2.3.6.5.0"  # dmsMsgTableSource
SRC_MODE = "1.3.6.1.4.1.1206.4.2.3.6.7.0"  # dmsMessageSourceMode

# statError group (dms 9)
SHORT_ERR = "1.3.6.1.4.1.1206.4.2.3.9.7.1.0"  # shortErrorStatus

# dmsMessageMultiString column (dms 5.8.1.3); indexed by
# dmsMessageMemoryType . dmsMessageNumber.
MULTI_BASE = "1.3.6.1.4.1.1206.4.2.3.5.8.1.3"


# ---------------------------------------------------------------------------
# Conjuntos lógicos
# ---------------------------------------------------------------------------


def system_oids() -> list[str]:
    """Escalares estándar del system group, útiles para identificar el panel."""
    return [SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_NAME]


def identity_oids() -> list[str]:
    """Escalares NTCIP 1201 útiles para fingerprint del controlador."""
    return [GLOBAL_SET_ID_PARAMETER, CONTROLLER_BASE_STANDARDS]


def required_oids() -> list[str]:
    """Escalares polleados en cada ciclo del modo monitor."""
    return [CTRL_MODE, SRC_MODE, MSG_SRC, SHORT_ERR]


def multi_oid(memory_type: int, message_number: int) -> str:
    """OID completo del MULTI string del mensaje activo."""
    return f"{MULTI_BASE}.{memory_type}.{message_number}"


__all__ = [
    # System group
    "SYS_DESCR",
    "SYS_OBJECT_ID",
    "SYS_UPTIME",
    "SYS_CONTACT",
    "SYS_NAME",
    "SYS_LOCATION",
    # NTCIP 1201
    "GLOBAL_BASE",
    "GLOBAL_SET_ID_PARAMETER",
    "GLOBAL_MAX_MODULES",
    "GLOBAL_MODULE_TABLE",
    "CONTROLLER_BASE_STANDARDS",
    "GLOBAL_TIME",
    "MODULE_DEVICE_NODE_COL",
    "MODULE_MAKE_COL",
    "MODULE_MODEL_COL",
    "MODULE_VERSION_COL",
    # NTCIP 1203
    "DMS_BASE",
    "CTRL_MODE",
    "MSG_SRC",
    "SRC_MODE",
    "SHORT_ERR",
    "MULTI_BASE",
    # Helpers
    "system_oids",
    "identity_oids",
    "required_oids",
    "multi_oid",
]
