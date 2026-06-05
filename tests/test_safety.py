"""Tests del `WriteGuard` (Fase 1).

Validan el doble gate, el dry-run y la compatibilidad de `WriteNotAllowedError`
con `PermissionError` (semántica del legacy).
"""

from __future__ import annotations

import pytest

from itstoolkit.core.safety import DoubleGateWriteGuard, WriteGuard
from itstoolkit.core.transport import WriteNotAllowedError


# ---------- bloqueo sin doble confirmación ----------------------------------


def test_read_only_guard_blocks_write():
    guard = DoubleGateWriteGuard.read_only()
    assert guard.allow_write is False
    assert guard.dry_run is False
    with pytest.raises(WriteNotAllowedError):
        guard.assert_can_write("dmsActivateMessage")


@pytest.mark.parametrize(
    "config_confirmed,cli_confirmed",
    [(False, False), (True, False), (False, True)],
)
def test_partial_confirmation_blocks_write(config_confirmed, cli_confirmed):
    guard = DoubleGateWriteGuard.from_flags(
        config_confirmed=config_confirmed,
        cli_confirmed=cli_confirmed,
    )
    assert guard.allow_write is False
    with pytest.raises(WriteNotAllowedError) as excinfo:
        guard.assert_can_write(point="any")
    msg = str(excinfo.value)
    if not config_confirmed:
        assert "confirm_write=true en config" in msg
    if not cli_confirmed:
        assert "--confirm-write en CLI" in msg


def test_write_not_allowed_error_is_permission_error():
    """Compatibilidad con código legacy que pueda hacer `except PermissionError`."""
    guard = DoubleGateWriteGuard.read_only()
    with pytest.raises(PermissionError):
        guard.assert_can_write()


def test_error_carries_point_for_diagnostics():
    guard = DoubleGateWriteGuard.read_only()
    with pytest.raises(WriteNotAllowedError) as excinfo:
        guard.assert_can_write(point="dmsActivateMessage.0")
    assert excinfo.value.point == "dmsActivateMessage.0"


# ---------- autorización con ambas mitades del gate -------------------------


def test_double_gate_authorizes_live_write():
    guard = DoubleGateWriteGuard.from_flags(
        config_confirmed=True,
        cli_confirmed=True,
        dry_run=False,
    )
    assert guard.allow_write is True
    assert guard.dry_run is False
    # No debe lanzar.
    guard.assert_can_write(point="dmsActivateMessage")


def test_unsafe_allow_write_factory_authorizes():
    """Factory de compatibilidad para el `allow_write=True` del legacy."""
    guard = DoubleGateWriteGuard.unsafe_allow_write()
    assert guard.allow_write is True
    guard.assert_can_write()


# ---------- dry-run ---------------------------------------------------------


def test_dry_run_requires_double_gate():
    """`dry_run=True` no relaja el doble gate: si falta cualquiera, bloquea."""
    guard = DoubleGateWriteGuard.from_flags(
        config_confirmed=False,
        cli_confirmed=True,
        dry_run=True,
    )
    assert guard.dry_run is True
    assert guard.allow_write is False
    with pytest.raises(WriteNotAllowedError):
        guard.assert_can_write()


def test_dry_run_with_full_gate_authorizes_in_dry_mode():
    guard = DoubleGateWriteGuard.from_flags(
        config_confirmed=True,
        cli_confirmed=True,
        dry_run=True,
    )
    assert guard.allow_write is True
    assert guard.dry_run is True
    # La autorización se concede; corresponde al transporte decidir si ejecuta
    # o solo registra. El guard no se ocupa de eso.
    guard.assert_can_write(point="dmsMessageMultiString.1")


# ---------- contrato (sanity check del ABC) ---------------------------------


def test_doublegate_is_a_writeguard():
    assert isinstance(DoubleGateWriteGuard.read_only(), WriteGuard)


def test_writeguard_is_abstract():
    with pytest.raises(TypeError):
        WriteGuard()  # type: ignore[abstract]
