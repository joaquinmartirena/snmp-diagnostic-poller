"""Controlador SEMEX C5000 (NTCIP 1202).

Reúne en un único paquete el catálogo de OIDs, los decoders y el adapter,
y registra el adapter en el `device_registry` al importarse.

Es el segundo dispositivo de la arquitectura nueva — su existencia revalidó
que el contrato `DeviceAdapter` escala más allá del VMS.
"""

from itstoolkit.core.device import device_registry

from .adapter import SemexC5000Adapter

device_registry.register(SemexC5000Adapter.family, SemexC5000Adapter)

__all__ = ["SemexC5000Adapter"]
