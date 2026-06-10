"""POC-VMS-19 — Recuperación de slot tras escritura parcial.

Simula una secuencia de escritura interrumpida (modifyReq + escribir MULTI
sin llegar a validateReq) y prueba si el slot puede recuperarse con
``notUsedReq`` y reescribirse limpio.

Esto define una pieza chica pero importante del ``MessageLoader``:
¿hay que hacer limpieza preventiva (``notUsedReq``) antes de cada
escritura, o el panel se autorecupera?

Pasos:

1. Snapshot del slot inicial → registrar ``dmsMessageStatus``.
2. Fase A (escritura parcial):
   a. SET ``dmsMessageStatus = modifyReq`` → esperar ``modifying``.
   b. Escribir MULTI parcial.
   c. **NO** disparar ``validateReq``: aquí es donde simulamos la
      interrupción.
3. Snapshot post-interrupción → debería estar en ``modifying(3)``.
4. Fase B (recuperación con notUsedReq):
   a. SET ``dmsMessageStatus = notUsedReq`` → esperar ``notUsed``.
   b. Snapshot → estado, MULTI residual.
5. Fase C (re-escritura exitosa):
   a. Ritual completo (modifyReq → write → validateReq → CRC).
   b. Activar y verificar.

Criterio:

- ``PASS`` si ``notUsedReq`` recupera el slot Y la re-escritura llega a
  ``valid(4)`` Y la activación responde ``none(2)``.
- ``QUIRK_PROVIDER`` si ``notUsedReq`` falla pero un re-``modifyReq``
  directo recupera el slot — documentar la secuencia alternativa.
- ``FAIL`` si el slot queda bloqueado y no se puede recuperar por SNMP.

Defaults:

    poc_19_slot: 249
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Optional, Tuple

from pysnmp.proto.rfc1902 import Integer, OctetString

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_QUIRK,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation


class PocVms19PartialWriteRecovery(Scenario):
    id = "POC-VMS-19"
    name = "Recuperación de slot tras escritura parcial"
    description = (
        "Simula una escritura interrumpida (modifyReq + write sin "
        "validateReq) y prueba si notUsedReq recupera el slot."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_slot: ClassVar[int] = 249

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        slot = int(ctx.device_config.get("poc_19_slot", self.default_slot))
        status_oid = _activation.row_oid(
            oids.DMS_MSG_STATUS_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )
        multi_oid = _activation.row_oid(
            oids.DMS_MSG_MULTI_STRING_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )
        owner_oid = _activation.row_oid(
            oids.DMS_MSG_OWNER_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )
        priority_oid = _activation.row_oid(
            oids.DMS_MSG_RUN_TIME_PRIORITY_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )

        # Snapshot inicial
        initial_status, _ = await ctx.snmp.get_one(status_oid)
        ctx.record_step(
            "snapshot_initial",
            operation="SNMP_GET",
            oid_name="dmsMessageStatus",
            oid=status_oid,
            value_read=decoders.decode_message_status(initial_status),
            success=True,
            slot=slot,
        )

        # Fase A — escritura parcial intencional
        _, err = await ctx.snmp.set_one(
            status_oid, Integer(oids.MSG_STATUS_MODIFY_REQ)
        )
        ctx.record_step(
            "phaseA.set_modifyReq",
            operation="SNMP_SET",
            oid_name="dmsMessageStatus",
            value_read=oids.MSG_STATUS_MODIFY_REQ,
            success=err is None,
            error=err,
        )
        if err is not None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"SET modifyReq inicial falló: {err}",
                error=err,
            )

        # Esperar 'modifying' (sin usar el helper privado del módulo;
        # acá replicamos el poll inline para mantener foco del escenario).
        state_value, wait_err = await _wait_until(
            ctx,
            status_oid,
            desired=oids.MSG_STATUS_MODIFYING,
            timeout=5.0,
            interval=0.2,
        )
        ctx.record_step(
            "phaseA.wait_modifying",
            operation="SNMP_GET",
            value_read=decoders.decode_message_status(state_value),
            success=wait_err is None,
            error=wait_err,
        )
        if wait_err is not None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Slot no llegó a 'modifying' tras modifyReq: {wait_err}"
                ),
                error=wait_err,
            )

        # Escribir CONTENIDO parcial, pero NO disparamos validateReq.
        partial_multi = "[jp3]POC-19-PARTIAL"
        _, err = await ctx.snmp.set_many(
            [
                (multi_oid, OctetString(partial_multi.encode("utf-8"))),
                (owner_oid, OctetString(b"itstoolkit-poc-19")),
                (priority_oid, Integer(32)),
            ]
        )
        ctx.record_step(
            "phaseA.write_partial",
            operation="SNMP_SET",
            oid_name="dmsMessageMultiString+owner+priority",
            value_read={"multi_partial": partial_multi},
            success=err is None,
            error=err,
            notes="Se omite validateReq intencionalmente — simulamos interrupción.",
        )
        # No retornamos error acá: el punto es la recuperación, no la
        # escritura parcial.

        post_interrupt_status, _ = await ctx.snmp.get_one(status_oid)
        ctx.record_step(
            "phaseA.snapshot_post_interrupt",
            operation="SNMP_GET",
            oid_name="dmsMessageStatus",
            value_read=decoders.decode_message_status(post_interrupt_status),
            success=True,
            notes=(
                "Se espera 'modifying(3)' — el slot quedó a la espera de "
                "validateReq que nunca llegó."
            ),
        )

        # Fase B — recuperación con notUsedReq
        recovery_kind, recovery_err = await self._try_recovery(
            ctx, status_oid=status_oid
        )
        if recovery_kind is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Slot quedó bloqueado: ni notUsedReq ni re-modifyReq "
                    f"lo recuperaron ({recovery_err})."
                ),
                error=recovery_err,
                design_impact=(
                    "Esos slots requieren intervención del fabricante. "
                    "MessageLoader debe evitar la región afectada."
                ),
            )

        # Fase C — re-escritura completa exitosa
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=slot,
            multi="[jp3]POC19OK",
            run_time_priority=32,
        )
        if loaded is None:
            # Hallazgo importante: el slot reporta notUsed/modifying tras la
            # recuperación pero la re-validación falla. Leemos los detalles
            # de error para enriquecer la evidencia.
            syntax_raw, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR
            )
            pos_raw, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR_POSITION
            )
            final_status_raw, _ = await ctx.snmp.get_one(status_oid)
            ctx.record_step(
                "phaseC.rewrite_failed_diagnostics",
                operation="SNMP_GET",
                value_read={
                    "dmsMultiSyntaxError": decoders.decode_multi_syntax_error(
                        syntax_raw
                    ),
                    "dmsMultiSyntaxErrorPosition": (
                        int(pos_raw) if pos_raw is not None else None
                    ),
                    "dmsMessageStatus": decoders.decode_message_status(
                        final_status_raw
                    ),
                    "load_err": load_err,
                },
                success=False,
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_QUIRK,
                summary=(
                    f"Recovery {recovery_kind} reportó éxito pero la "
                    f"re-escritura posterior NO valida ({load_err}). El "
                    f"slot NO es realmente reutilizable tras una "
                    f"interrupción."
                ),
                design_impact=(
                    "MessageLoader debe asumir que tras una escritura "
                    "interrumpida el slot queda inservible hasta un reboot "
                    "del panel — rotar a un slot diferente, no reusar."
                ),
            )

        err_text, err_value = await _activation.activate_message(
            ctx, loaded=loaded
        )
        if err_value != 2:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Slot recuperado y re-escrito, pero la activación "
                    f"final falló con {err_text}."
                ),
                error=err_text,
            )

        if recovery_kind == "notUsedReq":
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    "Recuperación limpia con notUsedReq + re-escritura + "
                    "activación. MessageLoader puede confiar en notUsedReq."
                ),
            )
        # recovery_kind == "modifyReq_overwrite"
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_QUIRK,
            summary=(
                "notUsedReq fue rechazado; el slot se recuperó con un "
                "modifyReq directo (overwrite). Re-escritura OK."
            ),
            design_impact=(
                "MessageLoader debe intentar notUsedReq primero y, ante "
                "fallo, hacer overwrite directo en vez de abortar."
            ),
        )

    async def _try_recovery(
        self, ctx: ScenarioContext, *, status_oid: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Devuelve (kind, error). kind = 'notUsedReq' | 'modifyReq_overwrite' | None."""
        # Intento 1: notUsedReq
        _, err = await ctx.snmp.set_one(
            status_oid, Integer(oids.MSG_STATUS_NOT_USED_REQ)
        )
        ctx.record_step(
            "phaseB.try_notUsedReq",
            operation="SNMP_SET",
            value_read=oids.MSG_STATUS_NOT_USED_REQ,
            success=err is None,
            error=err,
        )
        if err is None:
            state, wait_err = await _wait_until(
                ctx,
                status_oid,
                desired=oids.MSG_STATUS_NOT_USED,
                timeout=5.0,
                interval=0.2,
            )
            ctx.record_step(
                "phaseB.wait_notUsed",
                operation="SNMP_GET",
                value_read=decoders.decode_message_status(state),
                success=wait_err is None,
                error=wait_err,
            )
            if wait_err is None:
                return "notUsedReq", None

        # Intento 2: re-modifyReq directo
        _, err = await ctx.snmp.set_one(
            status_oid, Integer(oids.MSG_STATUS_MODIFY_REQ)
        )
        ctx.record_step(
            "phaseB.try_modifyReq_overwrite",
            operation="SNMP_SET",
            value_read=oids.MSG_STATUS_MODIFY_REQ,
            success=err is None,
            error=err,
        )
        if err is not None:
            return None, f"modifyReq_overwrite_failed:{err}"
        state, wait_err = await _wait_until(
            ctx,
            status_oid,
            desired=oids.MSG_STATUS_MODIFYING,
            timeout=5.0,
            interval=0.2,
        )
        if wait_err is None:
            return "modifyReq_overwrite", None
        return None, f"modifyReq_overwrite_no_state:{wait_err}"


async def _wait_until(
    ctx: ScenarioContext,
    oid: str,
    *,
    desired: int,
    timeout: float,
    interval: float,
) -> Tuple[Optional[int], Optional[str]]:
    deadline = asyncio.get_event_loop().time() + timeout
    last: Optional[int] = None
    while True:
        val, err = await ctx.snmp.get_one(oid)
        if err is not None:
            return None, err
        try:
            last = int(val) if val is not None else None
        except Exception:
            last = None
        if last == desired:
            return last, None
        if asyncio.get_event_loop().time() >= deadline:
            return last, "TIMEOUT_WAITING_STATE"
        await asyncio.sleep(interval)
