"""
polling — the read-only diagnostic poller.

Depends only on `shared`. Never imports from `pocs`. SNMP access is always
through shared.snmp_client.SnmpClient(allow_write=False).
"""
