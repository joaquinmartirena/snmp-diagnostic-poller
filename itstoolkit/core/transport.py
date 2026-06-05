"""Contrato de transporte.

Un `Transport` sabe leer y escribir valores contra un dispositivo físico, sin
saber qué significan. Las implementaciones concretas viven en `protocols/`.

Fase 0: contrato vacío. La forma final del contrato (firmas de `get`/`set`,
manejo de bulk, timeouts, etc.) se cierra al migrar el cliente SNMP en Fase 1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Transport(ABC):
    """Contrato mínimo de transporte hacia un dispositivo.

    Las firmas reales (get/set/walk, sincronía vs asincronía, manejo de
    timeouts) se definen al migrar `shared/snmp_client.py` en Fase 1.
    """

    @abstractmethod
    async def close(self) -> None:
        """Liberar recursos del transporte."""
        raise NotImplementedError


class TransportError(Exception):
    """Error genérico de transporte. Las implementaciones derivan errores propios."""


class WriteNotAllowedError(TransportError, PermissionError):
    """Se intentó escribir sin que `WriteGuard` lo permitiera.

    Definido acá porque pertenece al contrato de transporte, aunque la política
    que lo dispara vive en `core.safety`.

    Hereda también de `PermissionError` para conservar la semántica del legacy
    (`shared.snmp_client.WriteNotAllowedError` era un `PermissionError`).
    """

    def __init__(self, message: str = "Escritura no permitida por WriteGuard.", *, point: Any = None) -> None:
        super().__init__(message)
        self.point = point
