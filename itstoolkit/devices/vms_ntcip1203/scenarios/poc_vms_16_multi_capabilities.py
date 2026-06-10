"""POC-VMS-16 — Capacidades MULTI del panel.

Cruza el bitmap declarado en ``dmsSupportedMultiTags`` con la respuesta
real del panel a una batería de MULTIs que ejercitan cada tag. Resultado:
matriz de capacidades real (no declarada) lista para el
``VmsPanelCapabilityProfile``.

Pasos:

1. Leer ``dmsSupportedMultiTags`` (4 bytes bitmap) + ``dmsColorScheme`` +
   dimensiones.
2. Para cada caso de la batería:
   a. Cargar el MULTI en un slot changeable (ritual completo).
   b. Si la carga llega a ``valid``, activar y leer
      ``dmsActivateMsgError``.
   c. Registrar: tag, bit declarado, ¿carga OK?, ¿activación OK?,
      ``dmsMultiSyntaxError`` si syntaxMULTI(8).
3. Reporte: tags declarados que efectivamente funcionan vs los que
   declaran soporte pero rechazan.

Criterio:

- ``PASS`` si la matriz observada es **subset o igual** del bitmap
  declarado (panel no sobre-declara — todo lo que dice soportar funciona).
- ``PARTIAL`` si el panel **soporta más** de lo declarado (bitmap
  conservador — el provider puede ampliar).
- ``FAIL`` si el panel **sobre-declara** (acepta el bit pero rechaza al
  usar) — el bitmap del firmware miente y hay que documentar QUIRK por
  tag.

Defaults:

    poc_16_slot: 240
    poc_16_settle_seconds: 1.0
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    STATUS_QUIRK,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation

# Batería: (label, MULTI, bit_index del dmsSupportedMultiTags que ejerce)
# bit_index None = tag obligatorio (no aparece en el bitmap).
MULTI_BATTERY: List[Tuple[str, str, int | None]] = [
    ("plain_text", "HELLO", None),
    ("new_line", "L1[nl]L2", 10),
    ("new_page", "P1[np]P2", 11),
    ("justification_line", "[jl3]CENTERED", 6),
    ("justification_page", "[jp3]MID", 7),
    ("page_time_default", "[pt30o0]X", 12),
    ("color_foreground_classic", "[cf1]RED", 1),
    ("flashing", "[flt5o5]F[/fl]", 2),
    ("spacing_character", "[sc2]TEXT", 13),
    ("font_explicit", "[fo1]A", 3),
    # Tags poco usuales / probablemente no soportados (probamos para confirmar)
    ("moving_text", "[mvtdw,5,3,SCROLL]", 9),
    ("graphic_ref_missing", "[g99]", 4),
    ("hex_character", "[hc65]", 5),
    # Inválido a propósito — esperamos rechazo explícito (no silencioso)
    ("unsupported_invented_tag", "[xx99]BAD", None),
]


class PocVms16MultiCapabilities(Scenario):
    id = "POC-VMS-16"
    name = "Capacidades MULTI: declarado vs real"
    description = (
        "Cruza el bitmap dmsSupportedMultiTags con una batería real de "
        "MULTIs; detecta over-declaration (firmware miente) y under-"
        "declaration (firmware conservador)."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_slot: ClassVar[int] = 240
    default_settle_seconds: ClassVar[float] = 1.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        slot = int(ctx.device_config.get("poc_16_slot", self.default_slot))
        settle = float(
            ctx.device_config.get(
                "poc_16_settle_seconds", self.default_settle_seconds
            )
        )

        # Paso 1: leer capacidades declaradas
        vals, err = await ctx.snmp.get_many(
            [
                oids.DMS_SUPPORTED_MULTI_TAGS,
                oids.DMS_COLOR_SCHEME,
                oids.VMS_SIGN_HEIGHT_PIXELS,
                oids.VMS_SIGN_WIDTH_PIXELS,
            ]
        )
        if err in ("TIMEOUT", "SNMP_ERROR"):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"GET de capacidades MULTI falló: {err}",
                error=err,
            )

        bitmap_bytes = _coerce_octets(
            vals.get(oids.DMS_SUPPORTED_MULTI_TAGS)
        )
        declared_bits = _bitmap_to_set(bitmap_bytes)
        ctx.record_step(
            "capabilities_declared",
            operation="SNMP_GET",
            value_read={
                "dmsSupportedMultiTags_hex": (
                    bitmap_bytes.hex().upper() if bitmap_bytes else None
                ),
                "declared_bits": sorted(declared_bits),
                "dmsColorScheme": _safe_int(vals.get(oids.DMS_COLOR_SCHEME)),
                "sign_height_pixels": _safe_int(
                    vals.get(oids.VMS_SIGN_HEIGHT_PIXELS)
                ),
                "sign_width_pixels": _safe_int(
                    vals.get(oids.VMS_SIGN_WIDTH_PIXELS)
                ),
            },
            success=True,
        )

        # Paso 2: correr la batería
        observed_works: List[Dict[str, Any]] = []
        observed_fails: List[Dict[str, Any]] = []
        for label, multi_text, bit_index in MULTI_BATTERY:
            outcome = await self._test_one(
                ctx,
                label=label,
                multi=multi_text,
                bit_index=bit_index,
                slot=slot,
                declared_bits=declared_bits,
            )
            (observed_works if outcome["works"] else observed_fails).append(
                outcome
            )
            await asyncio.sleep(settle)

        # Paso 3: analizar consistencia
        # Over-declared = panel dice soportar el tag (bit en bitmap) PERO lo
        # rechaza con código 'unsupportedTag(3)'. Otros errores
        # (graphicNotDefined(15), fontNotDefined(6), unsupportedTagValue(4))
        # significan que el tag funciona pero el argumento no — eso NO es
        # over-declaration sino datos faltantes en el panel.
        UNSUPPORTED_TAG_CODE = 3
        over_declared = [
            o for o in observed_fails
            if (
                o["bit_index"] is not None
                and o["bit_index"] in declared_bits
                and _syntax_code(o.get("syntax_err")) == UNSUPPORTED_TAG_CODE
            )
        ]
        # Casos rechazados con códigos != unsupportedTag son "data-related"
        # (gráfico/fuente faltante, valor fuera de rango) y se reportan aparte
        # como datos útiles, no como bug del bitmap.
        data_related_failures = [
            o for o in observed_fails
            if (
                o["bit_index"] is not None
                and o["bit_index"] in declared_bits
                and _syntax_code(o.get("syntax_err")) != UNSUPPORTED_TAG_CODE
            )
        ]
        under_declared = [
            o for o in observed_works
            if o["bit_index"] is not None and o["bit_index"] not in declared_bits
        ]

        ctx.record_step(
            "summary",
            operation="VERIFY",
            value_read={
                "total_cases": len(MULTI_BATTERY),
                "works": len(observed_works),
                "fails": len(observed_fails),
                "over_declared": [o["label"] for o in over_declared],
                "under_declared": [o["label"] for o in under_declared],
                "data_related_failures": [
                    f"{o['label']} → {o.get('syntax_err')}"
                    for o in data_related_failures
                ],
            },
            success=True,
        )

        # Umbral: ≤2 over_declared = QUIRK por tag (provider los enmascara);
        # >2 = bitmap no confiable como fuente de verdad (FAIL).
        if over_declared:
            over_labels = ", ".join(o["label"] for o in over_declared)
            if len(over_declared) <= 2:
                return ScenarioResult(
                    scenario_id=self.id,
                    status=STATUS_QUIRK,
                    summary=(
                        f"Bitmap declara soporte para {len(over_declared)} tag(s) "
                        f"que NO funcionan: {over_labels}. El resto del bitmap "
                        f"({len(observed_works)}/{len(MULTI_BATTERY)} OK) "
                        f"es confiable."
                    ),
                    design_impact=(
                        f"En el provider del fabricante, enmascarar "
                        f"manualmente los tags {over_labels} del "
                        f"VmsPanelCapabilityProfile."
                    ),
                )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Panel sobre-declara {len(over_declared)} tag(s): "
                    f"{over_labels}. El bitmap NO es confiable como fuente."
                ),
                design_impact=(
                    "VmsPanelCapabilityProfile debe construirse desde la "
                    "matriz observada, ignorando dmsSupportedMultiTags."
                ),
            )
        if under_declared:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Panel soporta {len(under_declared)} tag(s) que NO "
                    f"declara: {', '.join(o['label'] for o in under_declared)}. "
                    f"Bitmap es conservador."
                ),
                design_impact=(
                    "Provider puede ampliar el profile más allá del bitmap; "
                    "documentar los tags adicionales soportados."
                ),
            )
        # Bitmap consistente con lo que se puede probar; los
        # data_related_failures son info útil pero no fallan el POC.
        works_count = len(observed_works)
        data_fail_note = (
            f" ({len(data_related_failures)} fallaron por datos faltantes "
            f"en el panel: {', '.join(o['label'] for o in data_related_failures)})"
            if data_related_failures
            else ""
        )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Matriz MULTI consistente con el bitmap declarado "
                f"({works_count}/{len(MULTI_BATTERY)} OK){data_fail_note}."
            ),
        )

    async def _test_one(
        self,
        ctx: ScenarioContext,
        *,
        label: str,
        multi: str,
        bit_index: int | None,
        slot: int,
        declared_bits: set,
    ) -> Dict[str, Any]:
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=slot,
            multi=multi,
            run_time_priority=32,
        )
        result: Dict[str, Any] = {
            "label": label,
            "multi": multi,
            "bit_index": bit_index,
            "bit_declared": (
                bit_index in declared_bits if bit_index is not None else None
            ),
            "load_ok": loaded is not None,
            "load_err": load_err,
            "activate_err": None,
            "activate_err_value": None,
            "syntax_err": None,
            "works": False,
        }
        if loaded is None:
            # Carga falló: leer el error sintáctico aunque sea (puede haber
            # llegado al ``error(5)`` state del slot).
            syntax_raw, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR
            )
            result["syntax_err"] = decoders.decode_multi_syntax_error(syntax_raw)
            ctx.record_step(
                f"case.{label}",
                operation="VERIFY",
                value_read=result,
                success=False,
            )
            return result

        err_text, err_value = await _activation.activate_message(
            ctx, loaded=loaded
        )
        result["activate_err"] = err_text
        result["activate_err_value"] = err_value
        result["works"] = err_value == 2  # none(2) = aceptado
        if err_value == 8:  # syntaxMULTI(8)
            syntax_raw, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR
            )
            result["syntax_err"] = decoders.decode_multi_syntax_error(syntax_raw)
        ctx.record_step(
            f"case.{label}",
            operation="VERIFY",
            value_read=result,
            success=result["works"],
        )
        return result


def _coerce_octets(raw: Any) -> bytes:
    if raw is None:
        return b""
    if hasattr(raw, "asOctets"):
        return bytes(raw.asOctets())
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    try:
        iv = int(raw)
        return iv.to_bytes(max(1, (iv.bit_length() + 7) // 8), "big")
    except Exception:
        return b""


def _bitmap_to_set(b: bytes) -> set:
    """Convierte el OCTET STRING a un set de índices de bit set en 1.

    NTCIP usa "bit 0 = MSB del primer byte". El bitmap es de 4 bytes según
    ``dmsSupportedMultiTags``.
    """
    out: set = set()
    for byte_i, byte in enumerate(b):
        for bit_in_byte in range(8):
            if byte & (0x80 >> bit_in_byte):
                out.add(byte_i * 8 + bit_in_byte)
    return out


def _syntax_code(text: Any) -> Optional[int]:
    """Extrae el código numérico de un texto tipo 'unsupportedTag(3)'."""
    if not isinstance(text, str):
        return None
    if "(" in text and text.endswith(")"):
        try:
            return int(text[text.rindex("(") + 1 : -1])
        except Exception:
            return None
    return None


def _safe_int(v: Any) -> Any:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return str(v)
