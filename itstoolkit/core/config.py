"""Resolución de config en cascada.

La fuente única de verdad para construir la config efectiva es esta cascada:

    defaults  →  YAML  →  variables de entorno  →  flags de CLI  →  prompt

No hay rutas alternativas: el prompt interactivo es la última etapa de la
misma cascada, no una bifurcación (``if args.config: ... else: prompt``).

Cada etapa aporta un ``dict``; las etapas posteriores pisan a las anteriores.
La etapa de prompt solo se activa para claves todavía no resueltas, y solo si
se pasa un ``prompter`` explícito (CLI interactivo). Los modos no-interactivos
nunca prompean: si una clave requerida no se resuelve, lanza ``ConfigError``.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - PyYAML está en pyproject.toml
    yaml = None  # type: ignore[assignment]


Schema = Mapping[str, Mapping[str, Any]]
Prompter = Callable[[str, Mapping[str, Any]], Any]


class ConfigError(ValueError):
    """Error en la resolución de config (clave faltante, tipo inválido, etc.)."""

# ---------------------------------------------------------------------------
# Coerción
# ---------------------------------------------------------------------------

def _coerce(value: Any, type_: Optional[Callable[[Any], Any]], key: str) -> Any:
    if type_ is None or value is None:
        return value
    if type_ is bool and isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "on"):
            return True
        if v in ("false", "0", "no", "n", "off"):
            return False
        raise ConfigError(f"Valor bool inválido para '{key}': {value!r}")
    try:
        return type_(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"No pude convertir '{key}'={value!r} a {type_.__name__}: {exc}"
        ) from exc

# ---------------------------------------------------------------------------
# Cascada
# ---------------------------------------------------------------------------

def resolve(
    schema: Schema,
    sources: Sequence[Mapping[str, Any]],
    *,
    prompter: Optional[Prompter] = None,
) -> Dict[str, Any]:
    """Resolver la config efectiva contra el esquema.
    Args:
        schema: mapping clave → spec (ver `DeviceAdapter.config_schema`).
        sources: secuencia de mappings en orden de prioridad **ascendente**:
            las posteriores pisan a las anteriores. Convención:
            ``[defaults, yaml, env, cli]``.
        prompter: si está, se invoca para cada clave sin valor resuelto.

    Returns:
        Diccionario con todas las claves del schema. Las que no resuelven
        nada y no son required se omiten.

    Raises:
        ConfigError: clave required sin valor, o coerción de tipo fallida.
    """
    out: Dict[str, Any] = {}
    for key, spec in schema.items():
        value: Any = None
        present = False
        for src in sources:
            if key in src and src[key] is not None and src[key] != "":
                value = src[key]
                present = True
        if not present:
            if "default" in spec:
                value = spec["default"]
                present = True
        if not present and prompter is not None:
            value = prompter(key, spec)
            present = value is not None and value != ""
        if not present:
            if spec.get("required"):
                raise ConfigError(f"Falta la clave requerida '{key}'.")
            continue
        out[key] = _coerce(value, spec.get("type"), key)
    return out

# ---------------------------------------------------------------------------
# Sources prefabricados
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> Mapping[str, Any]:
    """Cargar un archivo YAML como dict (vacío si no hay contenido)."""
    if yaml is None:
        raise ConfigError("PyYAML no está instalado")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, Mapping):
        raise ConfigError(f"El YAML en {path!r} no es un mapping.")
    return data


def from_env(
    schema: Schema,
    prefix: str = "ITSTOOLKIT_",
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Construir un dict desde variables de entorno.

    Para cada clave ``foo_bar`` del schema, busca ``<PREFIX>FOO_BAR``.
    """
    env = env if env is not None else os.environ
    out: Dict[str, Any] = {}
    for key in schema:
        env_key = prefix + key.upper()
        if env_key in env:
            out[key] = env[env_key]
    return out


def cli_dict(args: Any, schema: Schema) -> Dict[str, Any]:
    """Extraer del namespace de argparse las claves que matchean el schema."""
    out: Dict[str, Any] = {}
    ns = vars(args) if not isinstance(args, Mapping) else dict(args)
    for key in schema:
        if key in ns and ns[key] is not None:
            out[key] = ns[key]
    return out


def interactive_prompter(key: str, spec: Mapping[str, Any]) -> Any:
    """Prompter por stdin: usa ``spec['prompt']`` y muestra el default si hay."""
    label = spec.get("prompt", f"{key}: ")
    default = spec.get("default")
    if default is not None:
        label = label.rstrip(": ").rstrip() + f" [{default}]: "
    try:
        raw = input(label).strip()
    except EOFError:
        return None
    if not raw:
        return default
    return raw


def load_yaml_devices(path: str) -> Iterable[Mapping[str, Any]]:
    """Cargar la sección ``devices:`` de un YAML multi-dispositivo.

    Convención heredada del legacy: el YAML tiene ``devices: [ {...}, ... ]``.
    """
    data = load_yaml(path)
    devices = data.get("devices")
    if not devices:
        raise ConfigError(f"El YAML {path!r} no tiene una lista 'devices'.")
    if not isinstance(devices, list):
        raise ConfigError(f"'devices' en {path!r} no es una lista.")
    return devices


__all__ = [
    "Schema",
    "Prompter",
    "ConfigError",
    "resolve",
    "load_yaml",
    "load_yaml_devices",
    "from_env",
    "cli_dict",
    "interactive_prompter",
]
