"""Paquetes por familia de dispositivo.

Cada subpaquete reúne todo el conocimiento de una familia: catálogo de puntos
(`oids.py`), decoders (`decoders.py`), adapter (`adapter.py`) y escenarios
(`scenarios/`). Agregar un dispositivo nuevo es agregar un paquete acá —
sin tocar `core/`, `modes/` ni el CLI.

`load_all_adapters()` importa todos los subpaquetes para que sus adapters
queden registrados en `core.device.device_registry`. El CLI lo llama una vez
al inicio. Tests que necesiten todos los adapters lo invocan también.
"""

from __future__ import annotations

import importlib
import pkgutil


def load_all_adapters() -> list[str]:
    """Importar todos los subpaquetes de `devices/` y devolver sus nombres.

    Cada subpaquete tiene que registrar su adapter en el `device_registry` en
    su `__init__.py`. El orden de carga es el orden alfabético de los nombres.
    """
    loaded: list[str] = []
    for info in pkgutil.iter_modules(__path__):
        if not info.ispkg:
            continue
        importlib.import_module(f"{__name__}.{info.name}")
        loaded.append(info.name)
    return loaded


__all__ = ["load_all_adapters"]
