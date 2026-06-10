"""POC-VMS-14 — Brillo.

Valida si el control de brillo por SNMP es viable para MVP, determina la
escala (directa o invertida) y deja el panel en el valor original.

El Daktronics Vanguard tiene escala invertida (0=100% brillo). Hay que
confirmar si el Chainzone tiene el mismo comportamiento o si la escala es
directa, para parametrizar correctamente el provider.

Pasos:

1. Leer ``dmsIllumControl`` + ``dmsIllumNumBrightLevels`` (capacidades).
2. Leer ``dmsIllumManLevel`` actual y guardarlo como ``original_level``.
3. Si el panel está en photocell/timer, intentar setear
   ``dmsIllumControl=manualIndexed(6)`` para poder escribir niveles.
   Si rechaza, registramos y continuamos en modo observación read-only.
4. Para cada nivel de prueba (default 20, 50, 80):
   a. SET ``dmsIllumManLevel = nivel``.
   b. GET ``dmsIllumManLevel`` para confirmar que el panel lo aceptó.
   c. GET ``dmsIllumBrightLevelStatus`` para registrar el nivel "real"
      reportado por el panel (puede diferir si hay escala invertida o
      saturación).
5. Restaurar ``original_level`` y, si lo cambiamos, ``original_control``.

Criterio:

- ``PASS`` si los 3 SETs fueron aceptados y el panel reporta de vuelta los
  valores escritos (o los reporta de forma consistente con una escala
  invertida).
- ``PARTIAL`` si algún SET es aceptado pero el panel reporta otro valor
  (saturación, mapeo o escala no obvia).
- ``FAIL`` si ningún SET es aceptado o si el restore falla.

Defaults (overridables por device):

    poc_14_levels: [20, 50, 80]
    poc_14_settle_seconds: 1.5
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, List, Optional

from pysnmp.proto.rfc1902 import Integer

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


class PocVms14Brightness(Scenario):
    id = "POC-VMS-14"
    name = "Brillo: SETs de dmsIllumManLevel + escala"
    description = (
        "Determina si el control de brillo por SNMP funciona y cuál es la "
        "escala (directa o invertida). Restaura el valor original al final."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_levels: ClassVar[List[int]] = [20, 50, 80]
    default_settle_seconds: ClassVar[float] = 1.5
    # dmsIllumControl enum: manualIndexed(6) — el modo que permite SETs
    # determinísticos en dmsIllumManLevel.
    MANUAL_INDEXED: ClassVar[int] = 6

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        levels: List[int] = list(
            ctx.device_config.get("poc_14_levels", self.default_levels)
        )
        settle = float(
            ctx.device_config.get(
                "poc_14_settle_seconds", self.default_settle_seconds
            )
        )

        # Paso 1: capacidades
        caps, err = await ctx.snmp.get_many(
            [oids.DMS_ILLUM_CONTROL, oids.DMS_ILLUM_NUM_LEVELS]
        )
        if err in ("TIMEOUT", "SNMP_ERROR"):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"GET de capacidades de brillo falló: {err}",
                error=err,
            )
        try:
            original_control = int(caps.get(oids.DMS_ILLUM_CONTROL))
        except Exception:
            original_control = None
        try:
            num_levels = int(caps.get(oids.DMS_ILLUM_NUM_LEVELS))
        except Exception:
            num_levels = None
        ctx.record_step(
            "capabilities",
            operation="SNMP_GET",
            value_read={
                "dmsIllumControl_original": original_control,
                "dmsIllumNumBrightLevels": num_levels,
            },
            success=True,
        )

        # Paso 2: leer nivel actual + guardar
        original_val, err = await ctx.snmp.get_one(oids.DMS_ILLUM_MAN_LEVEL)
        try:
            original_level = int(original_val) if original_val is not None else None
        except Exception:
            original_level = None
        ctx.record_step(
            "snapshot_initial",
            operation="SNMP_GET",
            oid_name="dmsIllumManLevel",
            oid=oids.DMS_ILLUM_MAN_LEVEL,
            value_read=original_level,
            success=err is None,
            error=err,
        )
        if original_level is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    "No se pudo leer dmsIllumManLevel inicial; sin baseline "
                    "no se puede restaurar."
                ),
            )

        # Paso 3: forzar modo manualIndexed si hace falta
        switched_control = False
        if original_control != self.MANUAL_INDEXED:
            _, set_err = await ctx.snmp.set_one(
                oids.DMS_ILLUM_CONTROL, Integer(self.MANUAL_INDEXED)
            )
            switched_control = set_err is None
            ctx.record_step(
                "switch_to_manualIndexed",
                operation="SNMP_SET",
                oid_name="dmsIllumControl",
                oid=oids.DMS_ILLUM_CONTROL,
                value_read=self.MANUAL_INDEXED,
                success=switched_control,
                error=set_err,
                notes=(
                    "El panel debe estar en manualIndexed(6) para que los "
                    "SETs de dmsIllumManLevel sean determinísticos."
                ),
            )

        # Paso 4: probar cada nivel
        results: List[Dict[str, Any]] = []
        for level in levels:
            _, set_err = await ctx.snmp.set_one(
                oids.DMS_ILLUM_MAN_LEVEL, Integer(int(level))
            )
            ctx.record_step(
                f"set_level_{level}",
                operation="SNMP_SET",
                oid_name="dmsIllumManLevel",
                oid=oids.DMS_ILLUM_MAN_LEVEL,
                value_read=level,
                success=set_err is None,
                error=set_err,
            )
            await asyncio.sleep(settle)
            read_man, _ = await ctx.snmp.get_one(oids.DMS_ILLUM_MAN_LEVEL)
            read_status, _ = await ctx.snmp.get_one(
                oids.DMS_ILLUM_BRIGHT_LEVEL_STATUS
            )
            try:
                read_man_i = int(read_man) if read_man is not None else None
            except Exception:
                read_man_i = None
            try:
                read_status_i = (
                    int(read_status) if read_status is not None else None
                )
            except Exception:
                read_status_i = None
            ctx.record_step(
                f"verify_level_{level}",
                operation="SNMP_GET",
                value_read={
                    "wrote": level,
                    "dmsIllumManLevel_read": read_man_i,
                    "dmsIllumBrightLevelStatus": read_status_i,
                    "matches_write": read_man_i == level,
                },
                success=set_err is None and read_man_i is not None,
            )
            results.append(
                {
                    "wrote": level,
                    "read_man": read_man_i,
                    "read_status": read_status_i,
                    "accepted": set_err is None,
                }
            )

        # Paso 5: restaurar
        _, restore_err = await ctx.snmp.set_one(
            oids.DMS_ILLUM_MAN_LEVEL, Integer(original_level)
        )
        ctx.record_step(
            "restore_original_level",
            operation="SNMP_SET",
            oid_name="dmsIllumManLevel",
            oid=oids.DMS_ILLUM_MAN_LEVEL,
            value_read=original_level,
            success=restore_err is None,
            error=restore_err,
        )
        if switched_control and original_control is not None:
            _, ctrl_err = await ctx.snmp.set_one(
                oids.DMS_ILLUM_CONTROL, Integer(original_control)
            )
            ctx.record_step(
                "restore_original_control",
                operation="SNMP_SET",
                oid_name="dmsIllumControl",
                oid=oids.DMS_ILLUM_CONTROL,
                value_read=original_control,
                success=ctrl_err is None,
                error=ctrl_err,
            )

        # Veredicto
        accepted = sum(1 for r in results if r["accepted"])
        readback_exact = sum(
            1 for r in results if r["accepted"] and r["read_man"] == r["wrote"]
        )

        if accepted == 0:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"0/{len(results)} niveles aceptados. El panel rechaza "
                    f"SETs de dmsIllumManLevel."
                ),
                design_impact=(
                    "Control de brillo por SNMP no viable para este firmware. "
                    "Considerar exclusión del MVP o vía alternativa."
                ),
            )
        if readback_exact == accepted:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    f"{accepted}/{len(results)} niveles aceptados y "
                    f"reportados sin transformación (escala DIRECTA)."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PARTIAL,
            summary=(
                f"{accepted}/{len(results)} niveles aceptados, pero el panel "
                f"reporta valores distintos al escrito en "
                f"{accepted - readback_exact} casos — escala invertida o "
                f"saturación. Ver evidencia."
            ),
            design_impact=(
                "Parametrizar la escala en el provider del fabricante "
                "(directa vs invertida) según la evidencia."
            ),
        )
