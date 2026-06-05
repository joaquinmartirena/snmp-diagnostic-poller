"""Tests de layering — protegen las invariantes arquitectónicas.

Reglas que se verifican (ver `tool_kit_estructure.md`, §7):

- `core/` no conoce dispositivos ni protocolos concretos.
- `protocols/` no conoce dispositivos.
- `devices/` no importa de `modes/`.
- Nada nuevo puede aparecer en paquetes legacy fantasmas (`shared/`,
  `polling/`, `pocs/`) — fueron eliminados en Fase 7.

Estas pruebas se endurecen progresivamente: arrancaron muy laxas en Fase 0
y, una vez completada la migración, todas las invariantes principales del
documento de arquitectura están protegidas acá.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "itstoolkit"

#: Paquetes legacy que ya no deben existir en el repo y que el código nuevo
#: nunca debe importar. Si reaparecen, algo se está restaurando por error.
FORBIDDEN_LEGACY = {"shared", "polling", "pocs"}


# ---------- helpers ---------------------------------------------------------


def _iter_modules(subpath: str):
    """Iterar archivos .py bajo itstoolkit/<subpath>/."""
    base = PKG / subpath
    if not base.exists():
        return
    for py in base.rglob("*.py"):
        yield py


def _imports_in(file: Path) -> list[str]:
    """Devolver los módulos importados (tope) en un archivo, vía AST."""
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                # Reconstruir el módulo absoluto cuando es posible.
                if node.level == 0:
                    names.append(node.module)
                else:
                    # Import relativo: lo dejamos como el nombre nominal para no
                    # disparar falsos positivos contra paquetes legacy.
                    names.append(node.module)
    return names


def _forbidden(imports: list[str], banned_prefixes: tuple[str, ...]) -> list[str]:
    return [imp for imp in imports if any(imp == p or imp.startswith(p + ".") for p in banned_prefixes)]


# ---------- existencia de la estructura ------------------------------------


def test_package_imports_cleanly():
    """El paquete raíz debe importarse sin errores."""
    mod = importlib.import_module("itstoolkit")
    assert hasattr(mod, "__version__")


@pytest.mark.parametrize(
    "module",
    [
        "itstoolkit.core",
        "itstoolkit.core.transport",
        "itstoolkit.core.device",
        "itstoolkit.core.safety",
        "itstoolkit.core.evidence",
        "itstoolkit.core.config",
        "itstoolkit.protocols",
        "itstoolkit.protocols.snmp",
        "itstoolkit.devices",
        "itstoolkit.devices.vms_ntcip1203",
        "itstoolkit.devices.vms_ntcip1203.scenarios",
        "itstoolkit.devices.semex_c5000",
        "itstoolkit.modes",
        "itstoolkit.cli",
    ],
)
def test_layer_modules_exist(module):
    """Todos los módulos de la arquitectura objetivo deben existir e importar."""
    importlib.import_module(module)


# ---------- invariantes de imports -----------------------------------------


def test_core_does_not_know_about_protocols_or_devices():
    """`core/` no debe importar de `protocols/`, `devices/` ni `modes/`."""
    banned = ("itstoolkit.protocols", "itstoolkit.devices", "itstoolkit.modes")
    offenders: dict[str, list[str]] = {}
    for f in _iter_modules("core"):
        bad = _forbidden(_imports_in(f), banned)
        if bad:
            offenders[str(f.relative_to(ROOT))] = bad
    assert not offenders, f"core/ no debe importar de capas externas: {offenders}"


def test_protocols_do_not_know_about_devices_or_modes():
    """`protocols/` no debe importar de `devices/` ni `modes/`."""
    banned = ("itstoolkit.devices", "itstoolkit.modes")
    offenders: dict[str, list[str]] = {}
    for f in _iter_modules("protocols"):
        bad = _forbidden(_imports_in(f), banned)
        if bad:
            offenders[str(f.relative_to(ROOT))] = bad
    assert not offenders, f"protocols/ no debe importar de devices/ ni modes/: {offenders}"


def test_devices_do_not_import_modes():
    """`devices/` no debe importar de `modes/` (la dependencia va al revés)."""
    banned = ("itstoolkit.modes",)
    offenders: dict[str, list[str]] = {}
    for f in _iter_modules("devices"):
        bad = _forbidden(_imports_in(f), banned)
        if bad:
            offenders[str(f.relative_to(ROOT))] = bad
    assert not offenders, f"devices/ no debe importar de modes/: {offenders}"


def test_no_imports_from_eliminated_legacy():
    """Ningún módulo puede importar de paquetes legacy ya eliminados.

    Si alguien intenta restaurar `shared/`, `polling/` o `pocs/`, este test
    falla apuntando al archivo ofensor.
    """
    banned = tuple(FORBIDDEN_LEGACY)
    offenders: dict[str, list[str]] = {}
    for f in PKG.rglob("*.py"):
        bad = _forbidden(_imports_in(f), banned)
        if bad:
            offenders[str(f.relative_to(ROOT))] = bad
    assert not offenders, (
        f"Imports prohibidos a {FORBIDDEN_LEGACY}: {offenders}"
    )


def test_legacy_packages_do_not_exist_on_disk():
    """Los directorios legacy fueron eliminados en Fase 7."""
    for pkg in FORBIDDEN_LEGACY:
        assert not (ROOT / pkg).exists(), (
            f"El paquete legacy '{pkg}/' debería haber sido eliminado en Fase 7."
        )
