"""POC-VMS-08 — Re-sincronización de schedule existente.

Valida que se puede sobrescribir una fila del ``dmsActionTable`` sin dejar
restos del MessageIDCode anterior. En operación normal, la plataforma
sincroniza schedules sucesivos sobre el mismo panel; si el re-sync no es
limpio, el panel acumula referencias huérfanas.

.. note::

   "Schedule A" y "schedule B" son **dos estados sucesivos de la misma
   fila** del ``dmsActionTable`` (no dos entries distintas):

   - Estado A: ``dmsActionMsgCode.<action_index>`` → MessageIDCode(slot A)
   - Estado B: ``dmsActionMsgCode.<action_index>`` → MessageIDCode(slot B)

   Los mensajes A y B son MULTIs nuevos creados por el escenario en slots
   ``changeable`` altos (no reutiliza ningún mensaje preexistente).

Defaults (overridables por device en ``config.yaml``):

- ``action_index = 2``       — overridable como ``poc_08_action_index``
- ``slot_a = 254``           — overridable como ``poc_08_slot_a``
- ``slot_b = 255``           — overridable como ``poc_08_slot_b``

Pasos:

1. Cargar schedule A: MULTI A en ``slot_a``,
   ``dmsActionMsgCode.<action_index>`` → MessageIDCode(slot_a), activar
   scheduler (``memType=6 / msgNum=1 / CRC=0``).
2. Confirmar que A se muestra (``dmsMsgTableSource`` apunta a ``slot_a``).
3. Cargar schedule B: MULTI B en ``slot_b``, sobrescribir
   ``dmsActionMsgCode.<action_index>`` → MessageIDCode(slot_b).
4. Reactivar scheduler.
5. Confirmar que B se muestra y que
   ``dmsActionMsgCode.<action_index>`` ya no contiene el MessageIDCode de A.

Criterio:

- ``PASS`` si tras el re-sync el panel muestra B y la acción apunta
  exclusivamente a B (no residuos de A).
- ``PARTIAL`` si la acción se sobrescribe pero el panel sigue mostrando A
  (panel cachea el mensaje activo y requiere re-activar).
- ``FAIL`` si el SET de re-sync devuelve error o el panel queda en estado
  inconsistente.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from pysnmp.proto.rfc1902 import OctetString

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation


class PocVms08ResyncSchedule(Scenario):
    id = "POC-VMS-08"
    name = "Re-sincronización de schedule"
    description = (
        "Carga un schedule A, lo reemplaza por B y verifica que no quedan "
        "restos del primero en dmsActionTable."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    slot_memory_type: ClassVar[int] = oids.MEM_TYPE_CHANGEABLE
    default_slot_a: ClassVar[int] = 254
    default_slot_b: ClassVar[int] = 255
    default_action_index: ClassVar[int] = 2  # no 1, evita pisar la acción operativa
    settle_seconds: ClassVar[float] = 2.5

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        slot_a = int(ctx.device_config.get("poc_08_slot_a", self.default_slot_a))
        slot_b = int(ctx.device_config.get("poc_08_slot_b", self.default_slot_b))
        action_index = int(
            ctx.device_config.get(
                "poc_08_action_index", self.default_action_index
            )
        )
        # --- Schedule A ----------------------------------------------------
        a = await self._setup_action(
            ctx,
            slot=slot_a,
            multi="[jp3]POC-08[nl]SCHED-A",
            label="A",
            action_index=action_index,
        )
        if a is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary="No se pudo cargar el schedule A.",
            )

        ok_a, err_a = await self._activate_scheduler_and_verify(
            ctx, expected_slot=slot_a, label="A"
        )
        if not ok_a:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Schedule A no quedó activo: {err_a}",
                error=err_a,
            )

        # --- Schedule B (re-sync sobre la misma acción) --------------------
        b = await self._setup_action(
            ctx,
            slot=slot_b,
            multi="[jp3]POC-08[nl]SCHED-B",
            label="B",
            action_index=action_index,
        )
        if b is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary="A activo pero no se pudo cargar B.",
            )

        ok_b, err_b = await self._activate_scheduler_and_verify(
            ctx, expected_slot=slot_b, label="B"
        )
        if not ok_b:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"B cargado pero no desplazó a A en pantalla: {err_b}. "
                    f"Posible cache de currentBuffer."
                ),
                design_impact=(
                    "Re-sync requiere ciclo adicional de activación. "
                    "Documentar latencia."
                ),
                error=err_b,
            )

        # Confirmar que la acción ya no apunta a A
        action_oid = f"{oids.DMS_ACTION_MSG_CODE_COL}.{action_index}"
        raw, get_err = await ctx.snmp.get_one(action_oid)
        action_mid = decoders.decode_message_id_code(raw)
        ctx.record_step(
            "verify.action_post_resync",
            operation="SNMP_GET",
            oid_name="dmsActionMsgCode",
            oid=action_oid,
            value_read={
                "raw_hex": action_mid.get("raw_hex"),
                "memory_type": action_mid.get("memory_type"),
                "message_number": action_mid.get("message_number"),
            },
            success=get_err is None,
            error=get_err,
        )
        if action_mid.get("message_number") == slot_a:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    "Re-sync no limpió la acción — sigue apuntando al slot A."
                ),
                design_impact=(
                    "Re-sync sucio acumula referencias huérfanas. La sync "
                    "debe explicitar limpieza previa de dmsActionTable."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Schedule A→B reemplazado: acción {action_index} ahora "
                f"apunta a slot {action_mid.get('message_number')} y panel "
                f"muestra B."
            ),
        )

    # ---------------------------------------------------------------- helpers

    async def _setup_action(
        self,
        ctx: ScenarioContext,
        *,
        slot: int,
        multi: str,
        label: str,
        action_index: int,
    ):
        loaded, err = await _activation.load_message_into_slot(
            ctx,
            memory_type=self.slot_memory_type,
            message_number=slot,
            multi=multi,
            run_time_priority=64,
        )
        if loaded is None:
            ctx.record_step(
                f"setup_{label}.load_failed",
                operation="LOAD",
                success=False,
                error=err,
            )
            return None

        msg_id_code = (
            bytes([self.slot_memory_type])
            + slot.to_bytes(2, "big")
            + loaded.crc
        )
        action_oid = f"{oids.DMS_ACTION_MSG_CODE_COL}.{action_index}"
        _, err = await ctx.snmp.set_one(action_oid, OctetString(msg_id_code))
        ctx.record_step(
            f"setup_{label}.set_action",
            operation="SNMP_SET",
            oid_name="dmsActionMsgCode",
            oid=action_oid,
            value_read=msg_id_code.hex().upper(),
            success=err is None,
            error=err,
            slot=slot,
        )
        if err is not None:
            return None
        return loaded

    async def _activate_scheduler_and_verify(
        self, ctx: ScenarioContext, *, expected_slot: int, label: str
    ):
        sched_code = _activation.build_activation_code(
            duration_minutes=65535,
            activate_priority=255,
            memory_type=oids.MEM_TYPE_SCHEDULE,
            message_number=1,
            message_crc=b"\x00\x00",
        )
        _, err = await ctx.snmp.set_one(
            oids.DMS_ACTIVATE_MESSAGE, OctetString(sched_code)
        )
        ctx.record_step(
            f"activate_{label}",
            operation="SNMP_SET",
            oid_name="dmsActivateMessage",
            oid=oids.DMS_ACTIVATE_MESSAGE,
            value_read=sched_code.hex().upper(),
            success=err is None,
            error=err,
        )
        if err is not None:
            return False, err
        await asyncio.sleep(self.settle_seconds)
        raw, _ = await ctx.snmp.get_one(oids.MSG_SRC)
        mid = decoders.decode_message_id_code(raw)
        ctx.record_step(
            f"verify_{label}.msg_src",
            operation="SNMP_GET",
            oid_name="dmsMsgTableSource",
            oid=oids.MSG_SRC,
            value_read=mid,
            success=mid["valid"]
            and mid["memory_type"] == self.slot_memory_type
            and mid["message_number"] == expected_slot,
        )
        if (
            mid["valid"]
            and mid["memory_type"] == self.slot_memory_type
            and mid["message_number"] == expected_slot
        ):
            return True, None
        return False, f"msg_src points to {mid.get('message_number')}"
