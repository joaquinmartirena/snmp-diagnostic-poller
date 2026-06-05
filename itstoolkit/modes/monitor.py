"""Modo `monitor` — lectura repetida (diagnóstico continuo).

Es código de orquestación delgado: descubre el adapter de la familia
configurada en cada device, construye su `LineLogSink` con rotación diaria, y
lanza las tareas asyncio del adapter. No contiene OIDs, decoders ni
conocimiento de protocolo: todo eso vive en `devices/<familia>/`.

Estructura del config de cada device (post-cascada):
    {
        "family": "vms_ntcip1203",     # determina qué adapter usar
        "name": "dakt_001",
        "ip": "10.0.0.10",
        "port": 161,
        "community": "public",
        "interval_seconds": 60.0,
        ...                            # otras claves específicas del adapter
    }
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Mapping, Optional, Sequence

from itstoolkit.core.device import device_registry
from itstoolkit.core.evidence import EvidenceSink, LineLogSink


SinkFactory = Callable[[Mapping[str, Any]], EvidenceSink]


def default_sink_factory(config: Mapping[str, Any]) -> EvidenceSink:
    """Sink default del monitor: log diario por dispositivo, con eco a stdout."""
    return LineLogSink.daily(
        config["name"], config["ip"], directory="logs", echo_stdout=True
    )


async def run_monitor(
    devices: Sequence[Mapping[str, Any]],
    *,
    sink_factory: Optional[SinkFactory] = None,
) -> None:
    """Correr el modo monitor sobre una lista de dispositivos configurados.

    Cada dict de ``devices`` debe traer al menos ``family`` y las claves que
    el adapter de esa familia declara como requeridas. El llamador es
    responsable de haber pasado la cascada de config antes.
    """
    sink_factory = sink_factory or default_sink_factory
    sinks: List[EvidenceSink] = []
    tasks: List[asyncio.Task] = []
    try:
        for dev in devices:
            family = dev.get("family")
            if not family:
                raise ValueError(
                    f"Device {dev.get('name')!r} no declara 'family'."
                )
            adapter_cls = device_registry.get(family)
            adapter = adapter_cls()
            sink = sink_factory(dev)
            sinks.append(sink)
            tasks.extend(adapter.monitor_tasks(dev, sink))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    finally:
        for s in sinks:
            try:
                s.close()
            except Exception:
                pass


__all__ = ["run_monitor", "default_sink_factory", "SinkFactory"]
