"""POC-VMS-06 — Modelo de prioridades: manual vs manual.

Valida que el panel respeta ``dmsMessageRunTimePriority`` cuando recibe
sucesivas activaciones con distinta ``activatePriority``. Determina el
mapeo correcto entre los 6 niveles funcionales de Serviam
(``INFORMATIVE`` … ``AUTHORITY``) y el rango 1-255 del panel.

Matriz de casos (sobre el mismo slot, con priority base = 128):

+-----+------------------+--------------------------+
| Idx | activatePriority | Resultado esperado       |
+-----+------------------+--------------------------+
| 1   | 64  (<)          | priority(3), no cambia   |
| 2   | 128 (=)          | none(2), acepta          |
| 3   | 192 (>)          | none(2), acepta          |
+-----+------------------+--------------------------+

Fase 2 — AUTHORITY (runTimePriority=254) resiste todo salvo igual/mayor:

+-----+------------------+--------------------------+
| Idx | activatePriority | Resultado esperado       |
+-----+------------------+--------------------------+
| 4   | 192 (<)          | priority(3)              |
| 5   | 253 (<)          | priority(3)              |
| 6   | 254 (=)          | none(2)                  |
| 7   | 255 (>)          | none(2)                  |
+-----+------------------+--------------------------+

Criterio:

- ``PASS`` si los 7 casos producen el resultado esperado.
- ``PARTIAL`` si la mayoría calza y hay 1-2 desvíos (mapeo ajustable).
- ``FAIL`` si el panel ignora ``dmsMessageRunTimePriority`` o si la carga
    del mensaje base falla.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar, List, Tuple

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import oids
from . import _activation


# (idx, activate_priority, expected_err_value, descripcion)
PHASE1_CASES: List[Tuple[int, int, int, str]] = [
    (1, 64, 3, "manual<manual → priority(3)"),
    (2, 128, 2, "manual=manual → none(2)"),
    (3, 192, 2, "manual>manual → none(2)"),
]
PHASE2_CASES: List[Tuple[int, int, int, str]] = [
    (4, 192, 3, "<AUTHORITY → priority(3)"),
    (5, 253, 3, "<AUTHORITY → priority(3)"),
    (6, 254, 2, "=AUTHORITY → none(2)"),
    (7, 255, 2, ">AUTHORITY → none(2)"),
]


class PocVms06PriorityModel(Scenario):
    id = "POC-VMS-06"
    name = "Modelo de prioridades: manual vs manual"
    description = (
        "Recorre 7 combinaciones de activatePriority sobre un mensaje base "
        "con priority 128 y luego sobre un mensaje AUTHORITY (priority 254) "
        "y verifica que dmsActivateMsgError concuerda con la tabla."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    slot_memory_type: ClassVar[int] = oids.MEM_TYPE_CHANGEABLE
    default_base_slot: ClassVar[int] = 251
    default_authority_slot: ClassVar[int] = 252
    base_priority: ClassVar[int] = 128
    authority_priority: ClassVar[int] = 254
    settle_seconds: ClassVar[float] = 1.5

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        base_slot = int(
            ctx.device_config.get("poc_06_base_slot", self.default_base_slot)
        )
        authority_slot = int(
            ctx.device_config.get(
                "poc_06_authority_slot", self.default_authority_slot
            )
        )
        # Fase 1: cargar y activar el mensaje base (priority 128)
        base, err = await _activation.load_message_into_slot(
            ctx,
            memory_type=self.slot_memory_type,
            message_number=base_slot,
            multi="[jp3]POC-06[nl]BASE-128",
            run_time_priority=self.base_priority,
        )
        if base is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo cargar el mensaje base: {err}",
                error=err,
            )
        err_text, err_value = await _activation.activate_message(
            ctx, loaded=base, activate_priority=self.base_priority
        )
        if err_value != 2:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"No se pudo activar el mensaje base: {err_text}",
                error=err_text,
            )
        await asyncio.sleep(self.settle_seconds)

        # Recorrer la matriz Fase 1
        phase1_ok, phase1_fail = await self._run_matrix(
            ctx, loaded=base, cases=PHASE1_CASES, phase_label="phase1"
        )

        # Fase 2: cargar AUTHORITY y activarlo con priority 254
        authority, err = await _activation.load_message_into_slot(
            ctx,
            memory_type=self.slot_memory_type,
            message_number=authority_slot,
            multi="[jp3]POC-06[nl]AUTH-254",
            run_time_priority=self.authority_priority,
        )
        if authority is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Fase 1: {phase1_ok}/{len(PHASE1_CASES)} OK. "
                    f"Fase 2 abortada: {err}"
                ),
                error=err,
            )
        err_text, err_value = await _activation.activate_message(
            ctx, loaded=authority, activate_priority=self.authority_priority
        )
        if err_value != 2:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Fase 1: {phase1_ok}/{len(PHASE1_CASES)} OK. "
                    f"AUTHORITY no se activó: {err_text}"
                ),
                error=err_text,
            )
        await asyncio.sleep(self.settle_seconds)

        phase2_ok, phase2_fail = await self._run_matrix(
            ctx, loaded=authority, cases=PHASE2_CASES, phase_label="phase2"
        )

        total = len(PHASE1_CASES) + len(PHASE2_CASES)
        ok = phase1_ok + phase2_ok
        fail = phase1_fail + phase2_fail
        if ok == total:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=f"{ok}/{total} casos respetan dmsMessageRunTimePriority.",
            )
        if ok >= total * 0.7:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"{ok}/{total} casos OK, {len(fail)} desvíos: "
                    f"{', '.join(fail)}"
                ),
                design_impact=(
                    "Ajustar el mapeo INFORMATIVE…AUTHORITY → 1-255 según el "
                    "comportamiento observado."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_FAIL,
            summary=(
                f"{ok}/{total} casos OK — el panel ignora prioridad. "
                f"Desvíos: {', '.join(fail)}"
            ),
            design_impact=(
                "Sin respeto de dmsMessageRunTimePriority el modelo de "
                "convivencia de mensajes requiere rediseño."
            ),
        )

    async def _run_matrix(
        self,
        ctx: ScenarioContext,
        *,
        loaded: _activation.LoadedMessage,
        cases: List[Tuple[int, int, int, str]],
        phase_label: str,
    ) -> Tuple[int, List[str]]:
        ok = 0
        failures: List[str] = []
        for idx, prio, expected, desc in cases:
            err_text, err_value = await _activation.activate_message(
                ctx, loaded=loaded, activate_priority=prio
            )
            success = err_value == expected
            ctx.record_step(
                f"{phase_label}.case_{idx}",
                operation="VERIFY",
                value_read={
                    "activatePriority": prio,
                    "expected_err": expected,
                    "observed_err": err_value,
                    "observed_text": err_text,
                    "description": desc,
                },
                success=success,
            )
            if success:
                ok += 1
            else:
                failures.append(
                    f"#{idx}({desc} → got {err_text}, expected {expected})"
                )
            await asyncio.sleep(self.settle_seconds)
        return ok, failures
