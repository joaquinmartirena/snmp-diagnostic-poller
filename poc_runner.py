#!/usr/bin/env python3
"""
poc_runner.py — Top-level entrypoint for running VMS proof-of-concept scenarios.

SKELETON — not implemented yet.

Purpose: load a panel config (pocs/vms/config/panels/*.yaml), select one or
more scenarios from pocs/vms/scenarios/, and run them through the PoC runner.

Write safety contract (to be enforced by pocs/vms/runner.py):
    - A scenario that declares requires_write = True may only run when BOTH
      `confirm_write: true` is set in the panel config AND `--confirm-write`
      is passed on the CLI. If either is missing, the runner must block the
      scenario and refuse to construct a writable SNMP client.
    - Read-only scenarios always run with SnmpClient(allow_write=False).

This module depends only on `shared` and `pocs`. It never imports `polling`.
"""
