"""POC-VMS-03 — Capacidades escalares del panel.

Lee el conjunto completo de OIDs **escalares** que pueblan el capability
profile del panel (dimensiones, color, memoria, fuentes escalares, gráficos
escalares, brillo, scheduler, MULTI tags). No incluye walks de tablas
indexadas (fontTable, graphicTable, actionTable, dayPlanTable,
timeBaseScheduleTable) — esos van en un bloque posterior.

Criterio:

- ``PASS`` si todos los críticos respondieron con valor + ningún opcional
  devolvió error explícito (los ``NoSuchObject`` opcionales no fallan).
- ``PARTIAL`` si los críticos pasan pero hay opcionales no soportados.
- ``FAIL`` si falta cualquier crítico o si el GET global tira TIMEOUT/SNMP_ERROR.
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


class PocVms03Capabilities(Scenario):
    id = "POC-VMS-03"
    name = "Capacidades escalares del panel"
    description = (
        "Lee dimensiones, color, memoria, brillo, escalares de fuentes/gráficos "
        "y capacidades del scheduler (NTCIP 1201) para poblar el capability "
        "profile. Sin walks de tablas indexadas."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        critical = dict(oids.CAPABILITY_CRITICAL)
        optional = dict(oids.CAPABILITY_OPTIONAL)
        all_oids = list(critical.values()) + list(optional.values())

        vals, err = await ctx.snmp.get_many(all_oids)
        if err in ("TIMEOUT", "SNMP_ERROR"):
            ctx.record_step(
                "snmp_get_all",
                operation="SNMP_GET",
                oid_name="CAPABILITY_SCALAR_OIDS",
                success=False,
                error=err,
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"GET masivo de capacidades falló con {err}.",
                error=err,
            )

        crit_missing: list[str] = []
        opt_missing: list[str] = []

        for symbolic, oid in critical.items():
            present = vals.get(oid) is not None
            ctx.record_step(
                f"capability_{symbolic}",
                operation="SNMP_GET",
                oid_name=symbolic,
                oid=oid,
                value_read=vals.get(oid),
                success=present,
                error=None if present else "NoSuchObject",
                bucket="critical",
            )
            if not present:
                crit_missing.append(symbolic)

        for symbolic, oid in optional.items():
            present = vals.get(oid) is not None
            ctx.record_step(
                f"capability_{symbolic}",
                operation="SNMP_GET",
                oid_name=symbolic,
                oid=oid,
                value_read=vals.get(oid),
                success=present,
                error=None if present else "NoSuchObject",
                bucket="optional",
            )
            if not present:
                opt_missing.append(symbolic)

        if crit_missing:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Faltan capacidades críticas: {', '.join(crit_missing)}."
                ),
                design_impact=(
                    "Sin dimensiones ni capacidad básica de memoria no se "
                    "puede construir un capability profile válido. "
                    "Documentar como QUIRK del fabricante."
                ),
            )

        total_critical = len(critical)
        total_optional = len(optional)
        present_optional = total_optional - len(opt_missing)

        if opt_missing:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Críticas {total_critical}/{total_critical} OK. "
                    f"Opcionales {present_optional}/{total_optional} soportadas. "
                    f"No soportadas: {', '.join(opt_missing)}."
                ),
                design_impact=(
                    "Las capacidades opcionales no soportadas se marcan como "
                    "ausentes en el capability profile (campo null)."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Todas las capacidades escalares respondieron "
                f"({total_critical + total_optional} OIDs)."
            ),
        )
