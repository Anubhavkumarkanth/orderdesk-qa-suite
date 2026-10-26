"""In-process checks of the pretend UPI provider itself (REQ-PAY-008). Expected values come from the sources, not the code."""
import random

import pytest

from app import upi_provider as upi

pytestmark = pytest.mark.unit


def test_tc_upi_001_outcomes_follow_the_upi_pulse_decline_rates():
    """TC-UPI-001: over 200,000 seeded draws, business declines come out at 9.62% and technical declines at 0.29% (UPI Pulse), within 4 standard errors."""
    rng, n = random.Random(2026), 200_000
    codes = [upi.draw(rng)[1] for _ in range(n)]
    for group, rate in ((("ZM", "Z9", "U16", "U69"), 0.0962), (("U30", "U67"), 0.0029)):
        share = sum(c in group for c in codes) / n
        assert abs(share - rate) < 4 * (rate * (1 - rate) / n) ** 0.5, (group, share)
    assert set(codes) == {None, "ZM", "Z9", "U16", "U69", "U30", "U67"}


def test_tc_upi_002_codes_carry_npci_meanings_and_labels():
    """TC-UPI-002: each code has NPCI's description and TD/BD label from Error and Response Codes v2.9 (U30 is NA there, counted as technical)."""
    assert {c: (f[0], f[2]) for c, f in upi.FAILURES.items()} == {
        "ZM": ("INVALID MPIN", "BD"),
        "Z9": ("INSUFFICIENT FUNDS IN CUSTOMER (REMITTER) ACCOUNT", "BD"),
        "U16": ("RISK THRESHOLD EXCEEDED", "BD"),
        "U69": ("COLLECT EXPIRED", "BD"),
        "U30": ("DEBIT HAS BEEN FAILED", "NA"),
        "U67": ("DEBIT TIMEOUT", "TD"),
    }
    assert (upi.BUSINESS, upi.TECHNICAL) == (("ZM", "Z9", "U16", "U69"), ("U30", "U67"))
