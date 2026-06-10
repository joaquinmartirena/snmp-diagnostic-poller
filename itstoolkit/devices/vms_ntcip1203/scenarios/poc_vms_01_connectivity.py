"""POC-VMS-01 — Conectividad SNMP base.

Confirma que el panel responde a SNMP v2c con la versión y credenciales
configuradas. Es el primer paso obligatorio antes de cualquier otro
escenario: si éste falla, ninguno de los siguientes puede ejecutarse contra
el panel.

Pasos:

1. Leer ``sysDescr`` + ``sysUpTime`` 5 veces con intervalo de 5 segundos.
2. Registrar la latencia y los errores SNMP por intento.
3. ``PASS`` si las 5/5 lecturas responden sin timeout; ``PARTIAL`` si alguna
    responde y otras no; ``FAIL`` si ninguna.
"""

from __future__ import annotations

import asyncio
import time
from typing import ClassVar

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


class PocVms01Connectivity(Scenario):
    id = "POC-VMS-01"
    name = "Conectividad SNMP base"
    description = (
        "Lee sysDescr y sysUpTime varias veces para confirmar que el panel "
        "responde a SNMP v2c con la community configurada."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    #: Cantidad de lecturas consecutivas para considerar PASS.
    samples: ClassVar[int] = 5
    #: Intervalo entre lecturas (segundos).
    interval_seconds: ClassVar[float] = 5.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        oid_list = [oids.SYS_DESCR, oids.SYS_UPTIME]
        ok = 0
        last_err: str | None = None

        for i in range(self.samples):
            attempt = i + 1
            t0 = time.monotonic()
            vals, err = await ctx.snmp.get_many(oid_list)
            elapsed_ms = (time.monotonic() - t0) * 1000.0

            success = err is None and vals.get(oids.SYS_DESCR) is not None
            ctx.record_step(
                f"snmp_get_attempt_{attempt}",
                operation="SNMP_GET",
                oid_name="sysDescr+sysUpTime",
                oid=f"{oids.SYS_DESCR},{oids.SYS_UPTIME}",
                value_read=(
                    {
                        "sysDescr": vals.get(oids.SYS_DESCR),
                        "sysUpTime": vals.get(oids.SYS_UPTIME),
                    }
                    if success
                    else None
                ),
                success=success,
                error=err,
                latency_ms=round(elapsed_ms, 2),
                attempt=attempt,
            )
            if success:
                ok += 1
            else:
                last_err = err or "missing_value"

            if attempt < self.samples:
                await asyncio.sleep(self.interval_seconds)

        if ok == self.samples:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=f"{ok}/{self.samples} lecturas SNMP exitosas.",
            )
        if ok == 0:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"0/{self.samples} lecturas exitosas — el panel no responde. "
                    f"Último error: {last_err}."
                ),
                error=last_err,
                design_impact=(
                    "Sin conectividad SNMP confiable el resto de los escenarios "
                    "no puede ejecutarse. Revisar IP, community y conectividad."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PARTIAL,
            summary=(
                f"{ok}/{self.samples} lecturas exitosas — conectividad intermitente. "
                f"Último error: {last_err}."
            ),
            error=last_err,
            design_impact=(
                "Conectividad inestable: el polling tolera fallos esporádicos, "
                "pero hay que documentar la tasa de pérdida en campo."
            ),
        )
