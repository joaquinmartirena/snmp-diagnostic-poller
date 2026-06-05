"""Núcleo agnóstico del toolkit.

Contiene los contratos (`Transport`, `DeviceAdapter`), la política de seguridad
de escritura (`WriteGuard`), el modelo de evidencia y la resolución de config.

Invariante: `core/` no conoce dispositivos ni protocolos concretos. Si en este
paquete aparece la palabra "OID", "SNMP" o "VMS", algo está mal ubicado.
"""
