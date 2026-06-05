"""Escenarios PoC del VMS NTCIP 1203.

Los escenarios viven en este paquete porque son específicos del dispositivo:
catálogo de OIDs, decoders y veredicto pertenecen al mismo conocimiento de
familia que el adapter. El modo `scenario` (CLI) los descubre vía
``VmsNtcip1203Adapter.scenarios()`` — sin scan automático ni registry global.

Primer bloque (Fase 5): sólo escenarios AUTOMATIC read-only.
"""

from __future__ import annotations

from typing import Sequence

from itstoolkit.core.scenario import Scenario

from .poc_vms_01_connectivity import PocVms01Connectivity
from .poc_vms_02_oid_map import PocVms02OidMap
from .poc_vms_03_capabilities import PocVms03Capabilities
from .poc_vms_04_active_message import PocVms04ReadActiveMessage


def all_scenarios() -> Sequence[Scenario]:
    """Lista ordenada de escenarios expuestos por el adapter VMS.

    El orden es el orden de declaración (01 → 02 → 03 → 04). El runner no
    aplica DAG de dependencias en este bloque: si POC-VMS-01 falla, los
    siguientes corren igual y registran su propio FAIL/PARTIAL.
    """
    return (
        PocVms01Connectivity(),
        PocVms02OidMap(),
        PocVms03Capabilities(),
        PocVms04ReadActiveMessage(),
    )


__all__ = [
    "PocVms01Connectivity",
    "PocVms02OidMap",
    "PocVms03Capabilities",
    "PocVms04ReadActiveMessage",
    "all_scenarios",
]
