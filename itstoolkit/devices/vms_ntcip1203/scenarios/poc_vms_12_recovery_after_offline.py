"""POC-VMS-12 — Recovery tras pérdida de comunicación.

> ⚠️ **REQUIRES_PHYSICAL** — el operador corta y restaura la conectividad
> de red durante la ventana de observación. El escenario es read-only.

Valida qué estado retiene el panel después de un período offline y qué
debe hacer la plataforma al recuperar comunicación. En ruta 102 con
conectividad semi-estable este es el caso cotidiano.

Pasos:

1. Snapshot inicial: ``sysUpTime``, ``dmsControlMode``, ``dmsMsgSourceMode``,
   ``dmsMsgTableSource``, ``shortErrorStatus``, MULTI activo + hash.
2. El escenario imprime una instrucción y espera ``offline_seconds``.
   Durante esa ventana el operador debe **cortar la red** (Ethernet,
   firewall, o interfaz WAN del router) y **restaurarla antes de que la
   ventana termine**.
3. Poll cada ``poll_interval_s`` para detectar timeout SNMP (panel offline)
   y luego recovery (vuelve a responder).
4. Snapshot final + comparación campo-por-campo con el inicial.

Criterio:

- ``PASS`` si la red cayó y volvió durante la ventana **y** se pudo tomar
  snapshot post-recovery: la plataforma puede decidir determinísticamente.
- ``PARTIAL`` si no se detectó caída de red (operador no intervino) o si la
  conexión no volvió dentro de la ventana.
- ``FAIL`` si no se pudo tomar snapshot inicial.

Defaults pensados para una corrida cómoda. Para reproducir el caso de
offline largo de la spec (>300s), configurá:

    poc_12_offline_seconds: 360
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


class PocVms12RecoveryAfterOffline(Scenario):
    id = "POC-VMS-12"
    name = "Recovery tras pérdida de comunicación"
    description = (
        "Observa el estado del panel antes y después de una caída de red. "
        "Requiere que el operador corte y restaure la conectividad durante "
        "la ventana de observación."
    )
    execution_mode = EXEC_REQUIRES_PHYSICAL
    requires_write = False

    default_offline_seconds: ClassVar[float] = 60.0
    default_poll_interval_s: ClassVar[float] = 3.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        offline_window = float(
            ctx.device_config.get(
                "poc_12_offline_seconds", self.default_offline_seconds
            )
        )
        poll_interval = float(
            ctx.device_config.get(
                "poc_12_poll_interval_s", self.default_poll_interval_s
            )
        )

        ctx.record_step(
            "physical_action_expected",
            operation="LOCAL",
            notes=(
                f"Operador: cortar la red del panel (Ethernet/firewall/WAN) "
                f"y RESTAURARLA antes de que terminen los "
                f"{offline_window:.0f}s de ventana."
            ),
            success=True,
        )

        before, err = await self._snapshot(ctx, label="before")
        if before is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo leer estado inicial: {err}",
                error=err,
            )

        # Poll loop: detectar offline → detectar recovery → snapshot after
        deadline = asyncio.get_event_loop().time() + offline_window
        saw_offline = False
        saw_recovery = False
        polls = 0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_interval)
            polls += 1
            val, err = await ctx.snmp.get_one(oids.SYS_UPTIME)
            if err is not None or val is None:
                if not saw_offline:
                    saw_offline = True
                    ctx.record_step(
                        "detected_offline",
                        operation="SNMP_GET",
                        oid_name="sysUpTime",
                        success=False,
                        error=err or "no_response",
                        polls_until_offline=polls,
                    )
            else:
                if saw_offline:
                    saw_recovery = True
                    ctx.record_step(
                        "detected_recovery",
                        operation="SNMP_GET",
                        oid_name="sysUpTime",
                        value_read=int(val) if val is not None else None,
                        success=True,
                        polls_until_recovery=polls,
                    )
                    break

        if not saw_offline:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"No se detectó caída de red en {offline_window:.0f}s "
                    f"({polls} polls). El operador no intervino."
                ),
                design_impact=(
                    "Re-ejecutar tras cortar la red; o aumentar "
                    "poc_12_offline_seconds en el YAML."
                ),
            )
        if not saw_recovery:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Red cayó pero NO se recuperó en la ventana "
                    f"({offline_window:.0f}s). El panel sigue offline al "
                    f"cierre del escenario."
                ),
                design_impact=(
                    "Confirmar que el operador restauró la red. Ampliar "
                    "poc_12_offline_seconds para tests de offline largo."
                ),
            )

        after, err = await self._snapshot(ctx, label="after")
        if after is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Red recuperada pero no se pudo tomar snapshot final: "
                    f"{err}. Reintento sería útil."
                ),
                error=err,
            )

        # Comparar campo a campo
        diffs: Dict[str, Tuple[Any, Any]] = {}
        for k in ("ctrl_text", "src_text", "msg_id_raw", "multi_hash"):
            if before.get(k) != after.get(k):
                diffs[k] = (before.get(k), after.get(k))

        # sysUpTime se compara aparte: post-recovery debe ser > pre (no reset)
        uptime_reset = (
            isinstance(before.get("sys_uptime"), int)
            and isinstance(after.get("sys_uptime"), int)
            and after["sys_uptime"] < before["sys_uptime"]
        )

        ctx.record_step(
            "compare_pre_post",
            operation="VERIFY",
            value_read={
                "before": before,
                "after": after,
                "diffs": {k: {"before": v[0], "after": v[1]} for k, v in diffs.items()},
                "uptime_reset_observed": uptime_reset,
            },
            success=True,
        )

        summary_bits = []
        if diffs:
            summary_bits.append(f"cambios: {', '.join(diffs.keys())}")
        else:
            summary_bits.append("estado IDÉNTICO antes/después")
        if uptime_reset:
            summary_bits.append("sysUpTime RESETEÓ (reboot incidental)")

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Offline detectado y recuperación OK. "
                + " | ".join(summary_bits)
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
