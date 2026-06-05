"""Implementaciones concretas de transporte.

Cada subpaquete (`snmp/`, y a futuro otros) implementa el contrato `Transport`
de `core/`. Esta capa no conoce dispositivos: sabe cómo se habla físicamente
con un equipo, no qué se le dice.
"""
