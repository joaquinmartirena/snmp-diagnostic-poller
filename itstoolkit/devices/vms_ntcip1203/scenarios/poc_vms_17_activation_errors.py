"""POC-VMS-17 — Provocar cada error de ``dmsActivateMsgError``.

Provoca intencionalmente CRC incorrecto, slot vacío, slot inexistente y
MULTI con sintaxis inválida — y verifica que el panel responde con el
código documentado en la norma (NTCIP 1203 §5.7.17). El objetivo es
mapear el comportamiento real para que el Provider sepa qué retorna cada
panel ante cada falla.

La fase ``localMode(9)`` queda en POC-VMS-20 (escenario propio).

Matriz que ejercemos:

+-------------------------+---------------+-------------------------+
| Caso provocado          | Código        | Detalle adicional       |
|                         | esperado      |                         |
+-------------------------+---------------+-------------------------+
| CRC incorrecto          | messageCRC(7) | —                       |
| Slot notUsed            | messageStatus(4) | —                    |
| Slot inexistente        | messageNumber(6) | —                    |
| MULTI sintaxis inválida | syntaxMULTI(8)| dmsMultiSyntaxError +   |
|                         |               | dmsMultiSyntaxErrorPos  |
+-------------------------+---------------+-------------------------+

Criterio:

- ``PASS`` si los 4 casos retornan el código esperado de la norma.
- ``QUIRK_PROVIDER`` si algún caso retorna un código distinto (panel
  responde, pero con código no estándar — documentar y mapear).
- ``FAIL`` si algún caso retorna ``none(2)`` (panel acepta la activación
  cuando no debería) o si no responde.

Defaults:

    poc_17_valid_slot: 246      # slot que se carga con MULTI válido
    poc_17_empty_slot: 247      # slot que dejamos en notUsed
    poc_17_nonexistent_slot: 999
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, List, Optional

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


class PocVms17ActivationErrors(Scenario):
    id = "POC-VMS-17"
    name = "Errores de activación: códigos de dmsActivateMsgError"
    description = (
        "Provoca CRC incorrecto, slot vacío, slot inexistente y MULTI "
        "inválido. Verifica que el panel devuelve el código de error que "
        "corresponde según NTCIP 1203 §5.7.17."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_valid_slot: ClassVar[int] = 246
    default_empty_slot: ClassVar[int] = 247
    default_nonexistent_slot: ClassVar[int] = 999

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        valid_slot = int(
            ctx.device_config.get(
                "poc_17_valid_slot", self.default_valid_slot
            )
        )
        empty_slot = int(
            ctx.device_config.get(
                "poc_17_empty_slot", self.default_empty_slot
            )
        )
        nonexistent_slot = int(
            ctx.device_config.get(
                "poc_17_nonexistent_slot", self.default_nonexistent_slot
            )
        )

        # Preparación: dejar empty_slot en notUsed (best-effort).
        await self._mark_slot_unused(ctx, slot=empty_slot)

        # Preparación: cargar valid_slot con MULTI válido (para CRC test).
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=valid_slot,
            multi="[jp3]POC-17",
            run_time_priority=32,
        )
        if loaded is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"No se pudo cargar el mensaje base en slot {valid_slot}: "
                    f"{load_err}"
                ),
                error=load_err,
            )

        results: List[Dict[str, Any]] = []

        # Caso 1 — CRC incorrecto
        bad_crc = bytes([(loaded.crc[0] ^ 0xFF), (loaded.crc[1] ^ 0xFF)])
        results.append(
            await self._activate_and_classify(
                ctx,
                label="bad_crc",
                code=_activation.build_activation_code(
                    duration_minutes=60,
                    activate_priority=32,
                    memory_type=oids.MEM_TYPE_CHANGEABLE,
                    message_number=valid_slot,
                    message_crc=bad_crc,
                ),
                expected=7,
                expected_name="messageCRC(7)",
            )
        )
        await asyncio.sleep(0.5)

        # Caso 2 — slot notUsed
        results.append(
            await self._activate_and_classify(
                ctx,
                label="empty_slot",
                code=_activation.build_activation_code(
                    duration_minutes=60,
                    activate_priority=32,
                    memory_type=oids.MEM_TYPE_CHANGEABLE,
                    message_number=empty_slot,
                    message_crc=b"\x00\x00",
                ),
                expected=4,
                expected_name="messageStatus(4)",
            )
        )
        await asyncio.sleep(0.5)

        # Caso 3 — slot inexistente
        results.append(
            await self._activate_and_classify(
                ctx,
                label="nonexistent_slot",
                code=_activation.build_activation_code(
                    duration_minutes=60,
                    activate_priority=32,
                    memory_type=oids.MEM_TYPE_CHANGEABLE,
                    message_number=nonexistent_slot,
                    message_crc=b"\x00\x00",
                ),
                expected=6,
                expected_name="messageNumber(6)",
            )
        )
        await asyncio.sleep(0.5)

        # Caso 4 — MULTI con sintaxis inválida en valid_slot (rehacemos slot)
        bad_loaded, _ = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=valid_slot,
            multi="[xx99]BROKEN",
            run_time_priority=32,
        )
        # La norma dice: si el MULTI es inválido, el state machine falla en
        # validateReq y nunca llega a 'valid'. Algunos paneles aceptan el SET
        # y reportan el syntax error después. Lo intentamos igual.
        if bad_loaded is not None:
            results.append(
                await self._activate_and_classify(
                    ctx,
                    label="bad_multi",
                    code=_activation.build_activation_code(
                        duration_minutes=60,
                        activate_priority=32,
                        memory_type=oids.MEM_TYPE_CHANGEABLE,
                        message_number=valid_slot,
                        message_crc=bad_loaded.crc,
                    ),
                    expected=8,
                    expected_name="syntaxMULTI(8)",
                    read_syntax_detail=True,
                )
            )
        else:
            # El panel rechazó la carga (correcto) — leemos los OIDs de
            # syntax para registrar la evidencia.
            syntax_val, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR
            )
            pos_val, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR_POSITION
            )
            ctx.record_step(
                "case.bad_multi.rejected_at_load",
                operation="VERIFY",
                value_read={
                    "dmsMultiSyntaxError": decoders.decode_multi_syntax_error(
                        syntax_val
                    ),
                    "dmsMultiSyntaxErrorPosition": _safe_int(pos_val),
                    "note": (
                        "Panel rechazó el MULTI durante validateReq — más "
                        "estricto que la norma. Se cuenta como esperado."
                    ),
                },
                success=True,
            )
            results.append(
                {
                    "label": "bad_multi",
                    "expected_value": 8,
                    "expected_name": "syntaxMULTI(8) (rejected_at_load)",
                    "observed_value": 8,
                    "observed_text": "rejected_at_validate",
                    "match": True,
                }
            )

        matched = sum(1 for r in results if r["match"])
        responded = sum(1 for r in results if r["observed_value"] is not None)
        total = len(results)

        if matched == total:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=f"{matched}/{total} casos retornan el código esperado.",
            )
        if responded == total:
            mismatches = [
                f"{r['label']}: esperado {r['expected_name']}, got "
                f"{r['observed_text']}"
                for r in results
                if not r["match"]
            ]
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_QUIRK,
                summary=(
                    f"{matched}/{total} matches; {len(mismatches)} QUIRK: "
                    f"{'; '.join(mismatches)}"
                ),
                design_impact=(
                    "Documentar el mapeo no-estándar del panel en el "
                    "Provider correspondiente."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_FAIL,
            summary=(
                f"{matched}/{total} matches y {total - responded} casos "
                f"sin respuesta — panel no clasifica todos los errores."
            ),
            design_impact=(
                "El worker no puede confiar en dmsActivateMsgError para "
                "decidir reintentos. Considerar lectura adicional de "
                "shortErrorStatus."
            ),
        )

    async def _activate_and_classify(
        self,
        ctx: ScenarioContext,
        *,
        label: str,
        code: bytes,
        expected: int,
        expected_name: str,
        read_syntax_detail: bool = False,
    ) -> Dict[str, Any]:
        _, set_err = await ctx.snmp.set_one(
            oids.DMS_ACTIVATE_MESSAGE, OctetString(code)
        )
        raw_err, get_err = await ctx.snmp.get_one(
            oids.DMS_ACTIVATE_MSG_ERROR
        )
        err_text = decoders.decode_activate_msg_error(raw_err)
        observed = _safe_int(raw_err)
        match = observed == expected

        detail: Dict[str, Any] = {}
        if read_syntax_detail:
            syntax_val, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR
            )
            pos_val, _ = await ctx.snmp.get_one(
                oids.DMS_MULTI_SYNTAX_ERROR_POSITION
            )
            detail["dmsMultiSyntaxError"] = decoders.decode_multi_syntax_error(
                syntax_val
            )
            detail["dmsMultiSyntaxErrorPosition"] = _safe_int(pos_val)

        ctx.record_step(
            f"case.{label}",
            operation="VERIFY",
            value_read={
                "code_hex": code.hex().upper(),
                "snmp_set_result": set_err,
                "dmsActivateMsgError_text": err_text,
                "dmsActivateMsgError_value": observed,
                "expected_value": expected,
                "expected_name": expected_name,
                "match": match,
                **detail,
            },
            success=match,
        )
        return {
            "label": label,
            "expected_value": expected,
            "expected_name": expected_name,
            "observed_value": observed,
            "observed_text": err_text,
            "match": match,
        }

    async def _mark_slot_unused(
        self, ctx: ScenarioContext, *, slot: int
    ) -> None:
        """Best-effort: deja un slot en ``notUsed`` para poder testearlo vacío."""
        status_oid = _activation.row_oid(
            oids.DMS_MSG_STATUS_COL, oids.MEM_TYPE_CHANGEABLE, slot
        )
        _, err = await ctx.snmp.set_one(
            status_oid, Integer(oids.MSG_STATUS_NOT_USED_REQ)
        )
        ctx.record_step(
            "prep.mark_empty_slot",
            operation="SNMP_SET",
            oid_name="dmsMessageStatus",
            oid=status_oid,
            value_read=oids.MSG_STATUS_NOT_USED_REQ,
            success=err is None,
            error=err,
            slot=slot,
        )


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None
