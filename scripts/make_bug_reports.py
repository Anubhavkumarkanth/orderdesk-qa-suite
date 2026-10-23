"""Render docs/bugs/BUG-00x.md from the hand-written findings below plus the real evidence in docs/bugs/evidence/."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "docs" / "bugs"
E = B / "evidence"

BUGS = {
    "BUG-001": dict(
        title="Quantity of 11 is accepted although the limit is 10", sev="Medium", req="REQ-QTY-001", area="API / validation",
        steps=["Start the application and reset the data.",
               "`POST /api/orders` with `{\"customer_email\":\"qa@example.com\",\"items\":[{\"sku\":\"NB-A5\",\"quantity\":11}]}`."],
        expected="HTTP 422 `quantity for NB-A5 must be 1 to 10`.",
        actual="HTTP 201, order created for 11 units (total 132000 paise).",
        cause="`app/main.py` `create_order`: the upper bound becomes `MAX_QTY + 1` when the defect is on, an off-by-one in the limit.",
        fix="Compare against `MAX_QTY`.",
        guard="`tests/api/test_pricing_boundaries.py::test_tc_qty_001_quantity_boundaries[11-422]` (boundary value 11).",
        why="Boundary value analysis: the valid range is 1..10, so 0 and 11 are the first invalid values on each side."),
    "BUG-002": dict(
        title="SAVE10 rejected at exactly Rs 500.00", sev="High", req="REQ-PRC-001", area="API / pricing",
        steps=["Reset the data.", "`POST /api/orders` with 2 x `BND-B` (Rs 250.00 each, subtotal Rs 500.00) and `\"coupon\":\"SAVE10\"`."],
        expected="HTTP 201, discount 5000 paise, total 45000 paise (the minimum is inclusive).",
        actual="HTTP 422 `coupon minimum not met`.",
        cause="`app/pricing.py` `discount_for`: the minimum check uses `subtotal <= minimum` instead of `subtotal < minimum` for SAVE10, so the boundary value itself fails.",
        fix="Reject only when `subtotal < minimum`.",
        guard="`test_tc_prc_001_save10_minimum_subtotal_boundary`, `test_tc_prc_002_save10_at_exact_minimum_gives_free_shipping_and_correct_total` and `test_tc_prc_008_total_identity_holds_for_every_coupon_case` in `tests/api/test_pricing_boundaries.py`.",
        why="Customers who hit the threshold exactly lose a promised discount; tests at 499.99 / 500.00 / 500.01 exist for this reason."),
    "BUG-003": dict(
        title="Shipping charged on a Rs 500.00 order after SAVE10 is applied", sev="High", req="REQ-PRC-005", area="API / pricing",
        steps=["Reset the data.", "`POST /api/orders` with 2 x `BND-B` and coupon `SAVE10`."],
        expected="shipping 0, total 45000 paise (the free-shipping decision uses the pre-discount subtotal of 50000).",
        actual="shipping 4000, total 49000 paise: the customer is charged Rs 40.00 shipping they should not pay.",
        cause="`app/pricing.py` `price_order`: the shipping basis is `subtotal - discount` instead of `subtotal`.",
        fix="Use the pre-discount subtotal as the basis.",
        guard="`tests/api/test_pricing_boundaries.py::test_tc_prc_002_save10_at_exact_minimum_gives_free_shipping_and_correct_total`.",
        why="A discount silently removing free shipping is a classic interaction defect between two individually correct rules."),
    "BUG-004": dict(
        title="Cancelling an order does not return stock", sev="High", req="REQ-LIF-002", area="API / inventory",
        steps=["Reset the data (NB-A5 stock is 50).", "Place an order for 3 x `NB-A5`.", "`POST /api/orders/{id}/cancel`.", "`GET /api/products` and read NB-A5 stock."],
        expected="stock is 50 again.",
        actual="stock is 47: three units are lost from inventory on every cancellation.",
        cause="`app/main.py` `transition`: the `UPDATE products SET stock = stock + ...` statement is skipped for `cancel`.",
        fix="Restore the quantity of every order line when an order is cancelled.",
        guard="`test_tc_lif_004_*`, `test_tc_lif_005_*` (API), `tests/db/test_db_integrity.py::test_tc_dat_003_stock_is_conserved` (SQL), `tests/ui/test_checkout_ui.py::test_tc_ui_006_*` (browser).",
        why="Caught independently at three layers; the SQL conservation check (`stock + held units = initial stock`) needs no knowledge of the API."),
    "BUG-005": dict(
        title="A shipped order can be cancelled", sev="High", req="REQ-LIF-002", area="API / state machine",
        steps=["Reset the data.", "Place an order, then `pay` and `ship` it.", "`POST /api/orders/{id}/cancel`."],
        expected="HTTP 409 `cannot cancel an order that is SHIPPED`; status stays SHIPPED.",
        actual="HTTP 200, status `CANCELLED`, although the goods have left.",
        cause="`app/main.py` `transition`: `SHIPPED` is added to the allowed source states of `cancel`.",
        fix="Allow `cancel` only from PLACED and PAID.",
        guard="`tests/api/test_order_lifecycle.py::test_tc_lif_003_cancel_is_only_allowed_before_shipping[SHIPPED]`, `tests/ui/test_checkout_ui.py::test_tc_ui_007_*`.",
        why="State-transition testing: every (state, action) pair outside the allowed set must be rejected."),
    "BUG-006": dict(
        title="E-mail without a domain dot is accepted", sev="Low", req="REQ-VAL-001", area="API / validation",
        steps=["Reset the data.", "`POST /api/orders` with `customer_email` `user@nodot` and one valid line."],
        expected="HTTP 422 `invalid customer_email`.",
        actual="HTTP 201, order stored for `user@nodot`.",
        cause="`app/main.py`: the pattern used when the defect is on is `^[^@\\s]+@[^@\\s]+$`, which does not require a dot in the domain.",
        fix="Use `^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$`.",
        guard="`tests/api/test_orders_api.py::test_tc_val_001_invalid_email_is_rejected[user@nodot]`.",
        why="Equivalence partitioning of invalid e-mails: the other six invalid partitions were still rejected, so only this one slipped through."),
    "BUG-007": dict(
        title="Percentage discount truncated instead of rounded half up", sev="Medium", req="REQ-PRC-006", area="API / pricing",
        steps=["Reset the data.", "`POST /api/orders` with `BND-B` + `BND-E` (subtotal Rs 500.05) and coupon `SAVE10`."],
        expected="discount 5001 paise (10% of 50005 = 5000.5, rounded half up), total 45004.",
        actual="discount 5000, total 45005: the customer is over-charged one paisa.",
        cause="`app/pricing.py` `_percent_of`: integer floor division `amount * pct // 100` instead of adding 50 before dividing.",
        fix="`(amount * pct + 50) // 100`.",
        guard="`tests/api/test_pricing_boundaries.py::test_tc_prc_003_percentage_discount_rounds_half_up[items1-5001]`.",
        why="A one-paisa error is invisible in casual checks; it needs a fixture price whose 10% lands exactly on .5 paise."),
    "BUG-008": dict(
        title="Checkout page shows a total that ignores the coupon", sev="High", req="REQ-UI-001", area="UI",
        steps=["Open the checkout page.", "Enter quantity 1 for `BND-B` and `BND-D` (Rs 300.00), e-mail `qa@example.com`, coupon `FLAT50`.", "Click Place order and read `Total`."],
        expected="`Total: Rs 290.00` (300.00 - 50.00 + 40.00 shipping), the same as the API.",
        actual="`Total: Rs 340.00`: the page adds subtotal and shipping but omits the discount, while the API and database hold 290.00.",
        cause="`app/static/index.html` `render()`: when the defect is on, the displayed total is `subtotal_paise + shipping_paise` instead of `order.total_paise`.",
        fix="Display `order.total_paise`.",
        guard="`tests/ui/test_checkout_ui.py::test_tc_ui_003_coupon_discount_is_reflected_in_the_total`. The API tests pass in this build, which is why a browser test is needed.",
        why="UI and API disagree; only an end-to-end check sees what the customer sees."),
}

for bug_id, v in BUGS.items():
    evidence = json.loads((E / f"{bug_id}.json").read_text())
    evidence_text = json.dumps({k: x for k, x in evidence.items() if k != "bug"}, indent=2)
    images = ""
    if bug_id == "BUG-008":
        images = "\n![clean build](evidence/BUG-008-clean.png)\n![defective build](evidence/BUG-008-defective.png)\n"
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(v["steps"], 1))
    (B / f"{bug_id}.md").write_text(f"""# {bug_id}: {v['title']}

| Field | Value |
|---|---|
| Severity | {v['sev']} |
| Component | {v['area']} |
| Requirement | {v['req']} |
| Origin | **Seeded deliberately** (`ORDERDESK_DEFECTS={bug_id}`); not a defect in third-party software |
| Status | Fixed in the clean build; guarded by the tests below |

## Steps to reproduce
{steps}

## Expected
{v['expected']}

## Actual
{v['actual']}

## Evidence
Captured by `scripts/capture_evidence.py` from a clean build and a defective build (`docs/bugs/evidence/{bug_id}.json`):

```json
{evidence_text}
```
{images}
## Root cause
{v['cause']}

## Fix and verification
{v['fix']} Verified: the guarding test(s) fail with the defect on and pass on the clean build (see `reports/defect-matrix.md`).

Guarded by: {v['guard']}

## Why this test design catches it
{v['why']}
""", encoding="utf-8")
print("wrote", len(BUGS), "bug reports")
