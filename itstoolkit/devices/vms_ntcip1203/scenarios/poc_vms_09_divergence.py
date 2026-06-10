"""POC-VMS-09 — Expected vs reported sin plataforma.

Valida el núcleo del modelo de divergencia: comparar un MULTI "esperado"
(definido por la plataforma) contra el "reportado" (leído del panel) y
clasificar como ``IN_SYNC`` / ``DIVERGENT`` / ``UNKNOWN``. Si este
algoritmo no funciona con datos reales, el ``MessageMonitor`` no puede
implementarse.

El expected sale de la config del device (``expected_multi``) o de un
default razonable (string vacío). El reported se lee siguiendo la misma
ruta del adapter: ``dmsMsgTableSource`` → slot → ``dmsMessageMultiString``.

Pasos:

1. Determinar expected (config ``expected_multi``, default ``""``).
2. Leer reported actual del panel.
3. Calcular ``expected_hash`` y ``reported_hash``.
4. Clasificar (``IN_SYNC`` / ``DIVERGENT`` / ``UNKNOWN``).
5. Esperar ``recheck_seconds`` y repetir — un segundo punto baja el riesgo
    de falso positivo por race con un cambio en vuelo.

Criterio:

- ``PASS`` si las dos lecturas clasifican consistentemente y la
    clasificación es ``IN_SYNC`` o ``DIVERGENT`` (lectura confiable).
- ``PARTIAL`` si la clasificación cambia entre lecturas (panel inestable).
- ``FAIL`` si no se puede leer el MULTI activo (clasificación ``UNKNOWN``).

Read-only: no requiere ``confirm_write``.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar, Tuple

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
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


def _classify(expected_hash: str, reported_hash: str | None) -> str:
    if reported_hash is None:
        return "UNKNOWN"
    return "IN_SYNC" if reported_hash == expected_hash else "DIVERGENT"


class PocVms09Divergence(Scenario):
    id = "POC-VMS-09"
    name = "Divergencia expected vs reported"
    description = (
        "Compara el MULTI esperado por la plataforma vs el reportado por el "
        "panel y clasifica el estado (IN_SYNC / DIVERGENT / UNKNOWN)."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    recheck_seconds: ClassVar[float] = 3.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        expected = str(ctx.device_config.get("expected_multi", ""))
        expected_hash = hash_multi(expected)
        ctx.record_step(
            "expected_defined",
            operation="LOCAL",
            value_read={"expected": expected, "expected_sha256": expected_hash},
            success=True,
        )

        first = await self._read_and_classify(
            ctx, expected_hash=expected_hash, label="first"
        )
        await asyncio.sleep(self.recheck_seconds)
        second = await self._read_and_classify(
            ctx, expected_hash=expected_hash, label="second"
        )

        cls1, multi1, _ = first
        cls2, multi2, _ = second

        if cls1 == "UNKNOWN" and cls2 == "UNKNOWN":
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    "MULTI activo no se pudo leer en ninguna de las dos "
                    "lecturas — el monitor no tiene fuente confiable."
                ),
                design_impact=(
                    "MessageMonitor debe tolerar UNKNOWN como estado "
                    "explícito en lugar de asumir DIVERGENT/IN_SYNC."
                ),
            )

        if cls1 != cls2:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Clasificación inestable entre lecturas: "
                    f"{cls1} → {cls2}. Posible cambio en vuelo."
                ),
                design_impact=(
                    "El intervalo de monitoreo debe ser menor que la frecuencia "
                    "típica de cambios externos para evitar oscilación."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Clasificación consistente: {cls1} "
                f"(expected={expected!r}, reported={multi1!r})."
            ),
        )

    async def _read_and_classify(
        self, ctx: ScenarioContext, *, expected_hash: str, label: str
    ) -> Tuple[str, str | None, str | None]:
        # Leer control plane + mensaje activo
        vals, err = await ctx.snmp.get_many(
            [oids.CTRL_MODE, oids.SRC_MODE, oids.MSG_SRC]
        )
        if err in ("TIMEOUT", "SNMP_ERROR"):
            ctx.record_step(
                f"{label}.read_control",
                operation="SNMP_GET",
                success=False,
                error=err,
            )
            return "UNKNOWN", None, None

        mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))
        if not mid["valid"]:
            ctx.record_step(
                f"{label}.invalid_msg_id",
                operation="DECODE",
                value_read=mid,
                success=False,
                error="message_id_undecodable",
            )
            return "UNKNOWN", None, None

        multi_oid_str = oids.multi_oid(mid["memory_type"], mid["message_number"])
        raw, multi_err = await ctx.snmp.get_one(multi_oid_str)
        if multi_err is not None or raw is None:
            ctx.record_step(
                f"{label}.read_multi",
                operation="SNMP_GET",
                oid=multi_oid_str,
                success=False,
                error=multi_err or "NoSuchObject",
            )
            return "UNKNOWN", None, None

        text = snmp_values.decode_octet_text(raw) or ""
        reported_hash = hash_multi(text)
        classification = _classify(expected_hash, reported_hash)
        ctx.record_step(
            f"{label}.classify",
            operation="VERIFY",
            value_read={
                "reported": text,
                "reported_sha256": reported_hash,
                "classification": classification,
            },
            success=True,
        )
        return classification, text, reported_hash
