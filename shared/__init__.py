"""
shared — device-agnostic building blocks reused across the toolkit.

This package never imports from `polling` or `pocs`. It only provides
lower-level primitives (SNMP client, value coercion, config loading,
evidence writing) and the OID providers, so both the polling tool and the
PoC runner can depend on it without creating import cycles.
"""
