#!/usr/bin/env python3
"""
semex_c5000.py — SemexC5000Provider: OIDs for the SEMEX C5000 ASC.

NTCIP 1202 Actuated Signal Controller OIDs that used to be hardcoded in
polling/profiles/semex_c5000.py. A simple flat provider (no inheritance
hierarchy needed yet): scalar constants plus the OID-list builders the cycle
poll relies on.

Decoding/formatting of these values stays in the polling profile — this
module only owns the numeric OIDs and their layout.
"""


class SemexC5000Provider:
    """OID provider for the SEMEX C5000 (NTCIP 1202 ASC)."""

    # Base OID — NTCIP 1202 Actuated Signal Controller
    ASC = "1.3.6.1.4.1.1206.4.2.1"

    # Alarm scalars
    UNIT_ALARM1 = f"{ASC}.3.7.0"
    UNIT_ALARM2 = f"{ASC}.3.8.0"
    SHORT_ALARM = f"{ASC}.3.9.0"
    UPTIME      = f"{ASC}.1.3.0"

    # Coordination scalars
    COORD_PATTERN     = f"{ASC}.4.10.0"
    COORD_SYS_PATTERN = f"{ASC}.4.14.0"
    COORD_LOCAL_FREE  = f"{ASC}.4.11.0"
    COORD_CYCLE       = f"{ASC}.4.12.0"
    COORD_SYNC        = f"{ASC}.4.13.0"

    PHASE_GROUPS = range(1, 5)
    RINGS        = range(1, 5)
    CHANNELS     = range(1, 5)

    def build_alarm_oids(self):
        return [self.UNIT_ALARM1, self.UNIT_ALARM2, self.SHORT_ALARM, self.UPTIME]

    def build_cycle_oids(self):
        """Return ordered (logical_key, oid) pairs for the cycle poll."""
        asc = self.ASC
        pairs = []
        for g in self.PHASE_GROUPS:
            pairs += [
                (f"p{g}_R",  f"{asc}.1.4.1.2.{g}"),
                (f"p{g}_Y",  f"{asc}.1.4.1.3.{g}"),
                (f"p{g}_G",  f"{asc}.1.4.1.4.{g}"),
                (f"p{g}_DW", f"{asc}.1.4.1.5.{g}"),
                (f"p{g}_W",  f"{asc}.1.4.1.7.{g}"),
                (f"p{g}_VC", f"{asc}.1.4.1.8.{g}"),
                (f"p{g}_PC", f"{asc}.1.4.1.9.{g}"),
                (f"p{g}_ON", f"{asc}.1.4.1.10.{g}"),
            ]
        for r in self.RINGS:
            pairs.append((f"r{r}", f"{asc}.7.6.1.1.{r}"))
        for c in self.CHANNELS:
            pairs += [
                (f"c{c}_R", f"{asc}.8.4.1.2.{c}"),
                (f"c{c}_Y", f"{asc}.8.4.1.3.{c}"),
                (f"c{c}_G", f"{asc}.8.4.1.4.{c}"),
            ]
        pairs += [
            ("coord_pattern",     self.COORD_PATTERN),
            ("coord_sys_pattern", self.COORD_SYS_PATTERN),
            ("coord_local_free",  self.COORD_LOCAL_FREE),
            ("coord_cycle",       self.COORD_CYCLE),
            ("coord_sync",        self.COORD_SYNC),
        ]
        return pairs
