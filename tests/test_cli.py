"""Tests del CLI: parsing, mapeo legacy → family, resolución end-to-end."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from itstoolkit import cli


# ---------- mapeo legacy ----------------------------------------------------


@pytest.mark.parametrize(
    "legacy_type,expected_family,expected_vendor,expected_label",
    [
        ("VMS_NTCIP1203", "vms_ntcip1203", None, "VMS_NTCIP1203"),
        (
            "VMS_NTCIP1203_DAKTRONICS",
            "vms_ntcip1203",
            "daktronics",
            "VMS_NTCIP1203_DAKTRONICS",
        ),
        (
            "VMS_NTCIP1203_CHAINZONE",
            "vms_ntcip1203",
            "chainzone",
            "VMS_NTCIP1203_CHAINZONE",
        ),
        ("SEMEX_C5000_V1", "semex_c5000", None, "SEMEX_C5000_V1"),
    ],
)
def test_resolve_family_maps_legacy_types(
    legacy_type, expected_family, expected_vendor, expected_label
):
    out = cli._resolve_family({"name": "x", "type": legacy_type, "ip": "1.1.1.1"})
    assert out["family"] == expected_family
    assert out.get("vendor") == expected_vendor
    assert out["type_label"] == expected_label
    # type ya no debe estar — fue consumido.
    assert "type" not in out


def test_resolve_family_passes_through_explicit_family():
    out = cli._resolve_family({"family": "vms_ntcip1203", "name": "x", "ip": "1.1"})
    assert out["family"] == "vms_ntcip1203"


def test_resolve_family_rejects_unknown_type():
    from itstoolkit.core.config import ConfigError

    with pytest.raises(ConfigError):
        cli._resolve_family({"name": "x", "type": "FAKE_DEVICE", "ip": "1.1"})


# ---------- resolución end-to-end ------------------------------------------


def test_resolve_device_config_applies_defaults():
    cli.load_all_adapters()
    raw = {"type": "VMS_NTCIP1203", "name": "p1", "ip": "10.0.0.1"}
    out = cli._resolve_device_config(raw)
    assert out["family"] == "vms_ntcip1203"
    assert out["name"] == "p1"
    assert out["ip"] == "10.0.0.1"
    assert out["port"] == 161
    assert out["community"] == "public"
    assert out["interval_seconds"] == 60.0
    assert out["type_label"] == "VMS_NTCIP1203"


def test_resolve_device_config_yaml_then_cli_overrides():
    cli.load_all_adapters()
    raw = {"type": "VMS_NTCIP1203", "name": "p1", "ip": "10.0.0.1", "port": 1611}
    out = cli._resolve_device_config(raw, cli_overrides={"community": "private"})
    assert out["port"] == 1611  # del YAML
    assert out["community"] == "private"  # del CLI override


def test_load_devices_from_yaml_resolves_all_entries(tmp_path: Path):
    cli.load_all_adapters()
    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            """
            devices:
              - name: vms_a
                type: VMS_NTCIP1203
                ip: 10.0.0.1
                interval_seconds: 30
              - name: semex_b
                type: SEMEX_C5000_V1
                ip: 10.0.0.2
                cycle_interval_seconds: 1
            """
        ),
        encoding="utf-8",
    )
    from itstoolkit.core import config as core_config

    entries = list(core_config.load_yaml_devices(str(p)))
    devices = [cli._resolve_device_config(e) for e in entries]
    assert [d["family"] for d in devices] == ["vms_ntcip1203", "semex_c5000"]
    assert devices[0]["interval_seconds"] == 30.0
    assert devices[1]["cycle_interval_seconds"] == 1.0


# ---------- parser ----------------------------------------------------------


def test_parser_lists_all_subcommands():
    parser = cli.build_parser()
    help_text = parser.format_help()
    for sub in ("monitor", "probe", "discover"):
        assert sub in help_text


def test_main_with_no_args_prints_help_and_returns_zero(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "monitor" in out and "probe" in out and "discover" in out


# ---------- monitor: línea de log construida por el adapter ----------------


def test_vms_monitor_line_matches_legacy_layout():
    """La línea producida por el adapter debe respetar el layout histórico."""
    from itstoolkit.devices.vms_ntcip1203.adapter import _build_line

    config = {
        "name": "dakt",
        "ip": "10.0.0.1",
        "port": 161,
        "type_label": "VMS_NTCIP1203_DAKTRONICS",
    }
    line = _build_line(config, "OK", "CTRL=local(2) SRC=central(8)")
    # Estructura: [ts] DEVICE=... TYPE=... IP=... PORT=... POLL=vms COMM_STATUS=...
    assert "DEVICE=dakt" in line
    assert "TYPE=VMS_NTCIP1203_DAKTRONICS" in line
    assert "IP=10.0.0.1" in line
    assert "PORT=161" in line
    assert "POLL=vms" in line
    assert "COMM_STATUS=OK" in line
    assert "CTRL=local(2)" in line


def test_semex_monitor_lines_have_two_polls():
    """SEMEX emite dos polls distintos: alarm y cycle."""
    from itstoolkit.devices.semex_c5000.adapter import _build_line

    config = {"name": "s", "ip": "10.0.0.2", "port": 161}
    alarm = _build_line(config, "alarm", "OK", "ALARM1=none")
    cycle = _build_line(config, "cycle", "OK", "PHASES=...")
    assert "POLL=alarm" in alarm
    assert "POLL=cycle" in cycle
    assert "TYPE=SEMEX_C5000_V1" in alarm
