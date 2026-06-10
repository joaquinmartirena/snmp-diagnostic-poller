"""Contrato de Scenario y modelos de resultado (Fase 5).

Un Scenario es una validación específica de un dispositivo: corre contra un
panel real, recolecta evidencia estructurada (JSONL) y produce un veredicto
(PASS / FAIL / PARTIAL / QUIRK_PROVIDER / BLOCKED). Los Scenarios viven en
``itstoolkit.devices.<familia>.scenarios.*`` y el adapter los expone vía
``DeviceAdapter.scenarios()`` — el modo `scenario` los descubre por ahí, sin
registry global ni scan automático.

El runner aplica el doble gate de ``WriteGuard`` **antes** de instanciar el
cliente SNMP: un scenario con ``requires_write=True`` solo recibe un cliente
writable cuando ``confirm_write=True`` en config + ``--confirm-write`` en
CLI están puestos. Si falta cualquiera, el scenario queda ``BLOCKED`` sin
intentar ninguna escritura.

Evidencia: ``JsonlSink`` de :mod:`itstoolkit.core.evidence`. No se inventa
otro logging paralelo.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    Any,
    ClassVar,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from .evidence import EvidenceRecord, EvidenceSink, now_ts
from .safety import WriteGuard

# ---------------------------------------------------------------------------
# Constantes de modo / status (strings, no enums, para serializar limpio a JSONL)
# ---------------------------------------------------------------------------

EXEC_AUTOMATIC = "AUTOMATIC"
EXEC_REQUIRES_PHYSICAL = "REQUIRES_PHYSICAL"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_PARTIAL = "PARTIAL"
STATUS_QUIRK = "QUIRK_PROVIDER"
STATUS_BLOCKED = "BLOCKED"

ExecutionMode = str
ScenarioStatus = str


# ---------------------------------------------------------------------------
# Sesión SNMP — API mínima que un Scenario consume
# ---------------------------------------------------------------------------


@runtime_checkable
class SnmpSession(Protocol):
    """API mínima del transporte SNMP que un Scenario usa.

    El runner construye una sesión real (``SnmpClient`` + transport + community
    bound) o una mockeada en tests. El Scenario nunca abre transports ni
    clientes — recibe la sesión ya configurada vía :class:`ScenarioContext`.
    """

    async def get_many(
        self, oids: Sequence[str]
    ) -> Tuple[Mapping[str, Any], Optional[str]]:
        ...

    async def get_one(self, oid: str) -> Tuple[Any, Optional[str]]:
        ...

    async def set_many(
        self, varbinds: Sequence[Tuple[str, Any]]
    ) -> Tuple[Mapping[str, Any], Optional[str]]:
        ...

    async def set_one(self, oid: str, value: Any) -> Tuple[Any, Optional[str]]:
        ...

    async def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Resultado y contexto
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Veredicto de un scenario, espejo del cierre que pide el doc PoC §3."""

    scenario_id: str
    status: ScenarioStatus
    summary: str = ""
    design_impact: str = ""
    evidence_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ScenarioContext:
    """Todo lo que un Scenario recibe en runtime.

    Compuesto por el runner. El Scenario no abre archivos, transports ni
    clientes: consume ``self.snmp`` (sesión), ``self.evidence`` (sink) y
    ``self.write_guard`` (para chequeos defensivos, aunque el runner ya
    bloqueó si el gate no estaba).
    """

    device_config: Mapping[str, Any]
    snmp: SnmpSession
    evidence: EvidenceSink
    write_guard: WriteGuard
    scenario_id: str = ""

    # -- helpers de evidencia ----------------------------------------------

    def record_step(
        self,
        step: str,
        *,
        operation: str = "SNMP_GET",
        oid_name: Optional[str] = None,
        oid: Optional[str] = None,
        value_read: Any = None,
        success: bool = True,
        error: Optional[str] = None,
        notes: str = "",
        **extra: Any,
    ) -> None:
        """Emitir un step record en el JSONL.

        Mantiene el shape del doc PoC §3:
        ``{scenario_id, step, timestamp_utc, operation, oid_name, oid,
        value_read, success, error, notes}``.
        """
        payload = {
            "scenario_id": self.scenario_id,
            "step": step,
            "timestamp_utc": utc_iso(),
            "operation": operation,
            "oid_name": oid_name,
            "oid": oid,
            "value_read": safe_value(value_read),
            "success": bool(success),
            "error": error,
            "notes": notes,
        }
        if extra:
            payload.update(extra)
        self.evidence.write(EvidenceRecord(timestamp=now_ts(), payload=payload))

    def record_summary(self, result: ScenarioResult) -> None:
        """Emitir el record final con el veredicto del scenario."""
        self.evidence.write(
            EvidenceRecord(
                timestamp=now_ts(),
                payload={
                    "scenario_id": self.scenario_id,
                    "result": result.status,
                    "summary": result.summary,
                    "design_impact": result.design_impact,
                    "error": result.error,
                    "timestamp_utc": utc_iso(),
                },
            )
        )


