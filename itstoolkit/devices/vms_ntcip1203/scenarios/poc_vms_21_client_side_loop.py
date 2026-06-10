"""POC-VMS-21 — Scheduling client-side: loop de 5 mensajes con timings precisos.

A diferencia de POC-VMS-07/08 (que usan el scheduler INTERNO del panel),
este escenario testea la capacidad de la plataforma de **comandar al panel
desde afuera** con timing preciso. Es el caso de uso real del worker
``Vms.Worker.Schedule`` cuando la programación vive en Serviam.

Estructura del ciclo (9 s):

    MSG-1 → wait 2s → MSG-2 → wait 1s → MSG-3 → wait 3s
                        → MSG-4 → wait 2s → MSG-5 → wait 1s
    (loop)

El POC corre N ciclos hasta agotar la ventana ``duration_seconds`` (default
3600 s ≈ 400 ciclos ≈ 2000 activaciones). Es un test de **endurance** —
detecta:

- Degradación del panel tras muchas activaciones rápidas.
- Drift de timing acumulado.
- Memory leaks (algunos firmwares quedan sin slots tras X mil SETs).

Métricas registradas por activación:

- ``latency_apply_ms``: tiempo entre SET ``dmsActivateMessage`` y el GET
  de ``dmsMsgTableSource`` que confirma el cambio.
- ``activate_err``: código de ``dmsActivateMsgError`` (esperado ``none(2)``).

Métricas por ciclo:

- ``cycle_drift_s``: diferencia entre el tiempo real del ciclo y los 9s
  esperados. Drift positivo = el panel tardó más.

Cleanup:

Al finalizar (o ante abort por errores acumulados), activa un mensaje
``blank`` (``memType=blank(7) / msgNum=32 / CRC=0x0000``) que limpia la
pantalla. Documentado en NTCIP 1203 §5.1 ("MessageActivationCode special
conditions").

Veredicto:

- ``PASS``: completó la ventana, todas las activaciones OK, latencia media
  < ``max_latency_ms`` y drift por ciclo < ``max_cycle_drift_s``.
- ``PARTIAL``: completó pero con latencia / drift fuera de umbral (panel
  funciona pero con timing impreciso).
- ``FAIL``: abortó por ``max_consecutive_errors`` (3 por default) — panel
  degradado tras X activaciones.

Defaults (overridables por device en ``config.yaml``):

    poc_21_duration_seconds: 3600        # 1 h
    poc_21_max_consecutive_errors: 3
    poc_21_max_latency_ms: 500           # umbral para PASS
    poc_21_max_cycle_drift_s: 0.5        # umbral para PASS
    poc_21_slot_base: 235                # slots 235-239

"""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pysnmp.proto.rfc1902 import OctetString

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation


# Secuencia fija de timings del ciclo (segundos a esperar DESPUÉS de cada
# activación, antes de la siguiente). Total: 2+1+3+2+1 = 9 s.
CYCLE_TIMINGS_SECONDS: List[float] = [2.0, 1.0, 3.0, 2.0, 1.0]


