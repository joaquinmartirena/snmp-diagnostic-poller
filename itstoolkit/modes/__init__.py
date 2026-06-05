"""Modos de uso: los verbos del CLI.

`monitor`, `probe`, `discover` y `scenario` son clientes delgados del núcleo:
combinan un `DeviceAdapter`, un `Transport` y el modelo de evidencia, sin
contener OIDs, decoders ni conocimiento de protocolo.
"""
