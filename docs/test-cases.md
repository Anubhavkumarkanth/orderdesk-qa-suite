# Test cases

## Automated cases
62 automated test cases (124 test runs once parametrized) are listed with their requirement and test function in [`traceability.md`](traceability.md), which is generated from the code. Case IDs follow `TC-<area>-<number>`: ORD order flow, VAL validation, QTY quantity, STK stock, PRC pricing, LIF lifecycle, DAT data (SQL), UI browser, PAY UPI payments, UPI the pretend provider itself. The payment, race and mobile cases are ranked by risk in [`upi-failure-lab.md`](upi-failure-lab.md).

Format used for the designed examples below: **ID, priority, precondition, steps, expected result, technique**.

## Worked examples (design level)

| ID | Pri | Precondition | Steps | Expected | Technique |
|----|-----|--------------|-------|----------|-----------|
| TC-QTY-001 | High | Seeded data | Order `NB-A5` with quantity -1, 0, 1, 10, 11 | 422, 422, 201, 201, 422; no stock change on 422 | Boundary value analysis |
| TC-PRC-001 | High | Seeded data | Order subtotals of 499.99, 500.00, 500.01 with `SAVE10` | 422, 201 (discount 50.00), 201 (discount 50.00) | Boundary value analysis |
| TC-PRC-003 | Med | Seeded data | Order subtotal 500.05 with `SAVE10` | Discount 50.01 (half up), total 450.04 | Rounding edge case |
| TC-VAL-001 | Med | Seeded data | Submit e-mails: `plainaddress`, `@no-local.com`, `no-at.com`, `user@nodot`, `a b@c.com`, empty, `x@@y.com` | Each 422; no order created | Equivalence partitioning (invalid classes) |
| TC-LIF-002 | High | One order in each status | Apply every action that is not an allowed transition | 409 and status unchanged | State-transition testing |
| TC-DAT-003 | High | Mixed scenario (placed, paid, shipped, cancelled orders) | SQL: stock + units in non-cancelled orders = initial stock for each SKU | No row differs | Data invariant |
| TC-UI-003 | High | Checkout page open | Quantity 1 of `BND-B` and `BND-D`, coupon `FLAT50`, Place order | Summary shows discount -Rs 50.00 and total Rs 290.00 | End-to-end, oracle from requirements |
| TC-PAY-005 | High | A `PLACED` order with a pending UPI payment | Send the same signed `SUCCESS` callback 5 times at once, then once more, then a `FAILED U67` for the same payment | Every reply 200; payment `SUCCESS`; order `PAID`; exactly one `SUCCESS` row | Idempotency, concurrency |
| TC-PAY-008 | High | A pending UPI payment | Cancel the order, then send a signed `SUCCESS` callback | Payment `REFUNDED`; order stays `CANCELLED`; ship returns 409; stock back to 50 | State-transition, out-of-order event |
| TC-STK-003 | Med | `BAG-01` has 5 units | 500 buyers order 1 each at once (50 threads) | Exactly 5 x 201 and 495 x 409; stock 0; no 500s | Concurrency, data invariant |

## Manual cases (designed, NOT yet executed)
These need a human at a browser. They are written and ready but have **not** been run, so no result is recorded. Running them and logging results in a table like the one in `reports/` is the next step for a person.

| ID | Pri | Steps | Expected |
|----|-----|-------|----------|
| TC-MAN-001 | Med | Tab through the checkout page with the keyboard only and place an order | Every control is reachable in a sensible order; the Place order button works with Enter/Space |
| TC-MAN-002 | Low | Enter a quantity with the browser's spinner above stock, then place the order | A clear message is shown (409 text); the page remains usable |
| TC-MAN-003 | Low | Resize the window to 360 px wide | No horizontal scroll that hides the totals (also checked automatically on an emulated phone by TC-UI-008) |
| TC-MAN-004 | Med | Place an order, reload the page | Catalogue stock reflects the order; the summary is gone (expected: it is not persisted client-side) |
| TC-MAN-005 | Low | Paste an e-mail with leading/trailing spaces | Spaces are trimmed by the page and the order is accepted |
| TC-MAN-006 | Med | Double-click Place order quickly | Observe whether two orders are created (not specified in the requirements; log as a question, not a defect) |
