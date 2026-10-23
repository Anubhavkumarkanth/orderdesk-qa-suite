"""Pricing rules (REQ-PRC-*). All money is integer paise so no floating point error reaches a total."""
from dataclasses import dataclass

from . import defects

FREE_SHIPPING_THRESHOLD = 50_000   # Rs 500.00
SHIPPING_FEE = 4_000               # Rs 40.00
COUPONS = {
    # code: (kind, minimum subtotal in paise, value)
    "SAVE10": ("percent", 50_000, 10),
    "FLAT50": ("flat", 30_000, 5_000),
}


class CouponError(ValueError):
    pass


@dataclass(frozen=True)
class Totals:
    subtotal: int
    discount: int
    shipping: int
    total: int


def _percent_of(amount: int, pct: int) -> int:
    if defects.on("BUG-007"):
        return amount * pct // 100                      # truncates: Rs 0.01 error on some totals
    return (amount * pct + 50) // 100                   # round half up (REQ-PRC-006)


def discount_for(coupon: str | None, subtotal: int) -> int:
    if coupon is None:
        return 0
    rule = COUPONS.get(coupon)
    if rule is None:
        raise CouponError("unknown coupon")
    kind, minimum, value = rule
    below = subtotal <= minimum if (defects.on("BUG-002") and coupon == "SAVE10") else subtotal < minimum
    if below:
        raise CouponError("coupon minimum not met")
    return _percent_of(subtotal, value) if kind == "percent" else value


def price_order(subtotal: int, coupon: str | None) -> Totals:
    discount = discount_for(coupon, subtotal)
    basis = subtotal - discount if defects.on("BUG-003") else subtotal   # REQ-PRC-005: basis is the pre-discount subtotal
    shipping = 0 if basis >= FREE_SHIPPING_THRESHOLD else SHIPPING_FEE
    return Totals(subtotal, discount, shipping, subtotal - discount + shipping)
