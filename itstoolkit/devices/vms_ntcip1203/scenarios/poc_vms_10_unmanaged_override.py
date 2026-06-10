"""POC-VMS-10 — Detección de override externo / UNMANAGED.

> ⚠️ **REQUIRES_PHYSICAL** — antes de correr este escenario, el operador
> debe activar manualmente un mensaje en el panel (vía switch local del
> gabinete, consola web del fabricante u otro cliente SNMP). El escenario
> NO escribe — solo lee y clasifica.

Valida que la plataforma puede detectar un cambio realizado fuera de
ella (típicamente un técnico en campo) sin pisarlo automáticamente. Es
el caso de uso real de la ruta 102.

Pasos:

1. Snapshot inicial: ``dmsControlMode``, mensaje activo, hash.
2. Esperar ``observation_seconds`` para dar tiempo a la intervención
   manual (el operador ya la disparó antes de lanzar el escenario; este
   sleep solo asegura que el panel propagó el cambio).
3. Snapshot final + clasificación.
4. Reportar ``UNMANAGED`` si:
   - el hash del MULTI cambió respecto del inicial, y/o
   - ``dmsControlMode`` pasó a ``local(2)`` / ``centralOverride(5)``.

El scenario es read-only: no requiere ``confirm_write``. Aunque su modo
es ``REQUIRES_PHYSICAL``, el runner lo ejecuta igual — el "physical"
refiere a la acción del operador, no a la habilitación del gate.

Criterio:

- ``PASS`` si se detecta cualquier evidencia de override (cambio de hash o
  cambio de ``dmsControlMode``) — el algoritmo de UNMANAGED funciona.
- ``PARTIAL`` si no hay cambio observable (el operador no llegó a
  intervenir, o el panel está en estado idéntico al inicial).
- ``FAIL`` si no se puede leer el estado en ninguno de los dos puntos.
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


class PocVms10UnmanagedOverride(Scenario):
    id = "POC-VMS-10"
    name = "Detección de override externo / UNMANAGED"
    description = (
        "Detecta cambios realizados fuera de la plataforma (consola del "
        "fabricante, switch local, otro cliente SNMP) sin pisarlos. "
        "Requiere intervención física previa del operador."
    )
    execution_mode = EXEC_REQUIRES_PHYSICAL
    requires_write = False

    #: Tiempo de observación entre snapshots (segundos).
    observation_seconds: ClassVar[float] = 15.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        ctx.record_step(
            "physical_action_expected",
            operation="LOCAL",
            notes=(
                "Operador debe activar un mensaje externo (switch local / "
                "consola fabricante / otro cliente SNMP) antes o durante "
                f"la ventana de observación de {self.observation_seconds:.0f}s."
            ),
            success=True,
        )

        # Snapshot inicial
        before, err_before = await self._snapshot(ctx, label="before")
        if before is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo leer estado inicial: {err_before}",
                error=err_before,
            )

        await asyncio.sleep(self.observation_seconds)

        after, err_after = await self._snapshot(ctx, label="after")
        if after is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo leer estado final: {err_after}",
                error=err_after,
            )

        ctrl_changed = before["ctrl_value"] != after["ctrl_value"]
        ctrl_local_or_override = after["ctrl_value"] in (2, 5)  # local / centralOverride
        multi_changed = before["multi_hash"] != after["multi_hash"]
        msg_id_changed = before["msg_id_raw"] != after["msg_id_raw"]

        signals = []
        if multi_changed:
            signals.append("multi_hash")
        if msg_id_changed:
            signals.append("msg_id")
        if ctrl_changed:
            signals.append(
                f"ctrl({before['ctrl_text']}→{after['ctrl_text']})"
            )
        if ctrl_local_or_override:
            signals.append("ctrl_now_local_or_override")

        ctx.record_step(
            "classify",
            operation="VERIFY",
            value_read={
                "before": {
                    "ctrl": before["ctrl_text"],
                    "msg_id": before["msg_id_raw"],
                    "multi_sha256": before["multi_hash"],
                },
                "after": {
                    "ctrl": after["ctrl_text"],
                    "msg_id": after["msg_id_raw"],
                    "multi_sha256": after["multi_hash"],
                },
                "signals_detected": signals,
            },
            success=True,
        )

        if not signals:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Sin cambios observables en {self.observation_seconds:.0f}s. "
                    "El operador puede no haber intervenido."
                ),
                design_impact=(
                    "Re-ejecutar tras realizar el cambio externo; o aumentar "
                    "observation_seconds si la red tiene latencia alta."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Override detectado y clasificable como UNMANAGED. "
                f"Señales: {', '.join(signals)}."
            ),
        )

    async def _snapshot(
        self, ctx: ScenarioContext, *, label: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        vals, err = await ctx.snmp.get_many(
            [oids.CTRL_MODE, oids.SRC_MODE, oids.MSG_SRC]
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
        try:
            ctrl_value = int(vals.get(oids.CTRL_MODE))
        except Exception:
            ctrl_value = None
        mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))

        multi_hash = None
        multi_text = None
        if mid["valid"]:
            multi_oid_str = oids.multi_oid(
                mid["memory_type"], mid["message_number"]
            )
            raw, multi_err = await ctx.snmp.get_one(multi_oid_str)
            if multi_err is None and raw is not None:
                multi_text = snmp_values.decode_octet_text(raw) or ""
                multi_hash = hash_multi(multi_text)

        snap = {
            "ctrl_text": ctrl_text,
            "ctrl_value": ctrl_value,
            "msg_id_raw": mid.get("raw_hex"),
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
