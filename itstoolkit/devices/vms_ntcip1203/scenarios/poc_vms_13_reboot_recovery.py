"""POC-VMS-13 — Reboot físico del panel.

> ⚠️ **REQUIRES_PHYSICAL** — el operador corta la alimentación o ejecuta
> reset desde la consola del VFC. El escenario es read-only.

Documenta qué se pierde / qué persiste tras un reboot. El modo de falla
conocido del Daktronics/Chainzone es que el scheduler queda en estado
``timeBaseScheduleTableStatus = 0`` tras un reboot — sin este escenario el
panel puede quedar mostrando el mensaje de ``powerRecovery(10)``
indefinidamente.

Pasos:

1. Snapshot pre-reboot: ``sysUpTime``, ``dmsControlMode``,
   ``dmsMsgSourceMode``, ``dmsMsgTableSource``, ``shortErrorStatus``,
   MULTI activo + hash, ``dmsNumChangeableMsg``.
2. Imprime instrucción al operador y entra en poll loop esperando que
   ``sysUpTime`` **baje** respecto del valor registrado (indicador clásico
   de reboot). Timeout configurable.
3. Snapshot post-reboot: mismos campos que (1).
4. Comparación: qué persistió, qué cambió, qué se reseteó.

Criterio:

- ``PASS`` si se detectó el reboot (``sysUpTime`` bajó) y se pudo tomar
  snapshot post-reboot: la plataforma tiene insumo para diseñar la
  secuencia de recuperación.
- ``PARTIAL`` si no se detectó reboot (operador no intervino o tomó más
  que el timeout).
- ``FAIL`` si no se pudo tomar snapshot inicial.

.. note::

   La spec original tiene 4 fases (Fase 4 = secuencia de recuperación con
   recarga de mensajes y reactivación de scheduler). Esa fase requiere
   writes + dayPlan loading y queda **fuera** de este escenario. POC-13 v2
   puede extenderla cuando los OIDs de NTCIP 1201 dayPlanTable estén
   verificados contra firmware real.

Defaults:

    poc_13_max_wait_seconds: 300         # 5 min para que el operador reboot
    poc_13_poll_interval_s: 5            # cada 5s chequea sysUpTime
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, Optional, Tuple

from itstoolkit.core.scenario import (
    EXEC_REQUIRES_PHYSICAL,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    Scenario,
    ScenarioContext,
    ScenarioResult,
    hash_multi,
)
from itstoolkit.protocols.snmp import values as snmp_values

from .. import decoders, oids


class PocVms13RebootRecovery(Scenario):
    id = "POC-VMS-13"
    name = "Reboot físico del panel"
    description = (
        "Detecta reboot vía caída de sysUpTime y registra qué estado se "
        "perdió. Requiere que el operador reinicie el panel durante la "
        "ventana de espera."
    )
    execution_mode = EXEC_REQUIRES_PHYSICAL
    requires_write = False

    default_max_wait_seconds: ClassVar[float] = 300.0
    default_poll_interval_s: ClassVar[float] = 5.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        max_wait = float(
            ctx.device_config.get(
                "poc_13_max_wait_seconds", self.default_max_wait_seconds
            )
        )
        poll_interval = float(
            ctx.device_config.get(
                "poc_13_poll_interval_s", self.default_poll_interval_s
            )
        )

        before, err = await self._snapshot(ctx, label="pre_reboot")
        if before is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo leer estado pre-reboot: {err}",
                error=err,
            )
        baseline_uptime = before.get("sys_uptime")
        if not isinstance(baseline_uptime, int):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"sysUpTime no decodifica como entero "
                    f"({before.get('sys_uptime')!r}); no se puede detectar reboot."
                ),
            )

        ctx.record_step(
            "physical_action_expected",
            operation="LOCAL",
            notes=(
                f"Operador: hacer reboot del panel (cortar alimentación o "
                f"reset desde consola VFC). Esperando hasta {max_wait:.0f}s "
                f"que sysUpTime baje de {baseline_uptime}."
            ),
            success=True,
        )

        # Poll loop: detectar drop de sysUpTime
        deadline = asyncio.get_event_loop().time() + max_wait
        polls = 0
        detected_uptime: Optional[int] = None
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_interval)
            polls += 1
            val, snmp_err = await ctx.snmp.get_one(oids.SYS_UPTIME)
            # Durante el reboot el panel deja de responder; consideramos eso
            # parte del flujo (no fallo).
            if snmp_err is not None or val is None:
                continue
            try:
                current = int(val)
            except Exception:
                continue
            if current < baseline_uptime:
                detected_uptime = current
                ctx.record_step(
                    "detected_reboot",
                    operation="SNMP_GET",
                    oid_name="sysUpTime",
                    value_read={
                        "baseline": baseline_uptime,
                        "post_reboot": current,
                        "polls": polls,
                    },
                    success=True,
                )
                break

        if detected_uptime is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"No se detectó reboot en {max_wait:.0f}s "
                    f"({polls} polls). sysUpTime no bajó."
                ),
                design_impact=(
                    "Re-ejecutar tras hacer el reboot; o aumentar "
                    "poc_13_max_wait_seconds en el YAML."
                ),
            )

        after, err = await self._snapshot(ctx, label="post_reboot")
        if after is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Reboot detectado pero no se pudo leer estado final: "
                    f"{err}. El panel puede estar todavía inicializándose."
                ),
                error=err,
            )

        # Comparación campo a campo
        diffs: Dict[str, Any] = {}
        for k in (
            "ctrl_text",
            "src_text",
            "msg_id_raw",
            "multi_hash",
            "short_error",
        ):
            if before.get(k) != after.get(k):
                diffs[k] = {"before": before.get(k), "after": after.get(k)}

        ctx.record_step(
            "compare_pre_post",
            operation="VERIFY",
            value_read={
                "before": before,
                "after": after,
                "diffs": diffs,
            },
            success=True,
        )

        # Información clave: ¿el panel quedó en powerRecovery?
        post_src = after.get("src_text") or ""
        is_power_recovery = post_src.startswith("powerRecovery")

        summary_bits = [f"reboot detectado (uptime {baseline_uptime}→{detected_uptime})"]
        if is_power_recovery:
            summary_bits.append("src=powerRecovery(10) — confirmado modo de falla conocido")
        if diffs:
            summary_bits.append(f"cambios: {', '.join(diffs.keys())}")
        else:
            summary_bits.append("estado idéntico (panel restauró todo)")

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=" | ".join(summary_bits),
            design_impact=(
                "Polling debe detectar caída de sysUpTime y disparar "
                "secuencia de recuperación: verificar mensaje activo, "
                "reactivar scheduler si dmsMsgSourceMode != "
                "timebasedScheduler(9)."
            ),
        )

    async def _snapshot(
        self, ctx: ScenarioContext, *, label: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        vals, err = await ctx.snmp.get_many(
            [
                oids.SYS_UPTIME,
                oids.CTRL_MODE,
                oids.SRC_MODE,
                oids.MSG_SRC,
                oids.SHORT_ERR,
                oids.DMS_NUM_CHANGEABLE_MSG,
            ]
        )
        if err in ("TIMEOUT", "SNMP_ERROR"):
            ctx.record_step(
                f"snapshot.{label}",
                operation="SNMP_GET",
                success=False,
                error=err,
            )
            return None, err

        ctrl_text = decoders.decode_control_mode(vals.get(oids.CTRL_MODE))
        src_text = decoders.decode_source_mode(vals.get(oids.SRC_MODE))
        err_text, err_raw = decoders.decode_short_error_status(
            vals.get(oids.SHORT_ERR)
        )
        mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))
        try:
            sys_uptime = int(vals.get(oids.SYS_UPTIME))
        except Exception:
            sys_uptime = None
        try:
            num_changeable = int(vals.get(oids.DMS_NUM_CHANGEABLE_MSG))
        except Exception:
            num_changeable = None

        multi_hash: Optional[str] = None
        multi_text: Optional[str] = None
        if mid["valid"]:
            multi_oid_str = oids.multi_oid(
                mid["memory_type"], mid["message_number"]
            )
            raw, multi_err = await ctx.snmp.get_one(multi_oid_str)
            if multi_err is None and raw is not None:
                multi_text = snmp_values.decode_octet_text(raw) or ""
                multi_hash = hash_multi(multi_text)

        snap = {
            "sys_uptime": sys_uptime,
            "ctrl_text": ctrl_text,
            "src_text": src_text,
            "msg_id_raw": mid.get("raw_hex"),
            "short_error": err_text,
            "short_error_raw": err_raw,
            "num_changeable_msg": num_changeable,
            "multi_text": multi_text,
            "multi_hash": multi_hash,
        }
        ctx.record_step(
            f"snapshot.{label}",
            operation="SNMP_GET",
            value_read=snap,
            success=True,
        )
        return snap, None
