"""Contrato de dispositivo y registry.

Un `DeviceAdapter` reúne el conocimiento de una familia de dispositivos: su
catálogo de puntos, sus decoders y su esquema de config. Cada paquete en
`devices/<familia>/` registra su adapter contra el `device_registry` global.

Contrato mínimo en Fase 3:

- ``family``: identificador estable (`"vms_ntcip1203"`, `"semex_c5000"`).
- ``config_schema()``: declara las claves que necesita el dispositivo para
    funcionar, con tipo, default y prompt. La cascada de `core.config` lo
    consume para resolver la config efectiva.
- ``monitor_tasks(config, sink)``: devuelve una lista de ``asyncio.Task`` que
    ejecutan el modo monitor. Un VMS devuelve una tarea (poll del estado);
    un SEMEX devuelve dos (alarm + cycle).
- ``probe(config)``: lectura puntual one-shot. Devuelve un dict con el estado
    actual del dispositivo, sin loop ni escritura a sink.

Si el dispositivo expone capacidades que el contrato no contempla (p. ej. un
walk de OIDs para el modo `discover`), se incorporan al ABC cuando hace falta,
no antes.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Mapping, Sequence, Type

from .evidence import EvidenceSink

if TYPE_CHECKING:  # pragma: no cover - solo para type hints
    from .scenario import Scenario


class DeviceAdapter(ABC):
    """Contrato de un adapter de dispositivo.

    Las subclases viven bajo `itstoolkit.devices.<familia>` y se registran en
    `device_registry` al importar el paquete.
    """

    #: Identificador estable de la familia (en minúsculas, snake_case).
    family: str = ""

    @abstractmethod
    def config_schema(self) -> Mapping[str, Mapping[str, Any]]:
        """Declarar las claves de config que este dispositivo necesita.

        Cada clave mapea a un spec con:

        - ``type``: callable de coerción (``int``, ``float``, ``str``, ``bool``).
        - ``default``: valor si la cascada no resuelve nada (opcional).
        - ``required``: si es ``True`` y no hay default ni valor resuelto, se fuerza el prompt o se lanza error.
        - ``prompt``: texto del prompt interactivo.
        - ``description``: documentación corta (opcional).
        """
        raise NotImplementedError

    @abstractmethod
    def monitor_tasks(
        self,
        config: Mapping[str, Any],
        sink: EvidenceSink,
    ) -> List[asyncio.Task]:
        """Construir las tareas asyncio del modo `monitor` para este dispositivo."""
        raise NotImplementedError

    @abstractmethod
    async def probe(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        """Hacer una lectura puntual del estado del dispositivo."""
        raise NotImplementedError

    # -- escenarios PoC (Fase 5) -------------------------------------------
    # No abstracto: un adapter que no tiene escenarios todavía hereda la lista
    # vacía y sigue siendo un DeviceAdapter válido. Los adapters con
    # escenarios (e.g. `vms_ntcip1203`) sobreescriben el método y devuelven
    # instancias listas para ejecutar.
    def scenarios(self) -> Sequence["Scenario"]:
        """Lista de escenarios PoC expuestos por este adapter (orden de declaración)."""
        return ()


class DeviceRegistry:
    """Registro global de adapters por nombre de familia.

    Cada paquete `devices/<familia>/__init__.py` se registra al importarse.
    El CLI y los modos descubren adapters consultando este registry, sin
    imports duros.
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, Type[DeviceAdapter]] = {}

    def register(self, family: str, adapter_cls: Type[DeviceAdapter]) -> None:
        if family in self._adapters:
            raise ValueError(f"Adapter ya registrado para familia '{family}'.")
        self._adapters[family] = adapter_cls

    def get(self, family: str) -> Type[DeviceAdapter]:
        if family not in self._adapters:
            valid = ", ".join(sorted(self._adapters)) or "(ninguna)"
            raise KeyError(
                f"No hay adapter registrado para familia '{family}'. "
                f"Familias registradas: {valid}"
            )
        return self._adapters[family]

    def families(self) -> Iterator[str]:
        return iter(self._adapters)


#: Registry global. Importable desde los paquetes de `devices/`.
device_registry = DeviceRegistry()
