"""POC-VMS-04 — Lectura del mensaje actualmente mostrado.

Confirma que el panel reporta por SNMP el mensaje que está mostrando. Es la
base del mecanismo de divergencia: si la lectura del mensaje activo no es
confiable, el ``MessageMonitor`` no puede funcionar.

Pasos:

1. Leer ``dmsControlMode``, ``dmsMessageSourceMode``, ``dmsMsgTableSource``,
    ``shortErrorStatus``.
2. Decodificar ``dmsMsgTableSource`` para obtener ``memory_type`` +
    ``message_number``.
3. ``GET`` del MULTI activo en ``dmsMessageMultiString[memory_type][message_number]``.
4. Calcular el SHA-256 del MULTI normalizado.
5. Registrar todo en evidencia.

Criterio: ``PASS`` si se puede leer el MULTI; ``PARTIAL`` si el control plane
responde pero el MULTI no decodifica (panel sin mensaje activo válido);
``FAIL`` si los OIDs de control no responden.
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
    hash_multi,
)
from itstoolkit.protocols.snmp import values as snmp_values

from .. import decoders, oids


class PocVms04ReadActiveMessage(Scenario):
    id = "POC-VMS-04"
    name = "Lectura del mensaje actualmente mostrado"
    description = (
        "Lee el estado de control + el MULTI activo y calcula su hash. "
        "Es la base del MessageMonitor (divergencia expected vs reported)."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        # Paso 1: control plane
        control_oids = oids.required_oids()
        vals, err = await ctx.snmp.get_many(control_oids)
        if err in ("TIMEOUT", "SNMP_ERROR"):
            ctx.record_step(
                "read_control_plane",
                operation="SNMP_GET",
                oid_name="ctrl+src+msg_src+short_err",
                success=False,
                error=err,
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Lectura de control falló con {err}.",
                error=err,
            )

        ctrl = decoders.decode_control_mode(vals.get(oids.CTRL_MODE))
        src = decoders.decode_source_mode(vals.get(oids.SRC_MODE))
        err_text, err_raw = decoders.decode_short_error_status(vals.get(oids.SHORT_ERR))
        mid = decoders.decode_message_id_code(vals.get(oids.MSG_SRC))

        ctx.record_step(
            "decode_control_plane",
            operation="DECODE",
            oid_name="ctrl+src+msg_src+short_err",
            value_read={
                "ctrl": ctrl,
                "src": src,
                "msg_id_raw": mid.get("raw_hex"),
                "memory_type": mid.get("memory_type"),
                "message_number": mid.get("message_number"),
                "short_error": err_text,
                "short_error_raw": err_raw,
            },
            success=True,
        )

        if not mid["valid"]:
            ctx.record_step(
                "msg_id_invalid",
                operation="DECODE",
                oid_name="dmsMsgTableSource",
                success=False,
                error="message_id_undecodable",
                notes=(
                    "msg_id no decodificable: el panel puede no estar mostrando "
                    "un mensaje válido del catálogo de slots."
                ),
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    "Control plane OK pero msg_id no decodifica — sin mensaje "
                    "activo válido en el catálogo."
                ),
                design_impact=(
                    "MessageMonitor debe tolerar este estado (blank/unknown) "
                    "como un caso explícito, no como una falla de lectura."
                ),
            )

        # Paso 2: leer el MULTI
        multi_oid_str = oids.multi_oid(mid["memory_type"], mid["message_number"])
        raw_val, multi_err = await ctx.snmp.get_one(multi_oid_str)
        if multi_err is not None or raw_val is None:
            ctx.record_step(
                "read_multi",
                operation="SNMP_GET",
                oid_name="dmsMessageMultiString",
                oid=multi_oid_str,
                value_read=None,
                success=False,
                error=multi_err or "NoSuchObject",
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Control plane OK pero MULTI[{mid['memory_type']}.{mid['message_number']}] "
                    f"no se pudo leer ({multi_err or 'NoSuchObject'})."
                ),
                design_impact=(
                    "Documentar qué retorna el panel cuando el mensaje activo "
                    "apunta a un slot vacío o no leído."
                ),
            )

        text = snmp_values.decode_octet_text(raw_val) or ""
        h = hash_multi(text)
        ctx.record_step(
            "read_multi",
            operation="SNMP_GET",
            oid_name="dmsMessageMultiString",
            oid=multi_oid_str,
            value_read=text,
            success=True,
            multi_sha256=h,
            multi_length=len(text),
        )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"MULTI leído correctamente ({len(text)} caracteres, "
                f"hash {h[:12]}...)."
            ),
        )
