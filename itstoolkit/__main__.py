"""Permite ejecutar el paquete con ``python -m itstoolkit ...``.

Útil cuando el paquete no está instalado vía ``pip install -e .`` (en cuyo
caso el entrypoint ``itstoolkit`` declarado en `pyproject.toml` es la vía
canónica).
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
