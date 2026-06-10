"""Modo `scenario` — ejecutor de escenarios PoC del adapter.

API:

- :func:`list_scenarios(family)` enumera escenarios registrados por el
    adapter de esa familia (id, name, mode, requires_write).
- :func:`run_scenarios(devices, ...)` ejecuta el subconjunto pedido y
    devuelve la lista de :class:`ScenarioResult` en el mismo orden.

Política de seguridad (doble gate):

El runner construye el ``WriteGuard`` **antes** de instanciar el cliente
SNMP:

    config_confirmed = device_config.get("confirm_write", False)
    cli_confirmed    = cli_confirm_write
    => DoubleGateWriteGuard.from_flags(...)

Si un scenario declara ``requires_write=True`` y el guard no autoriza
escritura, queda ``BLOCKED`` con la razón en el JSONL — el cliente SNMP no
llega a abrirse.

Evidencia:

Cada scenario escribe a un ``JsonlSink`` propio en::

    <evidence_directory>/<family>/<device_name>/<run_ts>/<scenario_id>.jsonl

(default ``evidence_directory="evidence"``). Todos los escenarios de una
misma llamada a :func:`run_scenarios` comparten el mismo ``run_ts``, de
modo que la carpeta de la corrida agrupa todos los PoCs ejecutados juntos.
El sink se cierra al finalizar incluso si el scenario falla.

Inyección de dependencias:

``session_factory`` permite sustituir el SnmpClient real por una sesión
mockeada en tests. Default: abre ``SnmpClient(write_guard=...)`` y un
transport UDP contra ``ip:port``.
"""

from __future__ import annotations

from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
)

from itstoolkit.core.device import device_registry
from itstoolkit.core.evidence import JsonlSink
from itstoolkit.core.safety import DoubleGateWriteGuard, WriteGuard
from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_BLOCKED,
    STATUS_FAIL,
    Scenario,
    ScenarioContext,
    ScenarioResult,
    SnmpSession,
    evidence_path,
    utc_filename_ts,
)
from itstoolkit.protocols.snmp.client import SnmpClient


SessionFactory = Callable[
    [Mapping[str, Any], WriteGuard], Awaitable[SnmpSession]
]


# ---------------------------------------------------------------------------
# Sesión SNMP "real" — bound a (client, transport, community)
# ---------------------------------------------------------------------------


class _RealSnmpSession:
    """Adapta ``SnmpClient`` a la interfaz :class:`SnmpSession` (sin transport en cada call)."""

    def __init__(self, client: SnmpClient, transport: Any, community: str) -> None:
        self.client = client
        self.transport = transport
        self.community = community

    async def get_many(self, oids):
        return await self.client.get_many(self.transport, self.community, list(oids))

    async def get_one(self, oid):
        return await self.client.get_one(self.transport, self.community, oid)

    async def set_many(self, varbinds):
        return await self.client.set_many(
            self.transport, self.community, list(varbinds)
        )

    async def set_one(self, oid, value):
        return await self.client.set_one(self.transport, self.community, oid, value)

    async def close(self) -> None:
        # pysnmp SnmpEngine se libera por GC; no hay close() asincrónico.
        return None


async def default_session_factory(
    device_config: Mapping[str, Any], write_guard: WriteGuard
) -> SnmpSession:
    """Factory por defecto: abre cliente + transport reales contra el panel."""
    client = SnmpClient(write_guard=write_guard)
    transport = await client.make_transport(
        device_config["ip"], int(device_config.get("port", 161))
    )
    return _RealSnmpSession(
        client, transport, str(device_config.get("community", "public"))
    )


# ---------------------------------------------------------------------------
# Listado / selección
# ---------------------------------------------------------------------------


def _adapter_scenarios(family: str) -> List[Scenario]:
    adapter_cls = device_registry.get(family)
    adapter = adapter_cls()
    return list(adapter.scenarios())


def list_scenarios(family: str) -> List[Dict[str, Any]]:
    """Listar los escenarios registrados por una familia.

    Devuelve una lista de dicts (id, name, description, execution_mode,
    requires_write) en el orden de declaración del adapter.
    """
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "execution_mode": s.execution_mode,
            "requires_write": bool(s.requires_write),
        }
        for s in _adapter_scenarios(family)
    ]