class PocVms21ClientSideLoop(Scenario):
    id = "POC-VMS-21"
    name = "Scheduling client-side: loop endurance de 5 mensajes"
    description = (
        "Carga 5 MULTIs y los activa en loop con timings 2/1/3/2/1 s "
        "durante una ventana larga (default 1 h ≈ 400 ciclos). Mide "
        "latencia y drift; detecta degradación del panel."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_duration_seconds: ClassVar[float] = 3600.0
    default_max_consecutive_errors: ClassVar[int] = 3
    default_max_latency_ms: ClassVar[float] = 500.0
    default_max_cycle_drift_s: ClassVar[float] = 0.5
    default_slot_base: ClassVar[int] = 235  # slots 235-239
    default_priority: ClassVar[int] = 32

    # MULTIs simples y visualmente distinguibles
    MULTIS: ClassVar[List[str]] = [
        "[jp3]POC21[nl]MSG-1",
        "[jp3]POC21[nl]MSG-2",
        "[jp3]POC21[nl]MSG-3",
        "[jp3]POC21[nl]MSG-4",
        "[jp3]POC21[nl]MSG-5",
    ]

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        duration = float(
            ctx.device_config.get(
                "poc_21_duration_seconds", self.default_duration_seconds
            )
        )
        max_consec_errors = int(
            ctx.device_config.get(
                "poc_21_max_consecutive_errors",
                self.default_max_consecutive_errors,
            )
        )
        max_latency_ms = float(
            ctx.device_config.get(
                "poc_21_max_latency_ms", self.default_max_latency_ms
            )
        )
        max_drift_s = float(
            ctx.device_config.get(
                "poc_21_max_cycle_drift_s", self.default_max_cycle_drift_s
            )
        )
        slot_base = int(
            ctx.device_config.get("poc_21_slot_base", self.default_slot_base)
        )

        slots = [slot_base + i for i in range(len(self.MULTIS))]

        # Fase 1: cargar los 5 mensajes
        loaded_msgs: List[_activation.LoadedMessage] = []
        for i, (slot, multi) in enumerate(zip(slots, self.MULTIS)):
            msg, err = await _activation.load_message_into_slot(
                ctx,
                memory_type=oids.MEM_TYPE_CHANGEABLE,
                message_number=slot,
                multi=multi,
                run_time_priority=self.default_priority,
            )
            if msg is None:
                return ScenarioResult(
                    scenario_id=self.id,
                    status=STATUS_FAIL,
                    summary=(
                        f"No se pudo cargar MSG-{i + 1} en slot {slot}: {err}"
                    ),
                    error=err,
                )
            loaded_msgs.append(msg)
        ctx.record_step(
            "phase1.all_loaded",
            operation="VERIFY",
            value_read={
                "slots": slots,
                "loaded_count": len(loaded_msgs),
                "expected_cycle_seconds": sum(CYCLE_TIMINGS_SECONDS),
            },
            success=True,
        )

        # Fase 2: loop de activaciones
        loop = asyncio.get_event_loop()
        deadline = loop.time() + duration
        cycle_idx = 0
        total_activations = 0
        total_errors = 0
        consecutive_errors = 0
        latencies_ms: List[float] = []
        cycle_drifts_s: List[float] = []
        abort_reason: Optional[str] = None

        while loop.time() < deadline:
            cycle_idx += 1
            cycle_start = loop.time()

            for msg_idx, msg in enumerate(loaded_msgs):
                if loop.time() >= deadline:
                    # se acabó la ventana en mitad del ciclo
                    break

                t_set = loop.time()
                err_text, err_value = await _activation.activate_message(
                    ctx, loaded=msg
                )

                total_activations += 1
                if err_value != 2:  # none(2)
                    total_errors += 1
                    consecutive_errors += 1
                    ctx.record_step(
                        f"cycle_{cycle_idx}.msg_{msg_idx + 1}.activate_err",
                        operation="VERIFY",
                        value_read={
                            "activate_err_text": err_text,
                            "activate_err_value": err_value,
                            "consecutive_errors": consecutive_errors,
                        },
                        success=False,
                    )
                    if consecutive_errors >= max_consec_errors:
                        abort_reason = (
                            f"{consecutive_errors} errores consecutivos "
                            f"tras {total_activations} activaciones"
                        )
                        break
                else:
                    consecutive_errors = 0
                    # Confirmar el cambio leyendo dmsMsgTableSource
                    confirmed_at, confirmed_ok = await self._wait_msg_src_match(
                        ctx,
                        expected_slot=msg.message_number,
                        timeout_s=1.0,
                    )
                    latency_ms = (confirmed_at - t_set) * 1000.0 if confirmed_ok else None
                    if latency_ms is not None:
                        latencies_ms.append(latency_ms)
                    # Solo emitimos record cada N activaciones para no
                    # generar 2000 líneas de evidencia.
                    if total_activations % 10 == 1:
                        ctx.record_step(
                            f"cycle_{cycle_idx}.msg_{msg_idx + 1}.sample",
                            operation="VERIFY",
                            value_read={
                                "latency_apply_ms": (
                                    round(latency_ms, 1) if latency_ms else None
                                ),
                                "confirmed_msg_src": confirmed_ok,
                                "cumulative_activations": total_activations,
                            },
                            success=True,
                        )

                # Esperar el timing definido antes de la siguiente activación
                await asyncio.sleep(CYCLE_TIMINGS_SECONDS[msg_idx])

            if abort_reason:
                break

            cycle_end = loop.time()
            cycle_real = cycle_end - cycle_start
            drift = cycle_real - sum(CYCLE_TIMINGS_SECONDS)
            cycle_drifts_s.append(drift)

            # Resumen periódico cada 10 ciclos
            if cycle_idx % 10 == 0:
                ctx.record_step(
                    f"checkpoint.cycle_{cycle_idx}",
                    operation="VERIFY",
                    value_read={
                        "cycles_completed": cycle_idx,
                        "total_activations": total_activations,
                        "total_errors": total_errors,
                        "drift_last_cycle_s": round(drift, 3),
                        "elapsed_s": round(loop.time() - (deadline - duration), 1),
                        "remaining_s": round(deadline - loop.time(), 1),
                    },
                    success=True,
                )

        # Cleanup: blank the sign
        await self._blank_sign(ctx)

        # Resumen final
        elapsed = duration - max(0.0, deadline - loop.time())
        lat_mean = (
            round(sum(latencies_ms) / len(latencies_ms), 1)
            if latencies_ms
            else None
        )
        lat_max = round(max(latencies_ms), 1) if latencies_ms else None
        drift_mean = (
            round(sum(cycle_drifts_s) / len(cycle_drifts_s), 3)
            if cycle_drifts_s
            else None
        )
        drift_max = (
            round(max(abs(d) for d in cycle_drifts_s), 3)
            if cycle_drifts_s
            else None
        )

        ctx.record_step(
            "summary",
            operation="VERIFY",
            value_read={
                "duration_target_s": duration,
                "duration_elapsed_s": round(elapsed, 1),
                "cycles_completed": len(cycle_drifts_s),
                "total_activations": total_activations,
                "total_errors": total_errors,
                "latency_apply_ms_mean": lat_mean,
                "latency_apply_ms_max": lat_max,
                "cycle_drift_s_mean": drift_mean,
                "cycle_drift_s_max": drift_max,
                "abort_reason": abort_reason,
            },
            success=True,
        )

        # Veredicto
        if abort_reason:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Abortado tras {total_activations} activaciones: "
                    f"{abort_reason}. {len(cycle_drifts_s)} ciclos completos."
                ),
                error=abort_reason,
                design_impact=(
                    "Panel degrada bajo carga sostenida — limitar la tasa de "
                    "activaciones del worker o agregar back-off."
                ),
            )

        latency_ok = lat_mean is None or lat_mean <= max_latency_ms
        drift_ok = drift_max is None or drift_max <= max_drift_s

        if latency_ok and drift_ok:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    f"{len(cycle_drifts_s)} ciclos / {total_activations} "
                    f"activaciones OK. Latencia media {lat_mean}ms, "
                    f"drift max {drift_max}s."
                ),
            )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PARTIAL,
            summary=(
                f"{len(cycle_drifts_s)} ciclos / {total_activations} "
                f"activaciones OK pero timing fuera de umbral: "
                f"latencia media {lat_mean}ms (max {max_latency_ms}ms), "
                f"drift max {drift_max}s (max {max_drift_s}s)."
            ),
            design_impact=(
                "Worker debe asumir jitter en la aplicación de mensajes "
                "y no usar timings finos (< 1 s) para scheduling crítico."
            ),
        )

    async def _wait_msg_src_match(
        self,
        ctx: ScenarioContext,
        *,
        expected_slot: int,
        timeout_s: float,
    ) -> Tuple[float, bool]:
        """Poll ``dmsMsgTableSource`` hasta que apunte al slot esperado.

        Devuelve ``(timestamp_de_confirmacion, ok)``. ``ok=False`` si el
        timeout venció sin confirmar.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        while True:
            raw, err = await ctx.snmp.get_one(oids.MSG_SRC)
            now = loop.time()
            if err is None and raw is not None:
                mid = decoders.decode_message_id_code(raw)
                if (
                    mid["valid"]
                    and mid["memory_type"] == oids.MEM_TYPE_CHANGEABLE
                    and mid["message_number"] == expected_slot
                ):
                    return now, True
            if now >= deadline:
                return now, False
            await asyncio.sleep(0.05)

    async def _blank_sign(self, ctx: ScenarioContext) -> None:
        """Activar mensaje 'blank' al cierre — limpia la pantalla.

        NTCIP 1203 §5.1: ``memType=blank(7)`` activa pantalla en blanco.
        ``msgNum`` es la prioridad deseada; CRC siempre ``0x0000``.
        """
        blank_code = _activation.build_activation_code(
            duration_minutes=65535,
            activate_priority=self.default_priority,
            memory_type=oids.MEM_TYPE_BLANK,
            message_number=self.default_priority,  # NTCIP §5.1: msgNum = priority
            message_crc=b"\x00\x00",
        )
        _, err = await ctx.snmp.set_one(
            oids.DMS_ACTIVATE_MESSAGE, OctetString(blank_code)
        )
        ctx.record_step(
            "cleanup.blank_sign",
            operation="SNMP_SET",
            oid_name="dmsActivateMessage",
            oid=oids.DMS_ACTIVATE_MESSAGE,
            value_read=blank_code.hex().upper(),
            success=err is None,
            error=err,
            notes="memType=blank(7), msgNum=priority, CRC=0x0000",
        )
