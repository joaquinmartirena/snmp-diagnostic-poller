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

    <evidence_directory>/<family>/<scenario_id>_<device_name>_<UTC-ts>.jsonl

(default ``evidence_directory="evidence"``). El sink se cierra al finalizar
incluso si el scenario falla.

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
) -> ScenarioResult:
    guard = _build_write_guard(device_config, cli_confirm_write)
    path = evidence_path(
        family,
        scenario.id,
        str(device_config.get("name", "device")),
        directory=evidence_directory,
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
        finally:
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
) -> List[ScenarioResult]:
    """Ejecutar escenarios sobre una lista de dispositivos.

    Para cada device: resolvió family → adapter → escenarios → filtra por
    ``scenario_ids`` y ``automatic_only`` → ejecuta uno a uno.

    El orden de devices se respeta; dentro de cada device el orden es el de
    declaración del adapter. Si un scenario falla, los siguientes corren
    igual y registran su propio veredicto.
    """
    sf = session_factory or default_session_factory
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
            )
            results.append(res)
    return results


__all__ = [
    "list_scenarios",
    "run_scenarios",
    "default_session_factory",
    "SessionFactory",
]
