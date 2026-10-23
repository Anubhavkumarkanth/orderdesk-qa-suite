"""Seeded defects for the application under test.

The ORDERDESK_DEFECTS environment variable switches them on, e.g. ORDERDESK_DEFECTS=BUG-001,BUG-004
or ORDERDESK_DEFECTS=all. With the variable unset the application behaves as specified in
docs/requirements.md. Every defect is documented in docs/bugs/.
"""
import os

ALL = ("BUG-001", "BUG-002", "BUG-003", "BUG-004", "BUG-005", "BUG-006", "BUG-007", "BUG-008")


def active() -> frozenset[str]:
    raw = os.environ.get("ORDERDESK_DEFECTS", "").strip()
    if raw.lower() == "all":
        return frozenset(ALL)
    return frozenset(p.strip().upper() for p in raw.split(",") if p.strip())


def on(bug_id: str) -> bool:
    return bug_id in active()
