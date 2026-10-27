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
| REQ-STK-002 | When many customers order the last units at the same moment, exactly the available units are sold, everyone else gets 409, and stock never goes below 0. |
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
| REQ-DAT-003 | The full `customer_email` is never stored or returned. Orders keep only a masked copy: the first character of the name and of the domain, then `***`, then the last part of the domain (`anubhav@gmail.com` becomes `a***@g***.com`). |
| REQ-UI-001 | The checkout page shows the catalogue with live stock, places orders, and shows the order summary exactly as the API returns it (subtotal, discount, shipping, total). |
| REQ-UI-002 | Validation errors from the API are shown to the user; the summary stays hidden. |
| REQ-UI-003 | The page can mark an order paid and cancel it, and the stock column refreshes after each action. The payment line then shows the order's latest payment, such as a refund after a cancel. |
| REQ-UI-004 | The page works on a 360 px phone over a slow (3G) connection: the totals fit without sideways scrolling, a UPI payment shows `PENDING` until it settles, a decline shows its reason, and tapping Pay twice starts only one payment. |
| REQ-UI-005 | While a UPI payment is pending, the page keeps checking it: every 1.5 s for the first minute, then every 15 s. After a minute it says the bank has not answered yet and the customer should not pay again, and Pay stays disabled. If the connection drops, it says so and keeps checking the same payment, never starting a new one. |

Test fixtures: products `BND-A` (249.99), `BND-B` (250.00), `BND-C` (250.01), `BND-D` (50.00), `BND-E` (250.05) exist only so subtotals can land exactly on the thresholds and rounding edges above. `BND-UPI` (1,00,000.00) and `BND-P` (0.01) do the same for the UPI limit in REQ-PAY-012.

## UPI payments
Payments go through a pretend UPI provider (`app/upi_provider.py`); codes, rates and sources are in [`upi-failure-lab.md`](upi-failure-lab.md).

| ID | Requirement |
|----|-------------|
| REQ-PAY-001 | `POST /api/orders/{id}/payments` with a UPI ID (`name@handle`) starts a UPI collect request for the order total and returns the payment as `PENDING`. Only a `PLACED` order can be paid this way. A malformed UPI ID is 422. |
| REQ-PAY-002 | A payment ends `SUCCESS`, or `FAILED` with NPCI's error code and a plain-English reason. `SUCCESS` moves a `PLACED` order to `PAID`; `FAILED` leaves the order `PLACED` with its stock held. A final status never changes, except that money taken is returned: `SUCCESS` (or a late `SUCCESS` after `FAILED`) becomes `REFUND_PENDING` or `REFUNDED` (REQ-PAY-004, -009, -010). |
| REQ-PAY-003 | The provider's callback (`POST /api/payments/callback`) must be signed: `X-Upi-Signature` is the HMAC-SHA256 of the body. A missing or wrong signature is 401, an unknown payment 404, a `FAILED` without a known code (or a `SUCCESS` with one) 422, and none of them changes anything. A repeated callback is answered 200 but applied once, so an order is never charged or marked paid twice. |
| REQ-PAY-004 | A `SUCCESS` for an order that is no longer `PLACED` (cancelled, or paid another way) is refunded at once and changes nothing else, so a cancelled order never ships. Cancelling an order paid by UPI refunds the payment. |
| REQ-PAY-005 | `GET /api/payments/{id}` asks the provider for the latest status of a `PENDING` payment. `POST /api/payments/reconcile` does this for every `PENDING` payment and reports how many it checked, settled and left pending, so a lost callback cannot leave a payment pending once the bank has answered. Running it again changes nothing more. |
| REQ-PAY-006 | Retry rules: a new attempt is 409 while another is `PENDING`, once the order is paid, after 3 attempts, and after a `U16` risk-limit decline. After any other decline the customer may try again. |
| REQ-PAY-007 | The UPI ID is passed to the provider only; it is never stored or returned. |
| REQ-PAY-008 | The pretend provider uses NPCI's codes and meanings, and declines payments at UPI Pulse's 12-month payer's-bank rates: business declines 9.62%, technical declines 0.29%. |
| REQ-PAY-009 | A `SUCCESS` that arrives after the payment ended `FAILED` (for example a debit timeout, `U67`, that went through after all) is refunded, whether or not the customer has paid again meanwhile. The order is never charged twice. |
| REQ-PAY-010 | A refund counts only once the provider confirms it. Until then the payment is `REFUND_PENDING`, never `REFUNDED`, and `POST /api/payments/reconcile` asks again, reporting how many refunds it retried and how many are still pending. |
| REQ-PAY-011 | A signed `SUCCESS` callback must carry the payment's amount (`amount_paise`). A different or missing amount is 422 and the payment stays `PENDING`. |
| REQ-PAY-012 | An order above Rs 1,00,000.00, UPI's limit for one ordinary payment as reported in the news, cannot start a UPI payment: 422 with the reason, before any request reaches the provider. An order of exactly Rs 1,00,000.00 can pay. |
