"""POC-VMS-02 — Mapeo / disponibilidad de OIDs NTCIP conocidos.

Cierra el mapa real de OIDs del panel: no todos los paneles NTCIP 1203
exponen los mismos OIDs aunque sean "compliant" — hay opcionales, hay rutas
distintas según firmware y hay propietarios del fabricante. Este escenario
hace ``GET`` sobre el conjunto simbólico principal (system + NTCIP 1201 +
signControl + statError + MULTI tags + memoria) y registra cuáles están
``supported`` / ``unsupported`` / ``error``.

Sin walk de tablas indexadas — sólo escalares. Las tablas (fontTable,
graphicTable, actionTable, dayPlanTable, timeBaseScheduleTable) se cubren
en un bloque posterior.
"""

from __future__ import annotations

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


class PocVms02OidMap(Scenario):
    id = "POC-VMS-02"
    name = "Mapeo de OIDs NTCIP conocidos"
    description = (
        "GET sobre los OIDs simbólicos principales del adapter para confirmar "
        "cuáles están supported, unsupported o devuelven error. Sin walk de "
        "tablas — sólo escalares."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        named_all = dict(oids.NAMED_PRINCIPAL_OIDS)
        named_critical = dict(oids.NAMED_PRINCIPAL_CRITICAL)

        oid_list = list(named_all.values())
        vals, err = await ctx.snmp.get_many(oid_list)

        if err in ("TIMEOUT", "SNMP_ERROR"):
            ctx.record_step(
                "snmp_get_all",
                operation="SNMP_GET",
                oid_name="NAMED_PRINCIPAL_OIDS",
                success=False,
                error=err,
                notes="GET masivo falló — no se puede mapear nada.",
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"GET masivo falló con {err}. Mapeo no posible.",
                error=err,
                design_impact=(
                    "Sin GET funcionando, POC-VMS-03/04 tampoco corren. "
                    "Revisar conectividad (POC-VMS-01) primero."
                ),
            )

        supported: list[str] = []
        unsupported: list[str] = []

        for symbolic, oid in named_all.items():
            present = vals.get(oid) is not None
            ctx.record_step(
                f"check_{symbolic}",
                operation="SNMP_GET",
                oid_name=symbolic,
                oid=oid,
                value_read=vals.get(oid),
                success=present,
                error=None if present else "NoSuchObject",
                is_critical=symbolic in named_critical,
            )
            (supported if present else unsupported).append(symbolic)

        critical_missing = [s for s in named_critical if s in unsupported]

        if critical_missing:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Faltan OIDs críticos: {', '.join(critical_missing)}. "
                    f"Soportados: {len(supported)}/{len(named_all)}."
                ),
                design_impact=(
                    "Los OIDs críticos sostienen el monitor y los escenarios "
                    "posteriores. Si faltan, hay que documentarlos como "
                    "QUIRK del fabricante y resolver alternativos."
                ),
            )
        if unsupported:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"OIDs críticos presentes; opcionales no soportados: "
                    f"{', '.join(unsupported)}. "
                    f"Soportados: {len(supported)}/{len(named_all)}."
                ),
                design_impact=(
                    "Los opcionales no soportados se registran como ausencia "
                    "en el capability profile. No bloquea POC-VMS-03/04."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=f"Todos los OIDs principales soportados ({len(supported)}/{len(named_all)}).",
        )