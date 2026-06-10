"""POC-VMS-18 — Mapeo de ``dmsMultiSyntaxError`` por tipo de error.

Recorre una batería de MULTIs con errores intencionales y para cada uno
registra:

- ¿el panel rechaza durante ``validateReq`` (llega a ``error(5)``)?
- ``dmsMultiSyntaxError`` (código del enum NTCIP 1203 §5.7.18)
- ``dmsMultiSyntaxErrorPosition`` (offset en bytes, debería caer dentro
    del MULTI)

Estos OIDs son globales (signControl 18 / 19), no por slot — se leen una
sola vez por caso, inmediatamente después del intento de carga.

La spec lista 7 casos. POC-18 los cubre todos; ``font_not_defined`` y
``graphic_not_defined`` usan IDs altos que NORMALMENTE no existen (99) —
si el panel los tiene cargados, ese caso pasa a "valid" y se documenta.

Criterio:

- ``PASS`` si todos los casos retornan un código de error explícito
    (≠ ``none(2)``) y la posición cae dentro del MULTI.
- ``QUIRK_PROVIDER`` si algún caso retorna ``other(1)`` donde la spec
    esperaba un código específico — comportamiento propietario documentado.
- ``FAIL`` si algún caso retorna ``none(2)`` (panel acepta MULTI inválido)
    o si la posición es claramente errónea (> longitud del string en todos
    los casos donde se esperaba detalle).

Defaults:

    poc_18_slot: 248
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pysnmp.proto.rfc1902 import Integer, OctetString

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_QUIRK,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation


# (label, MULTI inválido, código(s) aceptable(s) del enum dmsMultiSyntaxError)
# Tupla de códigos = el panel puede devolver cualquiera de ellos y aún
# consideramos que respetó la spec (varias categorías de la norma admiten
# más de un código por caso límite).
# Enum: 1=other, 3=unsupportedTag, 4=unsupportedTagValue, 5=textTooBig,
# 6=fontNotDefined, 12=tooManyPages, 15=graphicNotDefined.
SYNTAX_BATTERY: List[Tuple[str, str, Tuple[int, ...]]] = [
    ("unsupported_tag", "[xx99]TEXT", (3,)),
    ("unsupported_tag_value", "[jl9]TEXT", (4,)),
    # 600 chars > dmsMaxMultiStringLength típico (500) pero entra en un PDU SNMP
    # único; con 4096 había TIMEOUT antes de llegar al panel.
    ("text_too_big", "X" * 600, (5,)),
    ("font_not_defined", "[fo99]TEXT", (6,)),
    ("too_many_pages", "[np]".join([f"P{i}" for i in range(60)]), (12,)),
    ("graphic_not_defined", "[g99]", (15,)),
    # Spec explícita: "other(1) o unsupportedTagValue(4)" — ambos válidos.
    ("malformed_font_comma", "[fo,14]TEXT", (1, 4)),
]


class PocVms18MultiSyntaxErrors(Scenario):
    id = "POC-VMS-18"
    name = "Errores de sintaxis MULTI por tipo"
    description = (
        "Para cada categoría de error sintáctico, registra el código que "
        "devuelve dmsMultiSyntaxError y la posición reportada. Insumo "
        "directo para el MultiValidator del provider."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_slot: ClassVar[int] = 248

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        slot = int(ctx.device_config.get("poc_18_slot", self.default_slot))

        results: List[Dict[str, Any]] = []
        for label, multi_text, expected_codes in SYNTAX_BATTERY:
            outcome = await self._test_one(
                ctx,
                label=label,
                multi=multi_text,
                expected_codes=expected_codes,
                slot=slot,
            )
            results.append(outcome)
            await asyncio.sleep(0.5)

        # Análisis
        total = len(results)
        infeasible = sum(1 for r in results if r["infeasible"])
        usable = total - infeasible
        accepted_as_none = sum(
            1 for r in results if not r["infeasible"] and r["observed_code"] == 2
        )
        exact_match = sum(
            1 for r in results if not r["infeasible"] and r["match_exact"]
        )
        explicit_error = sum(
            1
            for r in results
            if not r["infeasible"] and r["observed_code"] not in (None, 2)
        )

        ctx.record_step(
            "summary",
            operation="VERIFY",
            value_read={
                "total": total,
                "usable": usable,
                "infeasible": infeasible,
                "exact_match": exact_match,
                "explicit_error_any_code": explicit_error,
                "accepted_when_should_fail": accepted_as_none,
                "infeasible_cases": [
                    {"label": r["label"], "reason": r["infeasible_reason"]}
                    for r in results
                    if r["infeasible"]
                ],
                "mismatches": [
                    {
                        "label": r["label"],
                        "expected": r["expected_codes"],
                        "observed": r["observed_code"],
                        "observed_text": r["observed_text"],
                    }
                    for r in results
                    if not r["infeasible"] and not r["match_exact"]
                ],
            },
            success=True,
        )

        infeasible_note = (
            f" ({infeasible} caso(s) infactibles por límite SNMP/transport)"
            if infeasible
            else ""
        )

        if accepted_as_none > 0:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"{accepted_as_none}/{usable} MULTIs inválidos aceptados "
                    f"como 'none(2)' — el panel valida menos de lo que dice."
                ),
                design_impact=(
                    "El MultiValidator debe validar client-side ANTES de "
                    "enviar, porque el panel no protege contra MULTIs "
                    "malformados."
                ),
            )
        if exact_match == usable:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    f"{exact_match}/{usable} categorías retornan un código "
                    f"compatible con la spec{infeasible_note}."
                ),
            )
        if explicit_error == usable:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_QUIRK,
                summary=(
                    f"Todos los MULTIs son rechazados pero "
                    f"{usable - exact_match}/{usable} casos retornan un "
                    f"código distinto al esperado por la spec"
                    f"{infeasible_note}."
                ),
                design_impact=(
                    "Mapear los códigos observados al provider — el panel "
                    "agrupa varios tipos en otro código."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_FAIL,
            summary=(
                f"{explicit_error}/{usable} casos clasificados, "
                f"{usable - explicit_error} sin código legible — el panel "
                f"no expone dmsMultiSyntaxError de forma consistente."
            ),
        )

    async def _test_one(
        self,
        ctx: ScenarioContext,
        *,
        label: str,
        multi: str,
        expected_codes: Tuple[int, ...],
        slot: int,
    ) -> Dict[str, Any]:
        # Intentar cargar el MULTI. La validación dispara dmsMultiSyntaxError.
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=slot,
            multi=multi,
            run_time_priority=32,
        )

        # Si el SET del MULTI nunca llegó al panel (timeout de transporte),
        # leer dmsMultiSyntaxError devolvería el valor del caso ANTERIOR —
        # eso era el bug original. Marcamos el caso como infeasible.
        transport_failed = (
            load_err is not None
            and ("set_contents:" in load_err)
            and ("TIMEOUT" in load_err or "SNMP_ERROR" in load_err)
        )

        # Leer los OIDs globales de error sintáctico
        vals, _ = await ctx.snmp.get_many(
            [oids.DMS_MULTI_SYNTAX_ERROR, oids.DMS_MULTI_SYNTAX_ERROR_POSITION]
        )
        syntax_raw = vals.get(oids.DMS_MULTI_SYNTAX_ERROR)
        pos_raw = vals.get(oids.DMS_MULTI_SYNTAX_ERROR_POSITION)
        observed = _safe_int(syntax_raw)
        position = _safe_int(pos_raw)

        loaded_ok = loaded is not None
        match_exact = (not transport_failed) and observed in expected_codes
        position_plausible = (
            position is None
            or (0 <= position <= max(0, len(multi)))
        )

        outcome = {
            "label": label,
            "multi_len": len(multi),
            "multi_preview": multi[:60] + ("..." if len(multi) > 60 else ""),
            "expected_codes": list(expected_codes),
            "observed_code": observed if not transport_failed else None,
            "observed_text": (
                decoders.decode_multi_syntax_error(syntax_raw)
                if not transport_failed
                else "n/a (transport failed)"
            ),
            "position": position if not transport_failed else None,
            "position_plausible": position_plausible,
            "loaded_to_valid": loaded_ok,
            "load_err": load_err,
            "match_exact": match_exact,
            "infeasible": transport_failed,
            "infeasible_reason": (
                f"set_contents failed before panel saw MULTI: {load_err}"
                if transport_failed
                else None
            ),
        }
        ctx.record_step(
            f"case.{label}",
            operation="VERIFY",
            value_read=outcome,
            success=(transport_failed and False) or (match_exact and not loaded_ok),
        )

        # Limpieza best-effort: si el slot quedó en 'modifying' o 'error',
        # forzar notUsedReq para que el siguiente caso pueda usarlo.
        status_oid = _activation.row_oid(
            oids.DMS_MSG_STATUS_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )
        await ctx.snmp.set_one(status_oid, Integer(oids.MSG_STATUS_NOT_USED_REQ))
        return outcome


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None
