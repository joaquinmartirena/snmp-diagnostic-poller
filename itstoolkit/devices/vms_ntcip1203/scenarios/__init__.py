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
from .poc_vms_05_activate_manual import PocVms05ActivateManual
from .poc_vms_06_priority_model import PocVms06PriorityModel
from .poc_vms_07_schedule_device import PocVms07ScheduleDevice
from .poc_vms_08_resync_schedule import PocVms08ResyncSchedule
from .poc_vms_09_divergence import PocVms09Divergence
from .poc_vms_10_unmanaged_override import PocVms10UnmanagedOverride
from .poc_vms_11_clock_drift import PocVms11ClockDrift
from .poc_vms_12_recovery_after_offline import PocVms12RecoveryAfterOffline
from .poc_vms_13_reboot_recovery import PocVms13RebootRecovery
from .poc_vms_14_brightness import PocVms14Brightness
from .poc_vms_15_graphics import PocVms15Graphics
from .poc_vms_15b_load_bmp import PocVms15BLoadBmp
from .poc_vms_16_multi_capabilities import PocVms16MultiCapabilities
from .poc_vms_17_activation_errors import PocVms17ActivationErrors
from .poc_vms_18_multi_syntax_errors import PocVms18MultiSyntaxErrors
from .poc_vms_19_partial_write_recovery import PocVms19PartialWriteRecovery
from .poc_vms_20_local_mode import PocVms20LocalMode
from .poc_vms_21_client_side_loop import PocVms21ClientSideLoop


def all_scenarios() -> Sequence[Scenario]:
    """Lista ordenada de escenarios expuestos por el adapter VMS.

    El orden es el orden de declaración (01 → 10). El runner no aplica DAG
    de dependencias: si POC-VMS-01 falla, los siguientes corren igual y
    registran su propio FAIL/PARTIAL. Los escenarios con
    ``requires_write=True`` quedan ``BLOCKED`` si el doble gate no está
    habilitado.
    """
    return (
        PocVms01Connectivity(),
        PocVms02OidMap(),
        PocVms03Capabilities(),
        PocVms04ReadActiveMessage(),
        PocVms05ActivateManual(),
        PocVms06PriorityModel(),
        PocVms07ScheduleDevice(),
        PocVms08ResyncSchedule(),
        PocVms09Divergence(),
        PocVms10UnmanagedOverride(),
        PocVms11ClockDrift(),
        PocVms12RecoveryAfterOffline(),
        PocVms13RebootRecovery(),
        PocVms14Brightness(),
        PocVms15Graphics(),
        PocVms15BLoadBmp(),
        PocVms16MultiCapabilities(),
        PocVms17ActivationErrors(),
        PocVms18MultiSyntaxErrors(),
        PocVms19PartialWriteRecovery(),
        PocVms20LocalMode(),
        PocVms21ClientSideLoop(),
    )


__all__ = [
    "PocVms01Connectivity",
    "PocVms02OidMap",
    "PocVms03Capabilities",
    "PocVms04ReadActiveMessage",
    "PocVms05ActivateManual",
    "PocVms06PriorityModel",
    "PocVms07ScheduleDevice",
    "PocVms08ResyncSchedule",
    "PocVms09Divergence",
    "PocVms10UnmanagedOverride",
    "PocVms11ClockDrift",
    "PocVms12RecoveryAfterOffline",
    "PocVms13RebootRecovery",
    "PocVms14Brightness",
    "PocVms15Graphics",
    "PocVms15BLoadBmp",
    "PocVms16MultiCapabilities",
    "PocVms17ActivationErrors",
    "PocVms18MultiSyntaxErrors",
    "PocVms19PartialWriteRecovery",
    "PocVms20LocalMode",
    "PocVms21ClientSideLoop",
    "all_scenarios",
]
