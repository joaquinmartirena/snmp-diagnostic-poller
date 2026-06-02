"""
oid_providers — the single home for all numeric SNMP OIDs in the toolkit.

INVARIANT: no OID is hardcoded anywhere outside this package. Polling
profiles and PoC scenarios obtain their OIDs by resolving a provider here.

OidProviderRegistry.resolve(key) returns a provider instance for a logical
device-type key.
"""

from shared.oid_providers.base import NtcipBase
from shared.oid_providers.ntcip1203_v3 import Ntcip1203V3
from shared.oid_providers.daktronics_vanguard import DaktronicsVanguard
from shared.oid_providers.semex_c5000 import SemexC5000Provider


class OidProviderRegistry:
    """Maps a device-type key to its OID provider class."""

    _providers = {
        "VMS_NTCIP1203":            Ntcip1203V3,
        "VMS_NTCIP1203_DAKTRONICS": DaktronicsVanguard,
        "SEMEX_C5000_V1":           SemexC5000Provider,
    }

    @classmethod
    def resolve(cls, key):
        """Return a provider instance for `key`, or raise KeyError if unknown."""
        try:
            provider_cls = cls._providers[key]
        except KeyError:
            valid = ", ".join(sorted(cls._providers))
            raise KeyError(
                f"No OID provider for '{key}'. Known providers: {valid}")
        return provider_cls()

    @classmethod
    def register(cls, key, provider_cls):
        """Register an additional provider class under `key`."""
        cls._providers[key] = provider_cls


__all__ = [
    "OidProviderRegistry",
    "NtcipBase",
    "Ntcip1203V3",
    "DaktronicsVanguard",
    "SemexC5000Provider",
]
