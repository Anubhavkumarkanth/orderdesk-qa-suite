"""Boundary-value and rule tests for quantity, coupons, shipping and rounding (REQ-QTY-*, REQ-PRC-*).

Amounts are paise. BND-* products are fixtures priced so subtotals land exactly on the thresholds:
A = 249.99, B = 250.00, C = 250.01, D = 50.00, E = 250.05.
"""
import pytest

pytestmark = pytest.mark.api


@pytest.mark.parametrize("quantity, expected", [(-1, 422), (0, 422), (1, 201), (2, 201), (9, 201), (10, 201), (11, 422), (50, 422)])
def test_tc_qty_001_quantity_boundaries(api, quantity, expected):
    """TC-QTY-001: per-line quantity must be 1..10 (boundary values 0, 1, 10, 11)."""
    assert api.place([("NB-A5", quantity)]).status_code == expected


@pytest.mark.parametrize("items, expected_status", [
    ([("BND-A", 1), ("BND-B", 1)], 422),   # 499.99 -> below SAVE10 minimum
    ([("BND-B", 2)], 201),                 # 500.00 -> exactly the minimum
    ([("BND-B", 1), ("BND-C", 1)], 201),   # 500.01
])
def test_tc_prc_001_save10_minimum_subtotal_boundary(api, items, expected_status):
    """TC-PRC-001: SAVE10 needs a subtotal of at least Rs 500.00 (inclusive); below it the coupon is rejected, not ignored."""
    assert api.place(items, coupon="SAVE10").status_code == expected_status


def test_tc_prc_002_save10_at_exact_minimum_gives_free_shipping_and_correct_total(api):
    """TC-PRC-002: Rs 500.00 with SAVE10 -> discount 50.00, shipping free (basis is the PRE-discount subtotal), total 450.00."""
    o = api.place([("BND-B", 2)], coupon="SAVE10").json()
    assert (o["subtotal_paise"], o["discount_paise"], o["shipping_paise"], o["total_paise"]) == (50_000, 5_000, 0, 45_000)


@pytest.mark.parametrize("items, discount", [
    ([("BND-B", 1), ("BND-C", 1)], 5_000),   # 10% of 500.01 = 50.001 -> 50.00
    ([("BND-B", 1), ("BND-E", 1)], 5_001),   # 10% of 500.05 = 50.005 -> rounds half UP to 50.01
])
def test_tc_prc_003_percentage_discount_rounds_half_up(api, items, discount):
    """TC-PRC-003: percentage discounts round half up to the paisa."""
    assert api.place(items, coupon="SAVE10").json()["discount_paise"] == discount


@pytest.mark.parametrize("items, expected_status", [
    ([("BND-A", 1), ("BND-D", 1)], 422),   # 299.99
    ([("BND-B", 1), ("BND-D", 1)], 201),   # 300.00
    ([("BND-C", 1), ("BND-D", 1)], 201),   # 300.01
])
def test_tc_prc_004_flat50_minimum_subtotal_boundary(api, items, expected_status):
    """TC-PRC-004: FLAT50 needs a subtotal of at least Rs 300.00 (inclusive)."""
    assert api.place(items, coupon="FLAT50").status_code == expected_status


def test_tc_prc_005_flat50_total(api):
    """TC-PRC-005: Rs 300.00 with FLAT50 -> discount 50.00, shipping 40.00, total 290.00."""
    o = api.place([("BND-B", 1), ("BND-D", 1)], coupon="FLAT50").json()
    assert (o["subtotal_paise"], o["discount_paise"], o["shipping_paise"], o["total_paise"]) == (30_000, 5_000, 4_000, 29_000)


@pytest.mark.parametrize("items, shipping", [
    ([("BND-A", 1), ("BND-B", 1)], 4_000),   # 499.99 -> pays shipping
    ([("BND-B", 2)], 0),                     # 500.00 -> free
    ([("BND-B", 1), ("BND-C", 1)], 0),       # 500.01 -> free
])
def test_tc_prc_006_free_shipping_threshold_boundary(api, items, shipping):
    """TC-PRC-006: shipping is Rs 40.00 below Rs 500.00 and free from Rs 500.00."""
    assert api.place(items).json()["shipping_paise"] == shipping


@pytest.mark.parametrize("coupon", ["BOGUS", "save10", "SAVE 10", " SAVE10", ""])
def test_tc_prc_007_unknown_or_malformed_coupon_is_rejected(api, coupon):
    """TC-PRC-007: coupon codes are exact and case-sensitive; anything else returns 422."""
    assert api.place([("BND-B", 2)], coupon=coupon).status_code == 422


def test_tc_prc_008_total_identity_holds_for_every_coupon_case(api):
    """TC-PRC-008: total = subtotal - discount + shipping for a spread of orders."""
    cases = [([("NB-A5", 1)], None), ([("BND-B", 2)], "SAVE10"), ([("BND-B", 1), ("BND-D", 1)], "FLAT50"),
             ([("LAMP-01", 1), ("PEN-GEL", 3)], "SAVE10"), ([("BND-B", 1), ("BND-E", 1)], "SAVE10")]
    for items, coupon in cases:
        o = api.place(items, coupon=coupon).json()
        assert o["total_paise"] == o["subtotal_paise"] - o["discount_paise"] + o["shipping_paise"], (items, coupon, o)