# ---------------------------------------------------------------------------
# Contrato base del Scenario
# ---------------------------------------------------------------------------


class Scenario(ABC):
    """Contrato base de un escenario PoC.

    Subclases declaran metadata como atributos de clase y exponen ``run`` async
    que devuelve un :class:`ScenarioResult`.
    """

    #: ID estable, p.ej. ``"POC-VMS-01"``.
    id: ClassVar[str] = ""
    #: Nombre corto humano (1 línea).
    name: ClassVar[str] = ""
    #: Descripción larga (puede ser multi-línea).
    description: ClassVar[str] = ""
    #: ``AUTOMATIC`` o ``REQUIRES_PHYSICAL``.
    execution_mode: ClassVar[ExecutionMode] = EXEC_AUTOMATIC
    #: Si ``True``, el runner exige el doble gate antes de instanciar cliente.
    requires_write: ClassVar[bool] = False

    @abstractmethod
    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        """Ejecutar el scenario. Devuelve el veredicto."""
        raise NotImplementedError

# ---------------------------------------------------------------------------
# Helpers de serialización / paths
# ---------------------------------------------------------------------------

def utc_iso() -> str:
    """Timestamp UTC ISO-8601 con milisegundos y sufijo ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_filename_ts() -> str:
    """Timestamp UTC seguro para nombre de archivo (sin ``:``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def safe_value(v: Any) -> Any:
    """Coerce a value into something JSON-serializable.

    pysnmp expone tipos opacos; el JsonlSink ya tiene ``default=str`` pero
    preferimos un render explícito (``prettyPrint`` u hex) acá para que el
    JSONL no quede lleno de ``<OctetString hexValue ...>`` u objetos repr.
    """
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [safe_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): safe_value(x) for k, x in v.items()}
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("ascii")
        except Exception:
            return bytes(v).hex().upper()
    pp = getattr(v, "prettyPrint", None)
    if callable(pp):
        try:
            return pp()
        except Exception:
            pass
    return str(v)


def evidence_path(
    family: str,
    scenario_id: str,
    device_name: str,
    *,
    directory: str = "evidence",
    run_ts: Optional[str] = None,
) -> str:
    """Ruta canónica de evidencia.

    Layout: ``<dir>/<family>/<device>/<run_ts>/<scenario_id>.jsonl``.

    Si ``run_ts`` no se pasa, se genera uno nuevo con :func:`utc_filename_ts`.
    El runner debería pasar el mismo ``run_ts`` para todos los escenarios de
    una misma corrida — así quedan agrupados bajo la misma carpeta de sesión.
    """
    ts = run_ts or utc_filename_ts()
    folder = os.path.join(directory, family, device_name, ts)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{scenario_id}.jsonl")


def hash_multi(text: str) -> str:
    """SHA-256 hex del MULTI normalizado (UTF-8). Para divergencia."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "EXEC_AUTOMATIC",
    "EXEC_REQUIRES_PHYSICAL",
    "STATUS_PASS",
    "STATUS_FAIL",
    "STATUS_PARTIAL",
    "STATUS_QUIRK",
    "STATUS_BLOCKED",
    "ExecutionMode",
    "ScenarioStatus",
    "SnmpSession",
    "ScenarioResult",
    "ScenarioContext",
    "Scenario",
    "evidence_path",
    "hash_multi",
    "safe_value",
    "utc_iso",
    "utc_filename_ts",
]
