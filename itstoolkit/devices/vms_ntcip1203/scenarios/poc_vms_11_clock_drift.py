"""POC-VMS-11 — Reloj del panel y drift.

Mide el drift entre ``globalTime`` (NTCIP 1201, segundos desde epoch UTC
según la norma) y la hora UTC del host. Si el drift es alto o creciente,
los schedules DEVICE-only (POC-VMS-07/08) se disparan en momentos
equivocados sin que ningún error SNMP lo indique — por eso este escenario
es un input al diseño del scheduling.

Pasos:

1. Tomar ``samples`` muestras de ``globalTime`` con intervalo
   ``interval_seconds`` entre cada una.
2. Para cada muestra: calcular ``drift = panel_global_time - host_utc_now``.
3. Registrar drift mínimo, máximo, promedio y la variación entre la primera
   y la última muestra (para detectar drift creciente).

Criterio:

- ``PASS`` si todos los drifts caen dentro de ``max_acceptable_drift_s``
  (default 30 s).
- ``PARTIAL`` si el drift es alto pero estable (variación entre muestras
  < ``stable_variation_s``, default 5 s). Se puede compensar en software.
- ``FAIL`` si el drift es alto y creciente, o si ``globalTime`` no decodifica
  como entero (panel devuelve un tipo inesperado).

Defaults pensados para una corrida rápida (5 muestras × 5 s = 25 s). Para
una validación más rigurosa de drift de largo plazo, configurá vía YAML:

    poc_11_samples: 10
    poc_11_interval_seconds: 60
    poc_11_max_acceptable_drift_s: 30
"""

from __future__ import annotations

import asyncio
import time
from typing import ClassVar, List

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


class PocVms11ClockDrift(Scenario):
    id = "POC-VMS-11"
    name = "Reloj del panel y drift"
    description = (
        "Mide drift entre globalTime del panel y UTC del host. Crítico para "
        "schedules DEVICE-only (POC-VMS-07/08) cuyo timing depende del reloj."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    default_samples: ClassVar[int] = 5
    default_interval_seconds: ClassVar[float] = 5.0
    default_max_acceptable_drift_s: ClassVar[float] = 30.0
    default_stable_variation_s: ClassVar[float] = 5.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        samples = int(
            ctx.device_config.get("poc_11_samples", self.default_samples)
        )
        interval = float(
            ctx.device_config.get(
                "poc_11_interval_seconds", self.default_interval_seconds
            )
        )
        max_drift = float(
            ctx.device_config.get(
                "poc_11_max_acceptable_drift_s",
                self.default_max_acceptable_drift_s,
            )
        )
        stable_var = float(
            ctx.device_config.get(
                "poc_11_stable_variation_s", self.default_stable_variation_s
            )
        )

        drifts: List[float] = []
        for i in range(samples):
            attempt = i + 1
            host_before = time.time()
            val, err = await ctx.snmp.get_one(oids.GLOBAL_TIME)
            host_after = time.time()
            # Promedio de host_before/after compensa la mitad de la latencia RTT.
            host_mid = (host_before + host_after) / 2.0

            if err is not None or val is None:
                ctx.record_step(
                    f"sample_{attempt}",
                    operation="SNMP_GET",
                    oid_name="globalTime",
                    oid=oids.GLOBAL_TIME,
                    success=False,
                    error=err or "NoSuchObject",
                    attempt=attempt,
                )
                if attempt < samples:
                    await asyncio.sleep(interval)
                continue

            try:
                panel_epoch = int(val)
            except Exception:
                ctx.record_step(
                    f"sample_{attempt}",
                    operation="DECODE",
                    oid_name="globalTime",
                    value_read=str(val),
                    success=False,
                    error="not_int",
                    notes=(
                        "El panel devolvió globalTime con un tipo que no "
                        "decodifica como entero — revisar fabricante."
                    ),
                )
                return ScenarioResult(
                    scenario_id=self.id,
                    status=STATUS_FAIL,
                    summary=(
                        f"globalTime no decodifica como entero "
                        f"(tipo={type(val).__name__}, val={val!r})."
                    ),
                    error="globalTime_not_int",
                )

            drift = panel_epoch - host_mid
            drifts.append(drift)
            ctx.record_step(
                f"sample_{attempt}",
                operation="VERIFY",
                value_read={
                    "panel_global_time_epoch": panel_epoch,
                    "host_utc_epoch": host_mid,
                    "drift_seconds": round(drift, 3),
                    "rtt_ms": round((host_after - host_before) * 1000, 2),
                },
                success=True,
                attempt=attempt,
            )

            if attempt < samples:
                await asyncio.sleep(interval)

        if not drifts:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"0/{samples} lecturas de globalTime exitosas. "
                    f"El panel no responde o no soporta el OID."
                ),
            )

        drift_min = min(drifts)
        drift_max = max(drifts)
        drift_avg = sum(drifts) / len(drifts)
        variation = drift_max - drift_min
        max_abs = max(abs(drift_min), abs(drift_max))

        ctx.record_step(
            "summary",
            operation="VERIFY",
            value_read={
                "samples_taken": len(drifts),
                "drift_min_s": round(drift_min, 3),
                "drift_max_s": round(drift_max, 3),
                "drift_avg_s": round(drift_avg, 3),
                "variation_s": round(variation, 3),
                "max_abs_drift_s": round(max_abs, 3),
                "threshold_s": max_drift,
            },
            success=True,
        )

        if max_abs <= max_drift:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    f"Drift ±{max_abs:.1f}s ≤ umbral {max_drift:.0f}s. "
                    f"Avg={drift_avg:.1f}s, var={variation:.1f}s sobre "
                    f"{len(drifts)} muestras."
                ),
            )

        if variation <= stable_var:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Drift alto ({drift_avg:.0f}s) pero ESTABLE "
                    f"(variación {variation:.1f}s). Compensable en software."
                ),
                design_impact=(
                    "Aplicar offset constante al schedule local antes de "
                    "comparar contra eventos del dayPlan."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_FAIL,
            summary=(
                f"Drift alto y CRECIENTE: variación {variation:.0f}s entre "
                f"muestras. Schedules DEVICE no son confiables."
            ),
            design_impact=(
                "Schedules locales del panel no son viables. Mantener "
                "scheduling 100% del lado de Serviam."
            ),
        )
