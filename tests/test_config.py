"""Tests de la cascada de config (`core.config`)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from itstoolkit.core import config as cfg


SCHEMA = {
    "ip": {"type": str, "required": True, "prompt": "IP: "},
    "port": {"type": int, "default": 161, "prompt": "Port: "},
    "community": {"type": str, "default": "public", "prompt": "Comm: "},
    "interval_seconds": {"type": float, "default": 60.0},
    "verbose": {"type": bool, "default": False},
}


# ---------- cascada base ----------------------------------------------------


def test_resolve_uses_defaults_when_no_source_provides_value():
    out = cfg.resolve(SCHEMA, [{"ip": "10.0.0.1"}])
    assert out["ip"] == "10.0.0.1"
    assert out["port"] == 161
    assert out["community"] == "public"
    assert out["interval_seconds"] == 60.0
    assert out["verbose"] is False


def test_later_sources_override_earlier():
    defaults = {}
    yaml_ = {"ip": "10.0.0.1", "port": 161}
    env_ = {"port": "9000"}
    cli_ = {"community": "private"}
    out = cfg.resolve(SCHEMA, [defaults, yaml_, env_, cli_])
    assert out["ip"] == "10.0.0.1"
    assert out["port"] == 9000  # env piso a yaml
    assert out["community"] == "private"  # cli piso a default


def test_required_missing_raises_when_no_prompter():
    with pytest.raises(cfg.ConfigError):
        cfg.resolve(SCHEMA, [{}])


def test_prompter_only_runs_for_unresolved_keys():
    calls: list[str] = []

    def prompter(key, spec):
        calls.append(key)
        return "10.1.2.3" if key == "ip" else None

    out = cfg.resolve(SCHEMA, [{}], prompter=prompter)
    assert out["ip"] == "10.1.2.3"
    # No debe prompt para keys con default ya resuelto.
    assert calls == ["ip"]


def test_coercion_applies():
    out = cfg.resolve(SCHEMA, [{"ip": "1.1.1.1", "port": "8080", "verbose": "true"}])
    assert out["port"] == 8080
    assert isinstance(out["port"], int)
    assert out["verbose"] is True


def test_coercion_bool_accepts_natural_strings():
    for s, want in [("true", True), ("False", False), ("yes", True), ("0", False)]:
        out = cfg.resolve(SCHEMA, [{"ip": "x", "verbose": s}])
        assert out["verbose"] is want


def test_coercion_failure_raises_configerror():
    with pytest.raises(cfg.ConfigError):
        cfg.resolve(SCHEMA, [{"ip": "x", "port": "no-soy-int"}])


def test_empty_strings_dont_override():
    """Un valor de '' o None en una fuente no pisa al anterior."""
    out = cfg.resolve(
        SCHEMA, [{"ip": "10.0.0.1", "community": "private"}, {"community": ""}]
    )
    assert out["community"] == "private"


# ---------- sources prefabricados -------------------------------------------


def test_from_env_picks_prefix_keys():
    env = {"ITSTOOLKIT_IP": "10.9.9.9", "OTHER": "noise", "ITSTOOLKIT_PORT": "8161"}
    out = cfg.from_env(SCHEMA, prefix="ITSTOOLKIT_", env=env)
    assert out == {"ip": "10.9.9.9", "port": "8161"}


def test_load_yaml_devices(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            """
            devices:
              - name: a
                ip: 10.0.0.1
              - name: b
                ip: 10.0.0.2
            """
        ),
        encoding="utf-8",
    )
    devices = list(cfg.load_yaml_devices(str(p)))
    assert [d["name"] for d in devices] == ["a", "b"]


def test_load_yaml_devices_rejects_empty_list(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("devices: []", encoding="utf-8")
    with pytest.raises(cfg.ConfigError):
        list(cfg.load_yaml_devices(str(p)))


def test_load_yaml_devices_rejects_missing_devices_key(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("other: 1", encoding="utf-8")
    with pytest.raises(cfg.ConfigError):
        list(cfg.load_yaml_devices(str(p)))
