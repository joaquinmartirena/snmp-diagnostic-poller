"""Tests del modo `scenario` y de los escenarios PoC VMS (Fase 5).

Sin hardware: los tests usan un FakeSnmpSession scripteado por OID. Cubren:

- `scenario list` muestra los escenarios registrados.
- `scenario run --scenario POC-VMS-01` ejecuta un escenario mockeado y termina
  en PASS.
- `scenario run --automatic-only` corre los AUTOMATIC.
- Los escenarios read-only no requieren `--confirm-write`.
- Un scenario con `requires_write=True` queda BLOCKED sin doble gate, y corre
  cuando el doble gate está completo.
- El JSONL de evidencia se materializa en `evidence/<family>/...`.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pytest

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    EXEC_REQUIRES_PHYSICAL,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)
from itstoolkit.devices import load_all_adapters
from itstoolkit.devices.vms_ntcip1203 import oids as vms_oids
from itstoolkit.devices.vms_ntcip1203.scenarios import (
    PocVms01Connectivity,
    PocVms02OidMap,
    PocVms03Capabilities,
    PocVms04ReadActiveMessage,
)
from itstoolkit.modes import scenario as scenario_mode


@pytest.fixture(autouse=True)
def _ensure_adapters_loaded():
    load_all_adapters()


@pytest.fixture
def evidence_dir(tmp_path: Path) -> str:
    """Carpeta de evidencia aislada por test (no contamina el repo)."""
    d = tmp_path / "evidence"
    d.mkdir()
    return str(d)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Evita que POC-VMS-01 duerma 5*4=20s entre lecturas en cada test."""
    real_sleep = asyncio.sleep

    async def _zero_sleep(_seconds, *args, **kwargs):
        # delegamos a sleep(0) para mantener el cooperative scheduling
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _zero_sleep)


# ---------------------------------------------------------------------------
# FakeSnmpSession: respuestas scripteables por OID
# ---------------------------------------------------------------------------


class FakeSnmpSession:
    """SnmpSession mockeada — sin transporte real.

    `responses`: dict OID -> valor (None significa NoSuchObject).
    `error`: si está, todas las llamadas devuelven (vacío, error).
    """

    def __init__(
        self,
        responses: Optional[Mapping[str, Any]] = None,
        *,
        error: Optional[str] = None,
    ) -> None:
        self.responses: Dict[str, Any] = dict(responses or {})
        self.error = error
        self.closed = False
        self.calls: List[Tuple[str, Sequence[str]]] = []

    async def get_many(self, oids: Sequence[str]):
        self.calls.append(("get_many", list(oids)))
        if self.error:
            return {}, self.error
        return ({o: self.responses.get(o) for o in oids}, None)

    async def get_one(self, oid: str):
        self.calls.append(("get_one", [oid]))
        if self.error:
            return None, self.error
        return self.responses.get(oid), None

    async def close(self) -> None:
        self.closed = True


def _factory_returning(session: FakeSnmpSession) -> scenario_mode.SessionFactory:
    async def _f(device_config, write_guard):
        return session

    return _f


def _vms_device(name: str = "p1", **extra) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "family": "vms_ntcip1203",
        "name": name,
        "ip": "10.0.0.1",
        "port": 161,
        "community": "public",
        "type_label": "VMS_NTCIP1203",
    }
    base.update(extra)
    return base


def _full_panel_responses(*, with_multi: bool = True) -> Dict[str, Any]:
    """Set de respuestas que satisface POC-VMS-01/02/03/04 sin missing."""
    out: Dict[str, Any] = {
        vms_oids.SYS_DESCR: "Daktronics Vanguard VFC",
        vms_oids.SYS_OBJECT_ID: "1.3.6.1.4.1.1206",
        vms_oids.SYS_UPTIME: 123456,
        vms_oids.SYS_NAME: "vms-test",
        vms_oids.GLOBAL_SET_ID_PARAMETER: 1,
        vms_oids.CONTROLLER_BASE_STANDARDS: b"\x00",
        vms_oids.GLOBAL_TIME: 0,
        vms_oids.CTRL_MODE: 4,  # central
        vms_oids.SRC_MODE: 8,  # central
        vms_oids.MSG_SRC: b"\x03\x00\x04\x9D\xD5",  # memType=3, msgNum=4, crc
        vms_oids.SHORT_ERR: 0,
    }
    # Capabilities critical + optional
    for oid in list(vms_oids.CAPABILITY_CRITICAL.values()) + list(
        vms_oids.CAPABILITY_OPTIONAL.values()
    ):
        out.setdefault(oid, 1)
    # Multi
    if with_multi:
        multi_oid = vms_oids.multi_oid(3, 4)
        out[multi_oid] = b"HELLO WORLD"
    return out


