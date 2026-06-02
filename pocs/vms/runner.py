#!/usr/bin/env python3
"""
runner.py — VMS PoC scenario runner.

SKELETON — not implemented yet.

Purpose: orchestrate execution of VMS scenarios (subclasses of BaseScenario)
against a configured panel, capturing evidence via shared.evidence_writer.

Write safety gate (to implement here):
    - Resolve OIDs via shared.oid_providers (never hardcode OIDs).
    - For each scenario:
        * if scenario.requires_write is False -> run with
          SnmpClient(allow_write=False).
        * if scenario.requires_write is True -> run only when the panel
          config has confirm_write: true AND the CLI passed --confirm-write;
          otherwise SKIP/BLOCK the scenario and log the reason. Only then may
          a SnmpClient(allow_write=True) be constructed.

Depends only on `shared` and `pocs`. Never imports `polling`.
"""
