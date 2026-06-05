"""Modo `probe` — lectura puntual one-shot.

A diferencia de `monitor`, no hay loop ni sink: el adapter responde con un
dict del estado actual y el llamador decide cómo presentarlo. Útil para
diagnóstico rápido desde la línea de comandos o para tests.
"""

from __future__ import annotations

from typing import Any, Mapping

from itstoolkit.core.device import device_registry


async def run_probe(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Probar un único dispositivo y devolver el dict de estado del adapter."""
    family = config.get("family")
    if not family:
        raise ValueError("El config del probe no declara 'family'.")
    adapter_cls = device_registry.get(family)
    adapter = adapter_cls()
    return await adapter.probe(config)


__all__ = ["run_probe"]