def _select(
    scenarios: Sequence[Scenario],
    *,
    scenario_ids: Optional[Sequence[str]] = None,
    automatic_only: bool = False,
) -> List[Scenario]:
    out = list(scenarios)
    if scenario_ids:
        wanted = list(scenario_ids)
        known = {s.id for s in scenarios}
        missing = [w for w in wanted if w not in known]
        if missing:
            raise KeyError(
                f"Escenarios no encontrados: {missing}. "
                f"Conocidos: {sorted(known)}"
            )
        wanted_set = set(wanted)
        out = [s for s in out if s.id in wanted_set]
    if automatic_only:
        out = [s for s in out if s.execution_mode == EXEC_AUTOMATIC]
    return out


# ---------------------------------------------------------------------------
# Doble gate
# ---------------------------------------------------------------------------


def _build_write_guard(
    device_config: Mapping[str, Any], cli_confirm_write: bool
) -> WriteGuard:
    """Construir el WriteGuard a partir de los flags reales del runner."""
    return DoubleGateWriteGuard.from_flags(
        config_confirmed=bool(device_config.get("confirm_write", False)),
        cli_confirmed=bool(cli_confirm_write),
    )


def _gate_missing_reasons(
    device_config: Mapping[str, Any], cli_confirm_write: bool
) -> List[str]:
    out: List[str] = []
    if not bool(device_config.get("confirm_write", False)):
        out.append("confirm_write=true en config")
    if not cli_confirm_write:
        out.append("--confirm-write en CLI")
    return out


# ---------------------------------------------------------------------------
# Ejecución de un scenario
# ---------------------------------------------------------------------------


async def _run_one(
    scenario: Scenario,
    device_config: Mapping[str, Any],
    *,
    family: str,
    cli_confirm_write: bool,
    session_factory: SessionFactory,
    evidence_directory: str,
    run_ts: str,
    cleanup_after_each: bool = False,
) -> ScenarioResult:
    guard = _build_write_guard(device_config, cli_confirm_write)
    path = evidence_path(
        family,
        scenario.id,
        str(device_config.get("name", "device")),
        directory=evidence_directory,
        run_ts=run_ts,
    )
    sink = JsonlSink(path)
    try:
        # Doble gate: BLOCKED antes de abrir cualquier transporte.
        if scenario.requires_write and not guard.allow_write:
            reasons = _gate_missing_reasons(device_config, cli_confirm_write)
            summary = (
                "Scenario requiere escritura pero falta el doble gate: "
                + " + ".join(reasons)
            )
            ctx_blocked = ScenarioContext(
                device_config=device_config,
                snmp=_NoSession(),  # type: ignore[arg-type]
                evidence=sink,
                write_guard=guard,
                scenario_id=scenario.id,
            )
            ctx_blocked.record_step(
                "gate_check",
                operation="WRITE_GATE",
                success=False,
                error="DOUBLE_GATE_MISSING",
                notes=summary,
                missing=reasons,
            )
            result = ScenarioResult(
                scenario_id=scenario.id,
                status=STATUS_BLOCKED,
                summary=summary,
                evidence_path=path,
            )
            ctx_blocked.record_summary(result)
            return result

        # Abrir sesión real (o mockeada).
        try:
            session = await session_factory(device_config, guard)
        except Exception as exc:
            ctx_fail = ScenarioContext(
                device_config=device_config,
                snmp=_NoSession(),  # type: ignore[arg-type]
                evidence=sink,
                write_guard=guard,
                scenario_id=scenario.id,
            )
            ctx_fail.record_step(
                "session_open",
                operation="TRANSPORT",
                success=False,
                error=repr(exc),
            )
            result = ScenarioResult(
                scenario_id=scenario.id,
                status=STATUS_FAIL,
                summary=f"No se pudo abrir la sesión SNMP: {exc}",
                evidence_path=path,
                error=repr(exc),
            )
            ctx_fail.record_summary(result)
            return result

        ctx = ScenarioContext(
            device_config=device_config,
            snmp=session,
            evidence=sink,
            write_guard=guard,
            scenario_id=scenario.id,
        )
        try:
            result = await scenario.run(ctx)
        except Exception as exc:
            ctx.record_step(
                "exception",
                operation="SCENARIO",
                success=False,
                error=repr(exc),
            )
            result = ScenarioResult(
                scenario_id=scenario.id,
                status=STATUS_FAIL,
                summary=f"Excepción durante el scenario: {exc}",
                error=repr(exc),
            )

        # Cleanup post-scenario (opt-in). Solo tiene sentido si el guard
        # permite escritura — un scenario read-only no ensucia nada igual.
        # Se ejecuta SIEMPRE (PASS/PARTIAL/FAIL) para no dejar slots
        # ocupados tras un fallo a mitad de ritual.
        if cleanup_after_each and guard.allow_write:
            try:
                adapter_cls = device_registry.get(family)
                adapter_instance = adapter_cls()
                did_cleanup = await adapter_instance.cleanup_after_scenario(
                    device_config, ctx
                )
                ctx.record_step(
                    "cleanup.done",
                    operation="VERIFY",
                    value_read={"cleanup_executed": did_cleanup},
                    success=True,
                )
            except Exception as exc:
                ctx.record_step(
                    "cleanup.exception",
                    operation="VERIFY",
                    success=False,
                    error=repr(exc),
                    notes=(
                        "Cleanup post-scenario falló — el slot/acción puede "
                        "haber quedado en estado intermedio."
                    ),
                )

        try:
            await session.close()
        except Exception:
            pass

        result.evidence_path = path
        ctx.record_summary(result)
        return result
    finally:
        try:
            sink.close()
        except Exception:
            pass


