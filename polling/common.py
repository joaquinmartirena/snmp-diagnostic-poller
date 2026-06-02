#!/usr/bin/env python3
"""
common.py — polling-specific log line helpers and change detection.

What remains of the original common.py after SNMP, value coercion and the
low-level file writers were moved into shared/. This module knows how a
diagnostic log *line* is shaped (the COMM_STATUS prefix, CHANGE suffix) and
how to diff two state snapshots. It re-exports the generic file writers from
shared.evidence_writer for backwards-compatible call sites.

Imports only from `shared` — never from `pocs`.
"""

from shared.evidence_writer import now_ts, get_log_path, write_log, emit  # re-export

__all__ = [
    "now_ts", "get_log_path", "write_log", "emit",
    "build_common_prefix", "append_changes", "detect_changes",
]


def build_common_prefix(ts, dev, poll, comm_status):
    return (
        f"[{ts}] "
        f"DEVICE={dev['name']} "
        f"TYPE={dev['type']} "
        f"IP={dev['ip']} "
        f"PORT={dev['port']} "
        f"POLL={poll} "
        f"COMM_STATUS={comm_status}"
    )


def append_changes(line, changes):
    if changes:
        return line + " CHANGE=" + ";".join(changes)
    return line


def detect_changes(prev, current, keys, labels, quoted=()):
    """Generic field-change detector. Only reports keys present in prev."""
    changes = []
    for k in keys:
        pv = prev.get(k)
        cv = current.get(k)
        if pv is not None and pv != cv:
            if k in quoted:
                changes.append(f'{labels[k]}:"{pv}"->"{cv}"')
            else:
                changes.append(f"{labels[k]}:{pv}->{cv}")
    return changes
