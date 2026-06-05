"""Tests del registry de dispositivos y de los schemas de los adapters.

No corren contra hardware: solo verifican la auto-registración, el schema y
la integridad de los catálogos de OIDs migrados.
"""

from __future__ import annotations

import pytest

from itstoolkit.core.device import DeviceAdapter, device_registry
from itstoolkit.devices import load_all_adapters


@pytest.fixture(autouse=True)
def _ensure_adapters_loaded():
    """Cada test arranca con todos los adapters cargados."""
    load_all_adapters()


def test_both_adapters_register():
    families = set(device_registry.families())
    assert {"vms_ntcip1203", "semex_c5000"} <= families


@pytest.mark.parametrize("family", ["vms_ntcip1203", "semex_c5000"])
def test_adapter_is_a_device_adapter(family):
    cls = device_registry.get(family)
    adapter = cls()
    assert isinstance(adapter, DeviceAdapter)
    assert adapter.family == family


@pytest.mark.parametrize("family", ["vms_ntcip1203", "semex_c5000"])
def test_adapter_schema_declares_required_connection_keys(family):
    schema = device_registry.get(family)().config_schema()
    # Toda familia tiene que pedir al menos name + ip.
    assert "name" in schema and schema["name"].get("required")
    assert "ip" in schema and schema["ip"].get("required")
    # Puerto y community tienen default.
    assert schema["port"].get("default") == 161
    assert schema["community"].get("default") == "public"


def test_unknown_family_raises_with_helpful_message():
    with pytest.raises(KeyError) as excinfo:
        device_registry.get("nope")
    msg = str(excinfo.value)
    assert "vms_ntcip1203" in msg
    assert "semex_c5000" in msg


# ---------- catálogos de OIDs ----------------------------------------------


def test_vms_oids_match_legacy_values():
    """Los OIDs migrados del VMS deben ser idénticos a los del legacy."""
    from itstoolkit.devices.vms_ntcip1203 import oids

    # Valores verificados contra NTCIP 1203 v03.05.
    assert oids.CTRL_MODE == "1.3.6.1.4.1.1206.4.2.3.6.1.0"
    assert oids.MSG_SRC == "1.3.6.1.4.1.1206.4.2.3.6.5.0"
    assert oids.SRC_MODE == "1.3.6.1.4.1.1206.4.2.3.6.7.0"
    assert oids.SHORT_ERR == "1.3.6.1.4.1.1206.4.2.3.9.7.1.0"
    assert oids.required_oids() == [
        oids.CTRL_MODE,
        oids.SRC_MODE,
        oids.MSG_SRC,
        oids.SHORT_ERR,
    ]
    assert oids.multi_oid(1, 7) == "1.3.6.1.4.1.1206.4.2.3.5.8.1.3.1.7"


def test_semex_oids_match_legacy_values():
    from itstoolkit.devices.semex_c5000 import oids

    assert oids.ASC == "1.3.6.1.4.1.1206.4.2.1"
    assert oids.UNIT_ALARM1 == "1.3.6.1.4.1.1206.4.2.1.3.7.0"
    assert oids.UPTIME == "1.3.6.1.4.1.1206.4.2.1.1.3.0"
    pairs = oids.build_cycle_oids()
    # 4 grupos × 8 cols + 4 rings + 4 channels × 3 + 5 coord scalars = 53.
    assert len(pairs) == 4 * 8 + 4 + 4 * 3 + 5


# ---------- decoders --------------------------------------------------------


def test_vms_decoders_known_values():
    from itstoolkit.devices.vms_ntcip1203 import decoders as d

    assert d.decode_control_mode(2) == "local(2)"
    assert d.decode_control_mode(4) == "central(4)"
    assert d.decode_control_mode(99).startswith("unknown(")

    assert d.decode_source_mode(8) == "central(8)"
    assert d.decode_source_mode(9) == "timebasedScheduler(9)"

    err, raw = d.decode_short_error_status(0)
    assert err == "none" and raw == "0000"
    err, raw = d.decode_short_error_status(0b10)  # communicationsError
    assert "communicationsError" in err and raw == "0002"


def test_semex_restart_detection():
    from itstoolkit.devices.semex_c5000 import decoders as d

    assert d.detect_restart(None, None) == "unknown"
    assert d.detect_restart(100, None) == "unknown"
    assert d.detect_restart(100, 50) == "no"
    assert d.detect_restart(10, 100) == "detected"
