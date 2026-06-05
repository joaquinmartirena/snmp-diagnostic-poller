"""CLI único del toolkit.

Subcomandos:

- ``monitor``: lectura repetida (diagnóstico continuo). Reemplaza al antiguo
  `diag_poller.py`. Soporta multi-dispositivo vía YAML o un único dispositivo
  vía flags / prompt interactivo.
- ``probe``: lectura puntual one-shot.
- ``discover``: walk SNMP desde un OID base.
- ``scenario``: enumera (``list``) o ejecuta (``run``) los escenarios PoC
  expuestos por el adapter de cada familia. ``run`` aplica el doble gate de
  WriteGuard (`confirm_write` en config + `--confirm-write` en CLI) antes
  de instanciar el cliente SNMP.

La resolución de config sigue una **única** cascada
(``defaults → YAML → env → flags → prompt``) implementada en
:mod:`itstoolkit.core.config`. No hay bifurcación
``if args.config: ... else: prompt``: el prompt es la última etapa de la
misma cascada y solo se activa cuando faltan claves requeridas.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import __version__
from .core import config as core_config
from .core.device import device_registry
from .devices import load_all_adapters
from .modes import discover as discover_mode
from .modes import monitor as monitor_mode
from .modes import probe as probe_mode
from .modes import scenario as scenario_mode


# ---------------------------------------------------------------------------
# Mapping de los `type:` históricos del YAML legacy al `family` interno
# ---------------------------------------------------------------------------

#: Por cada `type:` del YAML legacy, indica (family, vendor, type_label).
#: Mantiene la distinción Daktronics/Chainzone como metadata (vendor) y
#: preserva el ``TYPE=`` del log line histórico vía ``type_label``.
LEGACY_TYPE_MAP: Dict[str, Dict[str, Optional[str]]] = {
    "VMS_NTCIP1203": {
        "family": "vms_ntcip1203",
        "vendor": None,
        "type_label": "VMS_NTCIP1203",
    },
    "VMS_NTCIP1203_DAKTRONICS": {
        "family": "vms_ntcip1203",
        "vendor": "daktronics",
        "type_label": "VMS_NTCIP1203_DAKTRONICS",
    },
    "VMS_NTCIP1203_CHAINZONE": {
        "family": "vms_ntcip1203",
        "vendor": "chainzone",
        "type_label": "VMS_NTCIP1203_CHAINZONE",
    },
    "SEMEX_C5000_V1": {
        "family": "semex_c5000",
        "vendor": None,
        "type_label": "SEMEX_C5000_V1",
    },
}


def _resolve_family(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Aplicar el mapping legacy y devolver un dict con 'family' poblado.

    Si el YAML ya trae 'family', se usa tal cual. Si trae 'type', se mapea
    al family correspondiente. Esto permite que YAMLs viejos (con `type:`)
    sigan funcionando sin migración manual.
    """
    out = dict(raw)
    if "family" in out and out["family"]:
        return out
    legacy_type = out.pop("type", None)
    if legacy_type and legacy_type in LEGACY_TYPE_MAP:
        meta = LEGACY_TYPE_MAP[legacy_type]
        out.setdefault("family", meta["family"])
        if meta.get("vendor") is not None:
            out.setdefault("vendor", meta["vendor"])
        out.setdefault("type_label", meta["type_label"])
    elif legacy_type:
        raise core_config.ConfigError(
            f"type '{legacy_type}' desconocido. "
            f"Conocidos: {sorted(LEGACY_TYPE_MAP)}."
        )
    return out


def _resolve_device_config(
    raw_yaml_entry: Mapping[str, Any],
    *,
    cli_overrides: Optional[Mapping[str, Any]] = None,
    prompter: Optional[core_config.Prompter] = None,
) -> Dict[str, Any]:
    """Pasar un device por la cascada usando el schema de su adapter."""
    entry = _resolve_family(raw_yaml_entry)
    family = entry.get("family")
    if not family:
        raise core_config.ConfigError(
            "Device sin 'family' ni 'type' reconocible: " + repr(raw_yaml_entry)
        )

    adapter_cls = device_registry.get(family)
    schema = adapter_cls().config_schema()

    sources: List[Mapping[str, Any]] = [
        entry,  # YAML (ya con family resuelta)
        core_config.from_env(schema),
        cli_overrides or {},
    ]
    resolved = core_config.resolve(schema, sources, prompter=prompter)
    resolved["family"] = family
    return resolved


