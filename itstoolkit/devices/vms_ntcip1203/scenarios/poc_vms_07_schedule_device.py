"""POC-VMS-07 — Carga de schedule DEVICE (núcleo).

Valida que el panel acepta programación local de mensajes y selecciona el
mensaje correcto cuando arranca el scheduler. Esta versión apunta al
**núcleo del scheduling NTCIP 1203**:

- ``dmsActionTable`` (1203, ``dmsSchedule 2``) — fila que mapea un índice de
  acción a un ``MessageIDCode``.
- Activación con ``messageMemoryType=schedule(6)``, ``messageNumber=1``,
  ``CRC=0x0000`` — el panel pasa a ``dmsMsgSourceMode = timebasedScheduler(9)``.

No carga las tablas ``timeBaseScheduleTable`` ni ``dayPlanTable`` de
NTCIP 1201 (que requieren columnas que dependen del firmware y caen fuera
del alcance del PoC inicial). Una vez confirmado este núcleo, POC-VMS-07 v2
puede extenderse con day plans reales.

.. important::

   El ``action_index`` defaultea a **2** (no 1) para no pisar la acción
   operativa típicamente cargada en la posición 1. Si el panel tiene la
   posición 2 ocupada, ajustá ``poc_07_action_index`` en el YAML.

   Limitación conocida: como el panel selecciona qué acción ejecutar según
   el ``dayPlanTable`` (NTCIP 1201) que **no** tocamos, este escenario
   confirma que el SET de ``dmsActionMsgCode`` y la activación del scheduler
   funcionan, pero la verificación de "se muestra MI mensaje" depende de
   que el dayPlan vigente apunte al ``action_index`` configurado.

Pasos:

1. Cargar un MULTI de prueba en slot ``changeable``.
2. Escribir ``dmsActionMsgCode.1`` con el ``MessageIDCode`` del slot.
3. Activar el scheduler vía ``dmsActivateMessage`` con
   ``memType=schedule(6)``, ``msgNum=1``, ``CRC=0x0000``.
4. Verificar que ``dmsMsgSourceMode = 9`` (timebasedScheduler).
5. Verificar que el panel está mostrando el mensaje esperado.

Criterio:

- ``PASS`` si tras activar, ``dmsMsgSourceMode = 9`` y el MULTI activo
  coincide con el cargado.
- ``PARTIAL`` si el panel acepta el SET pero no entra en modo scheduler
  (``dmsMsgSourceMode`` quedó en otro valor).
- ``FAIL`` si la carga del slot falla o el panel rechaza la activación.
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


class PocVms07ScheduleDevice(Scenario):
    id = "POC-VMS-07"
    name = "Carga de schedule DEVICE (núcleo)"
    description = (
        "Valida el núcleo del scheduling local NTCIP 1203: dmsActionTable + "
        "activación con memType=schedule. No carga timeBaseSchedule/dayPlan "
        "(NTCIP 1201) que dependen del firmware."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    slot_memory_type: ClassVar[int] = oids.MEM_TYPE_CHANGEABLE
    default_slot_number: ClassVar[int] = 253
    default_action_index: ClassVar[int] = 2  # ¡no 1! evita pisar la acción operativa
    settle_seconds: ClassVar[float] = 3.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        slot_number = int(
            ctx.device_config.get("poc_07_slot", self.default_slot_number)
        )
        action_index = int(
            ctx.device_config.get(
                "poc_07_action_index", self.default_action_index
            )
        )
        # Paso 1: cargar MULTI en slot
        loaded, err = await _activation.load_message_into_slot(
            ctx,
            memory_type=self.slot_memory_type,
            message_number=slot_number,
            multi="[jp3]POC-07[nl]SCHEDULED",
            run_time_priority=64,
        )
        if loaded is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo cargar el MULTI: {err}",
                error=err,
            )

        # Paso 2: escribir dmsActionMsgCode.action_index con el MessageIDCode
        # del slot (memType=1B, msgNum=2B, CRC=2B = 5 bytes)
        msg_id_code = (
            bytes([self.slot_memory_type])
            + slot_number.to_bytes(2, "big")
            + loaded.crc
        )
        action_oid = f"{oids.DMS_ACTION_MSG_CODE_COL}.{action_index}"
        _, err = await ctx.snmp.set_one(action_oid, OctetString(msg_id_code))
        ctx.record_step(
            "set_action_msg_code",
            operation="SNMP_SET",
            oid_name="dmsActionMsgCode",
            oid=action_oid,
            value_read=msg_id_code.hex().upper(),
            success=err is None,
            error=err,
        )
        if err is not None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"SET dmsActionMsgCode falló con {err}.",
                error=err,
            )

        # Paso 3: activar scheduler — memType=6, msgNum=1, CRC=0x0000
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
            "activate_scheduler",
            operation="SNMP_SET",
            oid_name="dmsActivateMessage",
            oid=oids.DMS_ACTIVATE_MESSAGE,
            value_read=sched_code.hex().upper(),
            success=err is None,
            error=err,
            notes="memType=schedule(6), msgNum=1, CRC=0x0000",
        )
        if err is not None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Activación de scheduler falló: {err}",
                error=err,
            )

        raw_err, _ = await ctx.snmp.get_one(oids.DMS_ACTIVATE_MSG_ERROR)
        err_text = decoders.decode_activate_msg_error(raw_err)
        try:
            err_value = int(raw_err) if raw_err is not None else None
        except Exception:
            err_value = None
        ctx.record_step(
            "verify.activate_msg_error",
            operation="SNMP_GET",
            oid_name="dmsActivateMsgError",
            oid=oids.DMS_ACTIVATE_MSG_ERROR,
            value_read=err_text,
            success=err_value == 2,
        )
        if err_value != 2:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Panel rechazó activación del scheduler: {err_text}",
                error=err_text,
            )

        # Paso 4: verificar dmsMsgSourceMode = 9 + MULTI esperado
        await asyncio.sleep(self.settle_seconds)
        vals, _ = await ctx.snmp.get_many([oids.SRC_MODE, oids.MSG_SRC])
        src_text = decoders.decode_source_mode(vals.get(oids.SRC_MODE))
        try:
            src_value = int(vals.get(oids.SRC_MODE))
        except Exception:
            src_value = None
        mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))
        ctx.record_step(
            "verify.scheduler_active",
            operation="VERIFY",
            value_read={
                "src_mode": src_text,
                "msg_src": mid.get("raw_hex"),
                "memory_type": mid.get("memory_type"),
                "message_number": mid.get("message_number"),
            },
            success=src_value == 9,
        )

        if src_value != 9:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Panel aceptó la activación pero src_mode={src_text} "
                    f"(esperado timebasedScheduler(9))."
                ),
                design_impact=(
                    "El panel puede no haber iniciado el scheduler porque la "
                    "ventana del dayPlan no está activa, o porque requiere "
                    "carga previa de timeBaseScheduleTable (NTCIP 1201)."
                ),
            )

        msg_match = (
            mid["valid"]
            and mid["memory_type"] == self.slot_memory_type
            and mid["message_number"] == slot_number
        )
        if not msg_match:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Scheduler activo pero mensaje mostrado no coincide con "
                    f"el del slot {self.slot_memory_type}.{slot_number}."
                ),
                design_impact=(
                    "El panel selecciona otra acción del dmsActionTable — "
                    "verificar que action_index=1 sea el activo."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                "Scheduler local activado y mensaje correcto en pantalla "
                "(src_mode=timebasedScheduler)."
            ),
        )
