"""Modos de uso: los verbos del CLI.

`monitor`, `probe`, `discover`, `scenario` son clientes delgados del núcleo:
combinan un `DeviceAdapter`, un `Transport` y el modelo de evidencia, sin
contener OIDs, decoders ni conocimiento de protocolo.

Fase 0: paquete vacío. Los módulos concretos se incorporan en fases 3-5.
"""