# ---------------------------------------------------------------------------
# Subcomando: monitor
# ---------------------------------------------------------------------------


def _add_common_device_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--family", help="Familia del dispositivo (e.g. vms_ntcip1203).")
    p.add_argument("--name", help="Nombre del panel (para el log).")
    p.add_argument("--ip", help="IP del panel.")
    p.add_argument("--port", type=int, help="Puerto SNMP.")
    p.add_argument("--community", help="SNMP community string.")
    p.add_argument(
        "--interval-seconds",
        type=float,
        dest="interval_seconds",
        help="Intervalo de polling para monitor.",
    )


def _cli_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    """Construir el dict de overrides desde el namespace argparse."""
    out: Dict[str, Any] = {}
    for k in ("name", "ip", "port", "community", "interval_seconds"):
        v = getattr(args, k, None)
        if v is not None:
            out[k] = v
    return out


def _devices_from_args(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Resolver la lista de devices según los args.

    - Si hay ``--config <path>``: lee la lista YAML y aplica cascada a cada uno.
    - Si no: construye un único device desde flags + prompt interactivo.
    """
    if args.config:
        entries = list(core_config.load_yaml_devices(args.config))
        return [_resolve_device_config(e) for e in entries]

    if not args.family:
        # Sin --family no podemos saber qué schema usar; activamos prompt.
        family = (
            input(
                "Familia [vms_ntcip1203] (registradas: "
                + ", ".join(sorted(device_registry.families()))
                + "): "
            ).strip()
            or "vms_ntcip1203"
        )
    else:
        family = args.family

    raw = {"family": family}
    return [
        _resolve_device_config(
            raw,
            cli_overrides=_cli_overrides(args),
            prompter=core_config.interactive_prompter,
        )
    ]


def _describe_device(dev: Mapping[str, Any]) -> str:
    base = f"  - {dev['name']} [{dev.get('type_label', dev['family'])}] {dev['ip']}:{dev['port']}"
    if "interval_seconds" in dev:
        base += f" interval={dev['interval_seconds']}s"
    if "alarm_interval_seconds" in dev:
        base += f" alarm={dev['alarm_interval_seconds']}s"
    if "cycle_interval_seconds" in dev:
        base += f" cycle={dev['cycle_interval_seconds']}s"
    return base


def cmd_monitor(args: argparse.Namespace) -> int:
    devices = _devices_from_args(args)
    print("\nMonitoreando dispositivos (read-only):")
    for d in devices:
        print(_describe_device(d))
    print("Ctrl+C para detener.\n")
    try:
        asyncio.run(monitor_mode.run_monitor(devices))
    except KeyboardInterrupt:
        print("\nDeteniendo monitor...")
    return 0


# ---------------------------------------------------------------------------
# Subcomando: probe
# ---------------------------------------------------------------------------


def cmd_probe(args: argparse.Namespace) -> int:
    devices = _devices_from_args(args)
    if len(devices) != 1:
        print(
            f"[itstoolkit] probe espera un único dispositivo (recibí {len(devices)}).",
            file=sys.stderr,
        )
        return 2
    state = asyncio.run(probe_mode.run_probe(devices[0]))
    print(f"--- probe {devices[0]['name']} [{devices[0]['family']}] ---")
    for k, v in state.items():
        print(f"  {k}: {v}")
    return 0


# ---------------------------------------------------------------------------
# Subcomando: scenario
# ---------------------------------------------------------------------------


def _print_scenarios(items: List[Dict[str, Any]]) -> None:
    if not items:
        print("(sin escenarios registrados)")
        return
    for it in items:
        write_tag = " write" if it.get("requires_write") else ""
        print(
            f"  {it['id']:14} [{it['execution_mode']}]{write_tag}  {it['name']}"
        )
        desc = (it.get("description") or "").strip()
        if desc:
            first_line = desc.splitlines()[0]
            print(f"      {first_line}")


def cmd_scenario(args: argparse.Namespace) -> int:
    action = getattr(args, "scenario_action", None)
    if action is None:
        print(
            "[itstoolkit] scenario requiere un subcomando: 'list' o 'run'.",
            file=sys.stderr,
        )
        return 2

    if action == "list":
        family = args.family or "vms_ntcip1203"
        try:
            items = scenario_mode.list_scenarios(family)
        except KeyError as exc:
            print(f"[itstoolkit] {exc}", file=sys.stderr)
            return 2
        print(f"--- escenarios registrados para family={family} ---")
        _print_scenarios(items)
        return 0

    if action == "run":
        devices = _devices_from_args(args)
        try:
            results = asyncio.run(
                scenario_mode.run_scenarios(
                    devices,
                    scenario_ids=args.scenario or None,
                    automatic_only=bool(args.automatic_only),
                    cli_confirm_write=bool(args.confirm_write),
                )
            )
        except KeyError as exc:
            print(f"[itstoolkit] {exc}", file=sys.stderr)
            return 2

        print(f"--- {len(results)} escenarios ejecutados ---")
        any_fail = False
        any_blocked = False
        for r in results:
            print(f"  {r.scenario_id:14} {r.status:14} {r.summary}")
            if r.evidence_path:
                print(f"      evidence: {r.evidence_path}")
            if r.status == "FAIL":
                any_fail = True
            elif r.status == "BLOCKED":
                any_blocked = True

        if any_fail:
            return 2
        if any_blocked:
            return 1
        return 0

    print(f"[itstoolkit] subcomando scenario desconocido: {action!r}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Subcomando: discover
# ---------------------------------------------------------------------------


def cmd_discover(args: argparse.Namespace) -> int:
    if not args.ip or not args.base_oid:
        print(
            "[itstoolkit] discover requiere --ip y --base-oid.",
            file=sys.stderr,
        )
        return 2
    pairs = asyncio.run(
        discover_mode.run_discover(
            args.ip,
            args.community or "public",
            args.base_oid,
            port=args.port or 161,
            max_oids=args.max_oids,
        )
    )
    print(f"--- discover {args.ip}:{args.port or 161} {args.base_oid} ({len(pairs)} OIDs) ---")
    for oid, val in pairs:
        try:
            pretty = val.prettyPrint()
        except Exception:
            pretty = repr(val)
        print(f"  {oid} = {pretty}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="itstoolkit",
        description="Toolkit de diagnóstico y validación de dispositivos ITS de campo.",
    )
    parser.add_argument(
        "--version", action="version", version=f"itstoolkit {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # monitor
    pm = sub.add_parser("monitor", help="Diagnóstico continuo (loop periódico).")
    pm.add_argument("--config", help="Path a YAML multi-dispositivo.")
    _add_common_device_flags(pm)
    pm.set_defaults(func=cmd_monitor)

    # probe
    pp = sub.add_parser("probe", help="Lectura puntual one-shot.")
    pp.add_argument("--config", help="Path a YAML (se usa el primer device).")
    _add_common_device_flags(pp)
    pp.set_defaults(func=cmd_probe)

    # discover
    pd = sub.add_parser("discover", help="Walk SNMP desde un OID base.")
    pd.add_argument("--ip", required=False, help="IP del dispositivo.")
    pd.add_argument("--port", type=int, default=161)
    pd.add_argument("--community", default="public")
    pd.add_argument("--base-oid", dest="base_oid", help="OID raíz del walk.")
    pd.add_argument("--max-oids", dest="max_oids", type=int, default=200)
    pd.set_defaults(func=cmd_discover)

    # scenario (list / run)
    ps = sub.add_parser(
        "scenario",
        help="Listar o ejecutar escenarios PoC declarados por el adapter.",
    )
    ssub = ps.add_subparsers(dest="scenario_action", metavar="<list|run>")

    psl = ssub.add_parser("list", help="Enumerar escenarios de una familia.")
    psl.add_argument("--family", help="Familia (default: vms_ntcip1203).")
    psl.set_defaults(func=cmd_scenario)

    psr = ssub.add_parser("run", help="Ejecutar escenarios contra el panel.")
    psr.add_argument("--config", help="Path a YAML multi-dispositivo.")
    _add_common_device_flags(psr)
    psr.add_argument(
        "--scenario",
        action="append",
        help="ID de scenario a correr (repetible). Default: todos.",
    )
    psr.add_argument(
        "--automatic-only",
        dest="automatic_only",
        action="store_true",
        help="Correr únicamente escenarios AUTOMATIC (saltea REQUIRES_PHYSICAL).",
    )
    psr.add_argument(
        "--confirm-write",
        dest="confirm_write",
        action="store_true",
        help=(
            "Mitad-CLI del doble gate de WriteGuard. Sin esto, escenarios con "
            "requires_write=True quedan BLOCKED."
        ),
    )
    psr.set_defaults(func=cmd_scenario)

    ps.set_defaults(func=cmd_scenario)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Importa todos los paquetes de devices/ para que registren sus adapters.
    load_all_adapters()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