class _NoSession:
    """Stub usado cuando el scenario quedó BLOCKED o no se pudo abrir sesión.

    No expone get_*; está sólo para satisfacer el tipo de ``ScenarioContext.snmp``
    en records de evidencia que no requieren SNMP.
    """

    async def get_many(self, oids):  # pragma: no cover - no se llama
        raise RuntimeError("No SNMP session available for this scenario.")

    async def get_one(self, oid):  # pragma: no cover
        raise RuntimeError("No SNMP session available for this scenario.")

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# API pública del runner
# ---------------------------------------------------------------------------


async def run_scenarios(
    devices: Sequence[Mapping[str, Any]],
    *,
    scenario_ids: Optional[Sequence[str]] = None,
    automatic_only: bool = False,
    cli_confirm_write: bool = False,
    session_factory: Optional[SessionFactory] = None,
    evidence_directory: str = "evidence",
    cleanup_after_each: bool = False,
) -> List[ScenarioResult]:
    """Ejecutar escenarios sobre una lista de dispositivos.

    Para cada device: resolvió family → adapter → escenarios → filtra por
    ``scenario_ids`` y ``automatic_only`` → ejecuta uno a uno.

    El orden de devices se respeta; dentro de cada device el orden es el de
    declaración del adapter. Si un scenario falla, los siguientes corren
    igual y registran su propio veredicto.
    """
    sf = session_factory or default_session_factory
    run_ts = utc_filename_ts()
    results: List[ScenarioResult] = []
    for dev in devices:
        family = dev.get("family")
        if not family:
            raise ValueError(f"Device {dev.get('name')!r} sin 'family'.")
        adapter_cls = device_registry.get(family)
        adapter = adapter_cls()
        scenarios = list(adapter.scenarios())
        selected = _select(
            scenarios,
            scenario_ids=scenario_ids,
            automatic_only=automatic_only,
        )
        for sc in selected:
            res = await _run_one(
                sc,
                dev,
                family=family,
                cli_confirm_write=cli_confirm_write,
                session_factory=sf,
                evidence_directory=evidence_directory,
                run_ts=run_ts,
                cleanup_after_each=cleanup_after_each,
            )
            results.append(res)
    return results


__all__ = [
    "list_scenarios",
    "run_scenarios",
    "default_session_factory",
    "SessionFactory",
]
