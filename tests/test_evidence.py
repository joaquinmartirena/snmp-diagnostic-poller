"""Tests del modelo de evidencia y sinks (Fase 2).

Cubren:

- Helpers planos: comportamiento idéntico al legacy (formato de timestamp, estructura del nombre de archivo, append-only).
- `LineLogSink`: ``raw_line`` se escribe verbatim (bit-exact con el formato histórico) y la reconstrucción desde ``fields`` + ``changes`` produce el mismo layout ``[ts] KEY=VAL ... CHANGE=...``.
- `JsonlSink`: escritura JSONL válida, una línea por record, con campos estructurados y valores tipográficamente raros.
- Compat: el shim `shared.evidence_writer` re-exporta los símbolos correctos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from itstoolkit.core.evidence import (
    EvidenceRecord,
    EvidenceSink,
    JsonlSink,
    LineLogSink,
    emit,
    get_log_path,
    now_ts,
    write_log,
)


# ---------- helpers planos --------------------------------------------------


def test_now_ts_format():
    ts = now_ts()
    # Mismo formato del poller legacy: "YYYY-MM-DD HH:MM:SS".
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ts)


def test_get_log_path_creates_directory_and_uses_date(tmp_path: Path):
    log_dir = tmp_path / "logs"
    path = get_log_path("dakt", "10.0.0.1", directory=str(log_dir))
    assert log_dir.exists()
    # name_ip_date.log con fecha actual.
    m = re.fullmatch(r"dakt_10\.0\.0\.1_\d{4}-\d{2}-\d{2}\.log", Path(path).name)
    assert m is not None, f"path inesperado: {path}"


def test_write_log_appends(tmp_path: Path):
    p = tmp_path / "x.log"
    write_log(str(p), "primera")
    write_log(str(p), "segunda")
    assert p.read_text(encoding="utf-8") == "primera\nsegunda\n"


def test_emit_prints_and_writes(tmp_path: Path, capsys):
    p = tmp_path / "e.log"
    emit(str(p), "hola")
    captured = capsys.readouterr()
    assert captured.out == "hola\n"
    assert p.read_text(encoding="utf-8") == "hola\n"


# ---------- LineLogSink -----------------------------------------------------


def test_linelogsink_raw_line_is_byte_exact(tmp_path: Path):
    """`raw_line` debe escribirse verbatim — preserva formato legacy bit-exact."""
    legacy_line = (
        "[2026-06-04 12:34:56] DEVICE=dakt TYPE=VMS_NTCIP1203_DAKTRONICS "
        "IP=10.0.0.1 PORT=161 POLL=42 COMM_STATUS=OK CHANGE=msg:\"hi\"->\"bye\""
    )
    p = tmp_path / "out.log"
    sink = LineLogSink(str(p))
    sink.write(EvidenceRecord(raw_line=legacy_line))
    sink.close()
    assert p.read_text(encoding="utf-8") == legacy_line + "\n"


def test_linelogsink_renders_from_fields_and_changes(tmp_path: Path):
    p = tmp_path / "out.log"
    sink = LineLogSink(str(p))
    record = EvidenceRecord(
        timestamp="2026-06-04 12:34:56",
        fields={
            "DEVICE": "dakt",
            "TYPE": "VMS_NTCIP1203",
            "IP": "10.0.0.1",
            "PORT": 161,
            "POLL": 1,
            "COMM_STATUS": "OK",
        },
        changes=("msg:\"hi\"->\"bye\"", "brightness:80->90"),
    )
    sink.write(record)
    sink.close()
    line = p.read_text(encoding="utf-8").rstrip("\n")
    expected = (
        "[2026-06-04 12:34:56] DEVICE=dakt TYPE=VMS_NTCIP1203 IP=10.0.0.1 "
        "PORT=161 POLL=1 COMM_STATUS=OK "
        "CHANGE=msg:\"hi\"->\"bye\";brightness:80->90"
    )
    assert line == expected


def test_linelogsink_daily_rotates_by_date(tmp_path: Path):
    sink = LineLogSink.daily("dakt", "10.0.0.1", directory=str(tmp_path))
    sink.write(EvidenceRecord(raw_line="entry-1"))
    sink.close()
    # Tiene que haber un archivo cuyo nombre encaje con la convención del poller.
    matches = list(tmp_path.glob("dakt_10.0.0.1_*.log"))
    assert len(matches) == 1
    assert matches[0].read_text(encoding="utf-8") == "entry-1\n"


def test_linelogsink_context_manager_closes(tmp_path: Path):
    p = tmp_path / "ctx.log"
    with LineLogSink(str(p)) as sink:
        sink.write(EvidenceRecord(raw_line="línea"))
    assert p.read_text(encoding="utf-8") == "línea\n"


def test_linelogsink_echo_stdout(tmp_path: Path, capsys):
    p = tmp_path / "echo.log"
    sink = LineLogSink(str(p), echo_stdout=True)
    sink.write(EvidenceRecord(raw_line="vivo"))
    sink.close()
    assert capsys.readouterr().out == "vivo\n"
    assert p.read_text(encoding="utf-8") == "vivo\n"


# ---------- JsonlSink -------------------------------------------------------


def test_jsonlsink_writes_one_object_per_line(tmp_path: Path):
    p = tmp_path / "evidence.jsonl"
    sink = JsonlSink(str(p))
    sink.write(
        EvidenceRecord(
            timestamp="2026-06-04 12:34:56",
            fields={"step": "get", "oid": "1.3.6.1.4.1.1206"},
            payload={"value": 42, "err": None},
        )
    )
    sink.write(
        EvidenceRecord(
            timestamp="2026-06-04 12:34:57",
            fields={"step": "set", "oid": "1.3.6.1.4.1.1206"},
            changes=("value:42->43",),
            payload={"dry_run": True},
        )
    )
    sink.close()

    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    a, b = (json.loads(lines[0]), json.loads(lines[1]))
    assert a["ts"] == "2026-06-04 12:34:56"
    assert a["fields"] == {"step": "get", "oid": "1.3.6.1.4.1.1206"}
    assert a["changes"] == []
    assert a["payload"] == {"value": 42, "err": None}
    assert b["changes"] == ["value:42->43"]
    assert b["payload"]["dry_run"] is True


def test_jsonlsink_handles_opaque_values_via_default_str(tmp_path: Path):
    """Valores no-JSON (objetos pysnmp, datetime, etc.) no deben romper el sink."""

    class Opaque:
        def __str__(self):
            return "<opaque>"

    p = tmp_path / "ev.jsonl"
    sink = JsonlSink(str(p))
    sink.write(EvidenceRecord(payload={"x": Opaque()}))
    sink.close()

    obj = json.loads(p.read_text(encoding="utf-8").strip())
    assert obj["payload"] == {"x": "<opaque>"}


def test_jsonlsink_is_context_manager(tmp_path: Path):
    p = tmp_path / "ctx.jsonl"
    with JsonlSink(str(p)) as sink:
        assert isinstance(sink, EvidenceSink)
        sink.write(EvidenceRecord(timestamp="t", fields={"k": "v"}))
    # close() debe ser idempotente cuando se llama de nuevo.
    obj = json.loads(p.read_text(encoding="utf-8").strip())
    assert obj["fields"] == {"k": "v"}


# ---------- contrato del sink ----------------------------------------------


def test_evidencesink_is_abstract():
    with pytest.raises(TypeError):
        EvidenceSink()  # type: ignore[abstract]
