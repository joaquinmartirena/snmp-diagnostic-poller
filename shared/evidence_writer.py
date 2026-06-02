#!/usr/bin/env python3
"""
evidence_writer.py — Generic, device-agnostic file/evidence output helpers.

Extracted from the original common.py: the low-level "write a line to a
timestamped file" primitives (timestamps, path building, append, emit).
These are reused both by the polling tool (daily log files) and by the PoC
runner (per-run evidence files).

Polling-specific log *line formatting* (the COMM_STATUS prefix, change
suffixes) lives in polling/common.py — this module only knows how to write
text somewhere safely, not what the text means.
"""

import os
from datetime import datetime


def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_log_path(device_name, ip, directory="logs"):
    os.makedirs(directory, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(directory, f"{device_name}_{ip}_{date_str}.log")


def write_log(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def emit(path, line):
    """Print to stdout and append to the log/evidence file."""
    print(line)
    write_log(path, line)