# ---------------------------------------------------------------------------
# list_scenarios
# ---------------------------------------------------------------------------


def test_list_scenarios_returns_registered_vms_scenarios():
    items = scenario_mode.list_scenarios("vms_ntcip1203")
    ids = [it["id"] for it in items]
    assert ids == [
        "POC-VMS-01",
        "POC-VMS-02",
        "POC-VMS-03",
        "POC-VMS-04",
        "POC-VMS-05",
        "POC-VMS-06",
        "POC-VMS-07",
        "POC-VMS-08",
        "POC-VMS-09",
        "POC-VMS-10",
        "POC-VMS-11",
        "POC-VMS-12",
        "POC-VMS-13",
        "POC-VMS-14",
        "POC-VMS-15",
        "POC-VMS-15B",
        "POC-VMS-16",
        "POC-VMS-17",
        "POC-VMS-18",
        "POC-VMS-19",
        "POC-VMS-20",
        "POC-VMS-21",
    ]
    # Metadata mínima presente en todos.
    for it in items:
        assert it["name"]
        assert it["description"]

    by_id = {it["id"]: it for it in items}

    # Read-only / AUTOMATIC (no requieren doble gate).
    for poc_id in (
        "POC-VMS-01",
        "POC-VMS-02",
        "POC-VMS-03",
        "POC-VMS-04",
        "POC-VMS-09",
        "POC-VMS-11",
        "POC-VMS-15",
    ):
        assert by_id[poc_id]["execution_mode"] == EXEC_AUTOMATIC
        assert by_id[poc_id]["requires_write"] is False

    # Write-heavy: AUTOMATIC pero requires_write=True.
    for poc_id in (
        "POC-VMS-05",
        "POC-VMS-06",
        "POC-VMS-07",
        "POC-VMS-08",
        "POC-VMS-14",
        "POC-VMS-15B",
        "POC-VMS-16",
        "POC-VMS-17",
        "POC-VMS-18",
        "POC-VMS-19",
        "POC-VMS-20",
        "POC-VMS-21",
    ):
        assert by_id[poc_id]["execution_mode"] == EXEC_AUTOMATIC
        assert by_id[poc_id]["requires_write"] is True

    # REQUIRES_PHYSICAL read-only (operador hace el cambio externo).
    for poc_id in ("POC-VMS-10", "POC-VMS-12", "POC-VMS-13"):
        assert by_id[poc_id]["execution_mode"] == "REQUIRES_PHYSICAL"
        assert by_id[poc_id]["requires_write"] is False


def test_list_scenarios_for_semex_is_empty():
    items = scenario_mode.list_scenarios("semex_c5000")
    assert items == []


# ---------------------------------------------------------------------------
# run_scenarios — happy path
# ---------------------------------------------------------------------------


def test_run_single_scenario_id_returns_pass(evidence_dir):
    session = FakeSnmpSession(responses=_full_panel_responses())
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            scenario_ids=["POC-VMS-01"],
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert len(results) == 1
    r = results[0]
    assert r.scenario_id == "POC-VMS-01"
    assert r.status == STATUS_PASS, r.summary
    assert r.evidence_path
    assert os.path.isfile(r.evidence_path)
    assert session.closed
    # Evidencia bien formada.
    lines = Path(r.evidence_path).read_text(encoding="utf-8").splitlines()
    assert lines, "El JSONL no debería estar vacío."
    last = json.loads(lines[-1])
    assert last["payload"]["scenario_id"] == "POC-VMS-01"
    assert last["payload"]["result"] == STATUS_PASS


