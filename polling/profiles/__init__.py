"""
Device profile registry.

Each entry maps a config `type` to a factory that, given a normalized device
dict, returns a list of asyncio tasks to run for that device:
  - VMS_NTCIP1203  -> one 'vms' task
  - SEMEX_C5000_V1 -> 'alarm' and 'cycle' tasks

To add a new profile: create polling/profiles/<name>.py exposing a
create_<name>_tasks(dev) factory, import it here, and register it below.
OIDs for the new profile must live in shared/oid_providers/, never here.
"""

from polling.profiles.vms_ntcip1203 import create_vms_tasks
from polling.profiles.semex_c5000 import create_semex_tasks

PROFILE_TASKS = {
    "VMS_NTCIP1203":  create_vms_tasks,
    "SEMEX_C5000_V1": create_semex_tasks,
}

__all__ = ["PROFILE_TASKS"]
