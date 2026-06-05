"""Modelo de evidencia y sinks (Fase 2).

Toda salida del toolkit —logs operativos del monitor, JSONL de escenarios,
reportes a futuro— se modela como un `EvidenceRecord` que un `EvidenceSink`
decide cómo materializar. Logs y JSONL son sinks distintos sobre el mismo
modelo, no pipelines separados.

Compatibilidad Fase 2:
- Los helpers planos (`now_ts`, `get_log_path`, `write_log`, `emit`) se
    conservan en este módulo y se re-exportan desde el shim
    `shared/evidence_writer.py`. El poller legacy los sigue usando sin cambio.
- `LineLogSink` puede inicializarse con un `path` fijo o con la fábrica
    `LineLogSink.daily(device_name, ip, directory)` que replica la rotación
    diaria por fecha en el nombre de archivo del poller legacy.
- `EvidenceRecord.raw_line` permite construir un record cuya representación
    textual ya viene pre-renderizada por el legacy (`build_common_prefix +
    append_changes` en `polling/common.py`), garantizando bit-exact con el
    formato actual. Fase 3 pasará a construir records a partir de `fields` y
    dejará `raw_line` para casos puntuales.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Helpers planos (compat legacy — mismo formato byte-a-byte)
# ---------------------------------------------------------------------------

def now_ts() -> str:
    """Timestamp ``YYYY-MM-DD HH:MM:SS`` en hora local. Formato del poller legacy."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_log_path(device_name: str, ip: str, directory: str = "logs") -> str:
    """Construir la ruta del log con rotación diaria por fecha en el nombre."""
    os.makedirs(directory, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(directory, f"{device_name}_{ip}_{date_str}.log")

def write_log(path: str, line: str) -> None:
    """Append una línea al archivo. Crea el archivo si no existe."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def emit(path: str, line: str) -> None:
    """Print a stdout y append al log. Comportamiento histórico del poller."""
    print(line)
    write_log(path, line)

# ---------------------------------------------------------------------------
# Detección de cambios entre snapshots (agnóstico de dispositivo)
# ---------------------------------------------------------------------------

def detect_changes(
    prev: Mapping[str, Any],
    current: Mapping[str, Any],
    keys: Iterable[str],
    labels: Mapping[str, str],
    *,
    quoted: Iterable[str] = (),
) -> list[str]:
    """Detectar cambios entre dos snapshots de estado.

    Solo reporta claves presentes en ``prev`` (evita falsos cambios en el
    primer poll después del arranque, cuando ``prev`` aún está vacío).
    """
    quoted_set = set(quoted)
    changes: list[str] = []
    for k in keys:
        pv = prev.get(k)
        cv = current.get(k)
        if pv is not None and pv != cv:
            if k in quoted_set:
                changes.append(f'{labels[k]}:"{pv}"->"{cv}"')
            else:
                changes.append(f"{labels[k]}:{pv}->{cv}")
    return changes

# ---------------------------------------------------------------------------
# Modelo de evidencia
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRecord:
    """Registro genérico de evidencia.

    Diseñado para representar tanto líneas de monitor (`COMM_STATUS`,
    cambios entre polls) como pasos de escenario (operación SNMP, resultado).

    Atributos:

    - ``timestamp``: string ya formateado por el productor (en general, salida
        de :func:`now_ts`). Es texto, no ``datetime``, para no perder el formato
        exacto cuando el sink solo concatena strings.
    - ``fields``: mapping ordenado de ``KEY=VAL`` que `LineLogSink` renderiza
        en orden de inserción. El productor controla el orden.
    - ``changes``: lista de cambios detectados respecto del poll anterior;
        LineLogSink` los emite como ``CHANGE=k1:a->b;k2:c->d``.
    - ``payload``: datos estructurados extra para JSONL (no se renderizan en
        a línea horizontal).
    - ``raw_line``: cuando viene seteado, `LineLogSink` lo escribe verbatim e
        ignora ``fields`` / ``changes``. Es el puente bit-exact con el formato
        del poller legacy durante Fase 2-3.
    """

    timestamp: str = ""
    fields: Mapping[str, Any] = field(default_factory=dict)
    changes: Sequence[str] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    raw_line: Optional[str] = None


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


class EvidenceSink(ABC):
    """Contrato de un destino de evidencia."""

    @abstractmethod
    def write(self, record: EvidenceRecord) -> None:
        """Persistir un registro."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Liberar recursos (handles de archivo, buffers)."""
        raise NotImplementedError

    # API contextual estándar — útil para `with LineLogSink(...) as sink:`.
    def __enter__(self) -> "EvidenceSink":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


PathProvider = Callable[[], str]


class LineLogSink(EvidenceSink):
    """Sink que escribe una línea horizontal por record.

    Dos modos de uso:

    - **Path fijo**: ``LineLogSink("logs/foo.log")``. Útil para tests y
        escenarios que viven en un único archivo.
    - **Rotación diaria por dispositivo**: ``LineLogSink.daily(name, ip)``
        reproduce la convención del poller legacy
        (``logs/<name>_<ip>_<YYYY-MM-DD>.log``), recomputando la fecha en cada
        write para que el rollover de medianoche funcione sin intervención.

    Si el record trae ``raw_line``, se escribe verbatim — preserva el formato
    histórico bit-exact. Si no, se reconstruye como
    ``[ts] KEY=VAL ... CHANGE=...`` con el mismo separador y orden que usaba
    el poller.
    """

    def __init__(
        self,
        path: "str | PathProvider",
        *,
        echo_stdout: bool = False,
    ) -> None:
        if callable(path):
            self._path_provider: PathProvider = path
        else:
            fixed = str(path)
            self._path_provider = lambda: fixed
        self.echo_stdout = bool(echo_stdout)

    @classmethod
    def daily(
        cls,
        device_name: str,
        ip: str,
        directory: str = "logs",
        *,
        echo_stdout: bool = False,
    ) -> "LineLogSink":
        """Sink con rotación diaria — equivalente al `emit(get_log_path(...))` legacy."""
        return cls(
            lambda: get_log_path(device_name, ip, directory),
            echo_stdout=echo_stdout,
        )

    def write(self, record: EvidenceRecord) -> None:
        line = self._render(record)
        path = self._path_provider()
        if self.echo_stdout:
            emit(path, line)
        else:
            write_log(path, line)

    def close(self) -> None:
        # Sin handle abierto: write_log abre/cierra por llamada.
        return None

    # -- rendering ----------------------------------------------------------
    @staticmethod
    def _render(record: EvidenceRecord) -> str:
        if record.raw_line is not None:
            return record.raw_line
        parts: list[str] = []
        if record.timestamp:
            parts.append(f"[{record.timestamp}]")
        for k, v in record.fields.items():
            parts.append(f"{k}={v}")
        line = " ".join(parts)
        if record.changes:
            line = line + " CHANGE=" + ";".join(record.changes)
        return line


class JsonlSink(EvidenceSink):
    """Sink que escribe un objeto JSON por línea.

    Pensado para evidencia estructurada de escenarios (Fase 5). En Fase 2 vive
    acá con tests propios pero **sin integrarse aún a escenarios** — los
    escenarios PoC son Fase 5.
    """

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        # Abrimos en append y mantenemos el handle vivo: una corrida de
        # escenario puede emitir cientos de records y abrir/cerrar por línea
        # introduce latencia innecesaria.
        self._fh = open(path, "a", encoding="utf-8")
        self.path = path

    def write(self, record: EvidenceRecord) -> None:
        obj = {
            "ts": record.timestamp,
            "fields": dict(record.fields),
            "changes": list(record.changes),
            "payload": dict(record.payload),
        }
        # `default=str` evita que objetos pysnmp u otros opacos rompan json.
        self._fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


__all__ = [
    # Helpers planos (compat legacy)
    "now_ts",
    "get_log_path",
    "write_log",
    "emit",
    "detect_changes",
    # Modelo + sinks
    "EvidenceRecord",
    "EvidenceSink",
    "LineLogSink",
    "JsonlSink",
]