def test_run_automatic_only_runs_all_automatic_vms_scenarios(evidence_dir):
    """``automatic_only=True`` corre POC 01-09 (10 es REQUIRES_PHYSICAL)."""
    session = FakeSnmpSession(responses=_full_panel_responses())
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            automatic_only=True,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert [r.scenario_id for r in results] == [
        "POC-VMS-01",
        "POC-VMS-02",
        "POC-VMS-03",
        "POC-VMS-04",
        "POC-VMS-05",
        "POC-VMS-06",
        "POC-VMS-07",
        "POC-VMS-08",
        "POC-VMS-09",
        "POC-VMS-11",
        "POC-VMS-14",
        "POC-VMS-15",
        "POC-VMS-15B",
        "POC-VMS-16",
        "POC-VMS-17",
        "POC-VMS-18",
        "POC-VMS-19",
        "POC-VMS-20",
        "POC-VMS-21",
    ]
    by_id = {r.scenario_id: r for r in results}
    # Read-only AUTOMATIC pasan con datos válidos (mocked).
    # POC-11 puede dar PARTIAL si el panel devuelve drift alto pero estable
    # contra el mock; POC-15 puede dar PASS sin slots cargados.
    for pid in (
        "POC-VMS-01",
        "POC-VMS-02",
        "POC-VMS-03",
        "POC-VMS-04",
        "POC-VMS-09",
        "POC-VMS-15",
    ):
        assert by_id[pid].status == STATUS_PASS, (
            f"{pid} {by_id[pid].status}: {by_id[pid].summary}"
        )
    # POC-11 contra mock con globalTime=0 da drift enorme → FAIL esperado.
    assert by_id["POC-VMS-11"].status in (STATUS_PASS, STATUS_PARTIAL, STATUS_FAIL)
    # Write-heavy quedan BLOCKED sin el doble gate (este test no lo activa).
    for pid in (
        "POC-VMS-05",
        "POC-VMS-06",
        "POC-VMS-07",
        "POC-VMS-08",
        "POC-VMS-14",
        "POC-VMS-15B",
        "POC-VMS-16",
        "POC-VMS-17",
        "POC-VMS-18",
        "POC-VMS-19",
        "POC-VMS-20",
        "POC-VMS-21",
    ):
        assert by_id[pid].status == STATUS_BLOCKED, (
            f"{pid} debería estar BLOCKED sin --confirm-write, está "
            f"{by_id[pid].status}"
        )


def test_read_only_scenarios_do_not_require_confirm_write(evidence_dir):
    """Los read-only (01-04, 09) pasan sin ``--confirm-write``."""
    session = FakeSnmpSession(responses=_full_panel_responses())
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            scenario_ids=[
                "POC-VMS-01",
                "POC-VMS-02",
                "POC-VMS-03",
                "POC-VMS-04",
                "POC-VMS-09",
            ],
            cli_confirm_write=False,  # explícito
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    for r in results:
        assert r.status == STATUS_PASS, f"{r.scenario_id}: {r.summary}"


# ---------------------------------------------------------------------------
# run_scenarios — degradación
# ---------------------------------------------------------------------------


def test_scenario_01_fails_when_all_reads_timeout(evidence_dir):
    session = FakeSnmpSession(error="TIMEOUT")
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            scenario_ids=["POC-VMS-01"],
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    r = results[0]
    assert r.status == STATUS_FAIL
    assert "0/5" in r.summary or "no responde" in r.summary


def test_scenario_03_partial_when_only_optional_missing(evidence_dir):
    """Si faltan opcionales pero los críticos están, POC-VMS-03 da PARTIAL."""
    from itstoolkit.core.scenario import STATUS_PARTIAL

    resp = _full_panel_responses()
    # Quitar todos los opcionales — los críticos quedan.
    for oid in vms_oids.CAPABILITY_OPTIONAL.values():
        resp[oid] = None
    session = FakeSnmpSession(responses=resp)
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            scenario_ids=["POC-VMS-03"],
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert results[0].status == STATUS_PARTIAL


def test_run_unknown_scenario_id_raises():
    session = FakeSnmpSession()
    with pytest.raises(KeyError) as excinfo:
        asyncio.run(
            scenario_mode.run_scenarios(
                [_vms_device()],
                scenario_ids=["POC-VMS-99"],
                session_factory=_factory_returning(session),
            )
        )
    assert "POC-VMS-99" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Doble gate: BLOCKED y autorizado
# ---------------------------------------------------------------------------


class _FakeWriteScenario(Scenario):
    """Scenario sintético con requires_write=True — sólo para tests del gate."""

    id = "POC-FAKE-WRITE"
    name = "Fake escenario de escritura"
    description = "Test-only: marca requires_write=True para ejercitar el doble gate."
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    def __init__(self):
        self.ran = False

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        self.ran = True
        # Sólo ejecuta una operación trivial — el test verifica que se llegó.
        ctx.record_step(
            "noop",
            operation="NOOP",
            success=True,
            notes="el doble gate dejó pasar",
        )
        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary="Fake scenario corrió: doble gate autorizó.",
        )


def _patch_vms_scenarios_with(scenario, monkeypatch):
    from itstoolkit.core.device import device_registry

    adapter_cls = device_registry.get("vms_ntcip1203")
    monkeypatch.setattr(adapter_cls, "scenarios", lambda self: [scenario])


