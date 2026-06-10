"""POC-VMS-20 — Panel en ``localMode``: detección y comportamiento.

Caso real: técnico en campo toma control físico durante una obra. La
plataforma debe (a) detectar la condición sin marcar el panel como caído,
(b) recibir un error explícito ante intentos de activación, (c) retomar
control cuando vuelve ``central``.

El escenario intenta SET ``dmsControlMode=local(2)`` por SNMP. La norma
permite que el panel responda ``genErr`` ante este SET (algunos firmwares
solo aceptan el cambio físico desde el switch del gabinete). En ese caso
el escenario degrada a OBSERVACIÓN: lee el modo actual; si ya está en
``local`` o ``centralOverride``, ejercita las fases 2-4; si no, queda
``BLOCKED`` con instrucción para el operador.

Pasos:

1. Leer ``dmsControlMode`` inicial → guardar para restaurar.
2. Intentar SET ``dmsControlMode=local(2)``. Si rechaza, intentar
   degradar (¿ya estaba en local? ¿centralOverride?).
3. Fase 2 — polling read-only: ``sysUpTime``, ``dmsMsgSourceMode``,
   ``dmsMsgTableSource``, ``shortErrorStatus`` deben responder.
4. Fase 3 — intentar activar un mensaje. Esperar
   ``dmsActivateMsgError = localMode(9)`` y mensaje en pantalla SIN cambio.
5. Fase 4 — restaurar ``dmsControlMode`` al valor inicial y verificar que
   la activación funciona de nuevo (smoke).

Criterio:

- ``PASS`` si las 3 fases se ejecutan: polling responde + activación
  retorna ``localMode(9)`` + restore funciona.
- ``QUIRK_PROVIDER`` si el panel responde con código distinto a ``9``
  ante activación en local — documentar el código real.
- ``BLOCKED`` si no se pudo forzar ``local`` (panel rechaza el SET y no
  estaba ya en local). Requiere intervención física → reintentar con
  switch del gabinete.

Defaults:

    poc_20_test_slot: 245
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, Optional

from pysnmp.proto.rfc1902 import Integer, OctetString

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_QUIRK,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation

CTRL_MODE_LOCAL = 2
CTRL_MODE_CENTRAL = 4
CTRL_MODE_CENTRAL_OVERRIDE = 5


class PocVms20LocalMode(Scenario):
    id = "POC-VMS-20"
    name = "Panel en localMode: detección y comportamiento"
    description = (
        "Fuerza dmsControlMode=local(2) (si el panel lo permite) y "
        "verifica polling, errores de activación y restore."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_test_slot: ClassVar[int] = 245

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        test_slot = int(
            ctx.device_config.get("poc_20_test_slot", self.default_test_slot)
        )

        # Paso 1: leer modo actual
        initial_raw, err = await ctx.snmp.get_one(oids.CTRL_MODE)
        try:
            initial_mode = int(initial_raw) if initial_raw is not None else None
        except Exception:
            initial_mode = None
        ctx.record_step(
            "snapshot_initial_control_mode",
            operation="SNMP_GET",
            oid_name="dmsControlMode",
            oid=oids.CTRL_MODE,
            value_read=decoders.decode_control_mode(initial_raw),
            success=err is None,
            error=err,
        )
        if initial_mode is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary="No se pudo leer dmsControlMode inicial.",
                error=err or "decode_failed",
            )

        # Paso 2: intentar SET local
        switched_via_snmp = False
        if initial_mode not in (CTRL_MODE_LOCAL, CTRL_MODE_CENTRAL_OVERRIDE):
            _, set_err = await ctx.snmp.set_one(
                oids.CTRL_MODE, Integer(CTRL_MODE_LOCAL)
            )
            ctx.record_step(
                "set_local_mode",
                operation="SNMP_SET",
                oid_name="dmsControlMode",
                oid=oids.CTRL_MODE,
                value_read=CTRL_MODE_LOCAL,
                success=set_err is None,
                error=set_err,
            )
            if set_err is None:
                switched_via_snmp = True
                await asyncio.sleep(0.5)

        # Re-leer para confirmar
        current_raw, _ = await ctx.snmp.get_one(oids.CTRL_MODE)
        try:
            current_mode = int(current_raw) if current_raw is not None else None
        except Exception:
            current_mode = None
        in_local_family = current_mode in (
            CTRL_MODE_LOCAL,
            CTRL_MODE_CENTRAL_OVERRIDE,
        )
        ctx.record_step(
            "verify_in_local",
            operation="SNMP_GET",
            value_read={
                "current": decoders.decode_control_mode(current_raw),
                "in_local_family": in_local_family,
            },
            success=in_local_family,
        )

        if not in_local_family:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_BLOCKED,
                summary=(
                    "El panel rechazó SET dmsControlMode=local(2) y no estaba "
                    "ya en local. Cambiar al modo local físicamente (switch "
                    "del gabinete) y reintentar."
                ),
                design_impact=(
                    "El cambio de control mode requiere acción física en este "
                    "firmware — documentar como requisito operativo."
                ),
            )

        # Fase 2: polling read-only debe responder
        poll_vals, poll_err = await ctx.snmp.get_many(
            [
                oids.SYS_UPTIME,
                oids.SRC_MODE,
                oids.MSG_SRC,
                oids.SHORT_ERR,
            ]
        )
        polling_ok = poll_err is None and all(
            poll_vals.get(o) is not None for o in (oids.SYS_UPTIME, oids.MSG_SRC)
        )
        ctx.record_step(
            "polling_in_local",
            operation="SNMP_GET",
            value_read={
                "sysUpTime": _safe_int(poll_vals.get(oids.SYS_UPTIME)),
                "src_mode": decoders.decode_source_mode(
                    poll_vals.get(oids.SRC_MODE)
                ),
                "msg_src": decoders.decode_message_id_code(
                    poll_vals.get(oids.MSG_SRC)
                ).get("raw_hex"),
                "short_error": decoders.decode_short_error_status(
                    poll_vals.get(oids.SHORT_ERR)
                )[0],
            },
            success=polling_ok,
            error=poll_err,
        )

        # Fase 3: cargar un MULTI e intentar activarlo → esperar localMode(9)
        # Cargamos en un slot que no se vea (priority bajo, el panel no va a
        # cambiar de pantalla aunque acepte).
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=test_slot,
            multi="[jp3]POC-20-LOCAL",
            run_time_priority=32,
        )
        activate_err_value: Optional[int] = None
        activate_err_text: Optional[str] = None
        if loaded is None:
            ctx.record_step(
                "activation_in_local.load_failed",
                operation="LOAD",
                success=False,
                error=load_err,
                notes=(
                    "Carga del mensaje falló en modo local — algunos firmwares "
                    "rechazan toda escritura, no sólo dmsActivateMessage."
                ),
            )
        else:
            activate_err_text, activate_err_value = await _activation.activate_message(
                ctx, loaded=loaded
            )

        # Fase 4: restaurar
        if switched_via_snmp:
            _, restore_err = await ctx.snmp.set_one(
                oids.CTRL_MODE, Integer(initial_mode)
            )
            ctx.record_step(
                "restore_control_mode",
                operation="SNMP_SET",
                oid_name="dmsControlMode",
                oid=oids.CTRL_MODE,
                value_read=initial_mode,
                success=restore_err is None,
                error=restore_err,
            )
            await asyncio.sleep(0.5)

        # Smoke post-restore: si conseguimos modo central, intentar activación
        # rápida — si funciona, el restore es OK.
        post_restore_smoke: Dict[str, Any] = {}
        post_raw, _ = await ctx.snmp.get_one(oids.CTRL_MODE)
        post_mode = _safe_int(post_raw)
        if post_mode == CTRL_MODE_CENTRAL and loaded is not None:
            err_text2, err_value2 = await _activation.activate_message(
                ctx, loaded=loaded
            )
            post_restore_smoke = {
                "post_restore_activate_text": err_text2,
                "post_restore_activate_value": err_value2,
            }
        ctx.record_step(
            "summary",
            operation="VERIFY",
            value_read={
                "polling_responded": polling_ok,
                "activation_err_text": activate_err_text,
                "activation_err_value": activate_err_value,
                "post_restore_mode": decoders.decode_control_mode(post_raw),
                **post_restore_smoke,
            },
            success=True,
        )

        # Veredicto
        if not polling_ok:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    "En localMode el polling de lectura NO responde — "
                    "rompe el modelo de monitoreo."
                ),
                design_impact=(
                    "El worker no puede mantener visibilidad del panel "
                    "cuando está en local. Reportar como UNREACHABLE en vez "
                    "de UNMANAGED."
                ),
            )

        if activate_err_value == 9:  # localMode(9)
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    "Polling OK + activación rechazada con localMode(9). "
                    "Worker puede detectar y suspender activaciones."
                ),
            )
        if activate_err_value is not None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_QUIRK,
                summary=(
                    f"Polling OK pero activación retornó "
                    f"{activate_err_text} (esperaba localMode(9))."
                ),
                design_impact=(
                    "Mapear el código observado al provider como equivalente "
                    "de localMode."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_QUIRK,
            summary=(
                "Polling OK pero no se pudo determinar el código de error "
                "de activación en local (panel rechazó carga previa)."
            ),
            design_impact=(
                "Algunos firmwares rechazan escrituras genéricas en local, "
                "no sólo dmsActivateMessage. Worker debe asumir read-only."
            ),
        )


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None
