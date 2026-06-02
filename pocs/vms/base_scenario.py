#!/usr/bin/env python3
"""
base_scenario.py — BaseScenario: contract every VMS PoC scenario implements.

SKELETON — not implemented yet.

Purpose: define the common interface for VMS scenarios. The key field is
`requires_write` (default False): scenarios that need an SNMP SET set it to
True, which makes the runner enforce the confirm_write / --confirm-write gate
before they are allowed to run.

Depends only on `shared`. Never imports `polling`.
"""