def test_requires_write_blocked_without_double_gate(monkeypatch, evidence_dir):
    fake = _FakeWriteScenario()
    _patch_vms_scenarios_with(fake, monkeypatch)
    session = FakeSnmpSession(responses=_full_panel_responses())

    # Caso 1: ni config ni CLI → BLOCKED.
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],  # confirm_write no seteado
            cli_confirm_write=False,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert len(results) == 1
    assert results[0].status == STATUS_BLOCKED
    assert "doble gate" in results[0].summary
    assert fake.ran is False, "El scenario no debe haber corrido."

    # Caso 2: sólo config — falta CLI → BLOCKED.
    fake2 = _FakeWriteScenario()
    _patch_vms_scenarios_with(fake2, monkeypatch)
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device(confirm_write=True)],
            cli_confirm_write=False,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert results[0].status == STATUS_BLOCKED
    assert "--confirm-write en CLI" in results[0].summary
    assert fake2.ran is False

    # Caso 3: sólo CLI — falta config → BLOCKED.
    fake3 = _FakeWriteScenario()
    _patch_vms_scenarios_with(fake3, monkeypatch)
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],  # confirm_write falso
            cli_confirm_write=True,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert results[0].status == STATUS_BLOCKED
    assert "confirm_write=true en config" in results[0].summary
    assert fake3.ran is False


def test_requires_write_runs_with_full_double_gate(monkeypatch, evidence_dir):
    fake = _FakeWriteScenario()
    _patch_vms_scenarios_with(fake, monkeypatch)
    session = FakeSnmpSession(responses=_full_panel_responses())

    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device(confirm_write=True)],
            cli_confirm_write=True,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert len(results) == 1
    assert results[0].status == STATUS_PASS
    assert fake.ran is True
    assert session.closed


def test_blocked_scenario_writes_evidence_with_reason(monkeypatch, evidence_dir):
    fake = _FakeWriteScenario()
    _patch_vms_scenarios_with(fake, monkeypatch)
    session = FakeSnmpSession(responses=_full_panel_responses())

    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            cli_confirm_write=False,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    r = results[0]
    assert r.evidence_path and os.path.isfile(r.evidence_path)
    lines = Path(r.evidence_path).read_text(encoding="utf-8").splitlines()
    # Debe haber un gate_check step y un summary.
    steps = [json.loads(line) for line in lines]
    gate_steps = [
        s for s in steps if s["payload"].get("operation") == "WRITE_GATE"
    ]
    assert gate_steps, "Falta el step gate_check en la evidencia."
    assert gate_steps[0]["payload"]["error"] == "DOUBLE_GATE_MISSING"
    assert "missing" in gate_steps[0]["payload"]
    # El último record es el summary.
    assert steps[-1]["payload"]["result"] == STATUS_BLOCKED


# ---------------------------------------------------------------------------
# CLI: build_parser + cmd_scenario list
# ---------------------------------------------------------------------------


def test_cli_parser_lists_scenario_subcommand():
    from itstoolkit import cli

    parser = cli.build_parser()
    help_text = parser.format_help()
    assert "scenario" in help_text


def test_cli_scenario_list_prints_ids(capsys):
    from itstoolkit import cli

    rc = cli.main(["scenario", "list", "--family", "vms_ntcip1203"])
    assert rc == 0
    out = capsys.readouterr().out
    for sid in ("POC-VMS-01", "POC-VMS-02", "POC-VMS-03", "POC-VMS-04"):
        assert sid in out


# ---------------------------------------------------------------------------
# Filtering: automatic-only excluye REQUIRES_PHYSICAL
# ---------------------------------------------------------------------------


class _FakePhysicalScenario(Scenario):
    id = "POC-FAKE-PHYS"
    name = "Fake escenario físico"
    description = "Test-only: REQUIRES_PHYSICAL, no debe correr con --automatic-only."
    execution_mode = EXEC_REQUIRES_PHYSICAL
    requires_write = False

    def __init__(self):
        self.ran = False

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        self.ran = True
        return ScenarioResult(self.id, STATUS_PASS, "")


def test_automatic_only_excludes_requires_physical(monkeypatch, evidence_dir):
    fake_phys = _FakePhysicalScenario()
    auto = PocVms01Connectivity()
    from itstoolkit.core.device import device_registry

    adapter_cls = device_registry.get("vms_ntcip1203")
    monkeypatch.setattr(adapter_cls, "scenarios", lambda self: [auto, fake_phys])

    session = FakeSnmpSession(responses=_full_panel_responses())
    results = asyncio.run(
        scenario_mode.run_scenarios(
            [_vms_device()],
            automatic_only=True,
            session_factory=_factory_returning(session),
            evidence_directory=evidence_dir,
        )
    )
    assert [r.scenario_id for r in results] == ["POC-VMS-01"]
    assert fake_phys.ran is False
