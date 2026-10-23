# Orderdesk requirements (specification used as the test oracle)

Orderdesk is a small order service written for this project, so the specification below is the author's, not a client's. Money is in INR, stored as integer paise.

| ID | Requirement |
|----|-------------|
| REQ-ORD-001 | `GET /api/products` lists every product with `sku`, `name`, `price_paise`, `stock`. |
| REQ-ORD-002 | `POST /api/orders` with a valid body returns 201 and the stored order (status `PLACED`, items, totals). |
| REQ-ORD-003 | `GET /api/orders/{id}` returns the stored order or 404. `GET /api/orders?status=X` filters; an unknown status is 422. |
| REQ-VAL-001 | `customer_email` must look like `local@domain.tld` (one `@`, a dot in the domain, no spaces, max 254 chars), otherwise 422. |
| REQ-VAL-002 | An order has 1 to 5 lines. Duplicate SKUs, unknown SKUs and non-integer quantities are 422. A rejected order changes nothing. |
| REQ-QTY-001 | Quantity per line is an integer from 1 to 10 inclusive. |
| REQ-STK-001 | Quantity above available stock is 409. Placing an order decrements stock; a rejected order leaves stock unchanged (all-or-nothing). |
| REQ-PRC-001 | `SAVE10` gives 10% off the subtotal when the subtotal is at least Rs 500.00 (inclusive). |
| REQ-PRC-002 | `FLAT50` gives Rs 50.00 off when the subtotal is at least Rs 300.00 (inclusive). |
| REQ-PRC-003 | An unknown, differently-cased or below-minimum coupon is rejected with 422 (never silently ignored). One coupon per order. |
| REQ-PRC-004 | Shipping is Rs 40.00 when the subtotal is below Rs 500.00, otherwise free. |
| REQ-PRC-005 | The shipping decision uses the subtotal **before** the discount. |
| REQ-PRC-006 | Percentage discounts round half up to the paisa. |
| REQ-PRC-007 | `total = subtotal - discount + shipping`. |
| REQ-LIF-001 | Lifecycle: `PLACED -> PAID -> SHIPPED -> DELIVERED`. Any other transition is 409 and leaves the status unchanged. |
| REQ-LIF-002 | `cancel` is allowed only from `PLACED` or `PAID`, and returns the quantities of every line to stock. |
| REQ-LIF-003 | Transitions on a missing order are 404; an unknown action is 404. |
| REQ-DAT-001 | Stored totals are internally consistent (`total = subtotal - discount + shipping`; `subtotal = sum(quantity x unit price)`). |
| REQ-DAT-002 | Stock is conserved: `stock + units in non-cancelled orders = initial stock`; stock is never negative; foreign keys are consistent. |
| REQ-UI-001 | The checkout page shows the catalogue with live stock, places orders, and shows the order summary exactly as the API returns it (subtotal, discount, shipping, total). |
| REQ-UI-002 | Validation errors from the API are shown to the user; the summary stays hidden. |
| REQ-UI-003 | The page can mark an order paid and cancel it, and the stock column refreshes after each action. |

Test fixtures: products `BND-A` (249.99), `BND-B` (250.00), `BND-C` (250.01), `BND-D` (50.00), `BND-E` (250.05) exist only so subtotals can land exactly on the thresholds and rounding edges above.
