"""POC-VMS-05 — Activación manual básica.

Valida la operación más fundamental del sistema: enviar un MULTI por SNMP y
confirmar que se muestra en el panel. Si esto no funciona, nada de lo que
viene después (prioridades, schedule, monitoreo de divergencia) tiene
sentido.

Pasos (estándar NTCIP 1203 §A.3 — ritual de carga + activación):

1. Snapshot del estado actual (``dmsControlMode``, mensaje activo,
    ``shortErrorStatus``).
2. Cargar el MULTI de prueba en un slot ``changeable`` siguiendo el state
    machine de ``dmsMessageStatus`` (``modifyReq`` → escribir contenido →
    ``validateReq`` → leer CRC). Ver :mod:`._activation`.
3. Construir ``MessageActivationCode`` con el CRC del panel y disparar
    ``dmsActivateMessage``.
4. Leer ``dmsActivateMsgError`` — debe ser ``none(2)``.
5. Esperar 3 segundos y leer el mensaje activo + hash.
6. Comparar hash esperado vs hash reportado.

Criterio:

- ``PASS`` si ``dmsActivateMsgError = none(2)`` y el hash reportado coincide
    con el calculado localmente sobre el MULTI enviado.
- ``PARTIAL`` si la activación responde ``none`` pero el panel no muestra el
    MULTI esperado (panel acepta pero transforma — documentar QUIRK).
- ``FAIL`` si la activación falla o el ritual de carga no llega a ``valid``.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

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
from . import _activation


class PocVms05ActivateManual(Scenario):
    id = "POC-VMS-05"
    name = "Activación manual básica"
    description = (
        "Carga un MULTI en un slot changeable siguiendo el ritual NTCIP 1203 "
        "(modifyReq → escribir → validateReq → activate) y verifica que el "
        "panel lo muestra. Es la operación más fundamental del sistema."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    #: Slot ``changeable`` que usamos para la prueba (default alto para no
    #: pisar slots operativos; overridable vía ``poc_05_slot`` en el YAML).
    slot_memory_type: ClassVar[int] = oids.MEM_TYPE_CHANGEABLE
    default_slot_number: ClassVar[int] = 250
    test_multi: ClassVar[str] = "[jp3]ITSTK[nl]POC-VMS-05"
    test_priority: ClassVar[int] = 64
    settle_seconds: ClassVar[float] = 3.0

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        slot_number = int(
            ctx.device_config.get("poc_05_slot", self.default_slot_number)
        )
        # Paso 1 — snapshot
        vals, err = await ctx.snmp.get_many(oids.required_oids())
        if err in ("TIMEOUT", "SNMP_ERROR"):
            ctx.record_step(
                "snapshot_initial",
                operation="SNMP_GET",
                oid_name="ctrl+src+msg_src+short_err",
                success=False,
                error=err,
            )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Snapshot inicial falló con {err}.",
                error=err,
            )
        ctx.record_step(
            "snapshot_initial",
            operation="DECODE",
            value_read={
                "ctrl": decoders.decode_control_mode(vals.get(oids.CTRL_MODE)),
                "src": decoders.decode_source_mode(vals.get(oids.SRC_MODE)),
                "short_err": decoders.decode_short_error_status(
                    vals.get(oids.SHORT_ERR)
                )[0],
            },
            success=True,
        )

        # Paso 2 — cargar el MULTI siguiendo el state machine
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=self.slot_memory_type,
            message_number=slot_number,
            multi=self.test_multi,
            run_time_priority=self.test_priority,
        )
        if loaded is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"No se pudo cargar el MULTI en slot "
                    f"{self.slot_memory_type}.{slot_number}: {load_err}"
                ),
                error=load_err,
                design_impact=(
                    "Sin ritual de carga funcional no se puede activar nada "
                    "vía SNMP — revisar permisos write o estado del slot."
                ),
            )

        # Paso 3 — activar
        err_text, err_value = await _activation.activate_message(
            ctx, loaded=loaded
        )
        if err_value != 2:  # 2 = none
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Activación rechazada por panel: {err_text}.",
                error=err_text,
                design_impact=(
                    "El panel acepta el ritual de carga pero rechaza la "
                    "activación — documentar el código de error como QUIRK."
                ),
            )

        # Paso 4 — esperar y verificar
        await asyncio.sleep(self.settle_seconds)
        msg_src, get_err = await ctx.snmp.get_one(oids.MSG_SRC)
        mid = decoders.decode_message_id_code(msg_src)
        ctx.record_step(
            "verify.read_msg_src",
            operation="SNMP_GET",
            oid_name="dmsMsgTableSource",
            oid=oids.MSG_SRC,
            value_read={
                "raw_hex": mid.get("raw_hex"),
                "memory_type": mid.get("memory_type"),
                "message_number": mid.get("message_number"),
            },
            success=get_err is None and mid["valid"],
            error=get_err,
        )

        if not mid["valid"] or (
            mid["memory_type"] != self.slot_memory_type
            or mid["message_number"] != slot_number
        ):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Activación respondió none(2) pero msg_src no apunta al "
                    f"slot {self.slot_memory_type}.{slot_number}."
                ),
                design_impact=(
                    "El panel acepta el SET pero no refleja el nuevo mensaje "
                    "en dmsMsgTableSource — revisar timing o cache del panel."
                ),
            )

        # Comparar MULTI reportado con el enviado
        multi_oid_str = oids.multi_oid(
            self.slot_memory_type, slot_number
        )
        raw_val, multi_err = await ctx.snmp.get_one(multi_oid_str)
        reported_text = snmp_values.decode_octet_text(raw_val) if raw_val else ""
        expected_hash = hash_multi(self.test_multi)
        reported_hash = hash_multi(reported_text or "")
        ctx.record_step(
            "verify.compare_multi",
            operation="SNMP_GET",
            oid_name="dmsMessageMultiString",
            oid=multi_oid_str,
            value_read=reported_text,
            success=multi_err is None,
            error=multi_err,
            expected_sha256=expected_hash,
            reported_sha256=reported_hash,
        )

        if expected_hash != reported_hash:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    "Activación OK pero el MULTI reportado difiere del "
                    "enviado — el panel está transformando el contenido."
                ),
                design_impact=(
                    "Documentar la transformación que aplica el firmware. "
                    "MessageMonitor debe normalizar antes de comparar hashes."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"MULTI activado y verificado en slot "
                f"{self.slot_memory_type}.{slot_number} "
                f"(hash {expected_hash[:12]}...)."
            ),
        )
