"""Política de seguridad de escritura.

Toda escritura a un dispositivo de campo pasa por un `WriteGuard` que aplica
el doble gate: `confirm_write=True` en la config + flag `--confirm-write` en
el CLI. No existe ruta de escritura que evite este componente.

Modos:

- **Read-only.** Sin doble gate: cualquier intento de escritura lanza
    `WriteNotAllowedError`. Es el modo por defecto. El poller y los escenarios
    read-only operan acá.
- **Dry-run.** Doble gate activo + `dry_run=True`: la escritura se autoriza
    pero el transporte la registra sin ejecutarla. Útil para validar payloads
    contra paneles productivos.
- **Live write.** Doble gate activo + `dry_run=False`: la escritura se ejecuta
  efectivamente. Solo se alcanza cuando *ambas* mitades del gate están puestas.

Compatibilidad con Fase 1: el `SnmpClient` legacy expone `allow_write=False/True`.
El cliente migrado mapea ese booleano internamente a un `WriteGuard`
(`DoubleGateWriteGuard.read_only()` o `DoubleGateWriteGuard.unsafe_allow_write()`),
preservando la firma del legacy mientras la política vive ya en el núcleo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .transport import WriteNotAllowedError


class WriteGuard(ABC):
    """Contrato del guard de escritura.

    Las implementaciones concretas exponen `allow_write` y `dry_run` como
    atributos (booleanos). Solo `assert_can_write` es abstracto: cómo se
    decide la autorización es responsabilidad de la implementación.
    """

    #: Si el guard autoriza alguna forma de escritura (live o dry-run).
    allow_write: bool = False
    #: Si las escrituras autorizadas deben ejecutarse en seco.
    dry_run: bool = False

    @abstractmethod
    def assert_can_write(self, point: Any = None) -> None:
        """Lanzar `WriteNotAllowedError` si la escritura no está autorizada."""
        raise NotImplementedError


@dataclass(frozen=True)
class DoubleGateWriteGuard(WriteGuard):
    """Guard estándar: doble confirmación (config + CLI) más dry-run opcional.

    - `config_confirmed`: viene de `confirm_write: true` en la config.
    - `cli_confirmed`:    viene de `--confirm-write` en el CLI.
    - `dry_run`:          si está, la escritura se autoriza pero el transporte
        la registra sin ejecutarla. No relaja el doble gate: ambas mitades
        tienen que estar puestas igual.
    """

    config_confirmed: bool = False
    cli_confirmed: bool = False
    dry_run: bool = False

    @property
    def allow_write(self) -> bool:  # type: ignore[override]
        return bool(self.config_confirmed and self.cli_confirmed)

    def assert_can_write(self, point: Any = None) -> None:
        if self.allow_write:
            return
        missing = []
        if not self.config_confirmed:
            missing.append("confirm_write=true en config")
        if not self.cli_confirmed:
            missing.append("--confirm-write en CLI")
        raise WriteNotAllowedError(
            f"Escritura no permitida: falta {' + '.join(missing)}.",
            point=point,
        )

    # -- factorías ----------------------------------------------------------
    @classmethod
    def read_only(cls) -> "DoubleGateWriteGuard":
        """Guard sin escritura posible (modo por defecto)."""
        return cls(config_confirmed=False, cli_confirmed=False, dry_run=False)

    @classmethod
    def from_flags(
        cls,
        *,
        config_confirmed: bool,
        cli_confirmed: bool,
        dry_run: bool = False,
    ) -> "DoubleGateWriteGuard":
        return cls(
            config_confirmed=bool(config_confirmed),
            cli_confirmed=bool(cli_confirmed),
            dry_run=bool(dry_run),
        )

    @classmethod
    def unsafe_allow_write(cls, *, dry_run: bool = False) -> "DoubleGateWriteGuard":
        """Construir un guard con ambas mitades del gate ya confirmadas.

        Pensado para compatibilidad con `SnmpClient(allow_write=True)` del
        legacy y para tests. No usar en código de producción nuevo: el CLI
        debe construir el guard a partir de las flags reales.
        """
        return cls(config_confirmed=True, cli_confirmed=True, dry_run=bool(dry_run))


__all__ = [
    "WriteGuard",
    "DoubleGateWriteGuard",
    "WriteNotAllowedError",
]
