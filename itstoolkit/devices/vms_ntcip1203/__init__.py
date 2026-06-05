"""VMS / DMS NTCIP 1203 v3.

Reúne en un único paquete el catálogo de OIDs (`oids.py`), los decoders
(`decoders.py`) y el adapter (`adapter.py`). Al importarse, registra el
adapter en el `device_registry` global del núcleo.

La distinción Daktronics/Chainzone histórica se reduce a un campo opcional
``vendor`` y a la posibilidad de preservar el ``type_label`` en el log
(``VMS_NTCIP1203`` vs ``VMS_NTCIP1203_DAKTRONICS``) sin duplicar adapter.
"""

from itstoolkit.core.device import device_registry

from .adapter import VmsNtcip1203Adapter

device_registry.register(VmsNtcip1203Adapter.family, VmsNtcip1203Adapter)

__all__ = ["VmsNtcip1203Adapter"]
