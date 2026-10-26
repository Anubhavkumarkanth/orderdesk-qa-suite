# UPI payment failure lab

The checkout can take payment by UPI through a **pretend UPI provider** (`app/upi_provider.py`). It moves no money. It answers the way a gateway does: every request starts pending, then succeeds or fails with a real NPCI error code, at real-world rates. The tests in `tests/api/test_upi_payments.py`, `tests/api/test_flash_sale.py`, `tests/db/` and `tests/ui/` use it to check what a shop most often gets wrong with UPI.

Checked 2026-10-27.

## Failure codes

Each code and its meaning were checked against NPCI's **Unified Payments Interface: Error and Response Codes, version 2.9** (17 Jan 2024). npci.org.in blocks scripted requests, so I read the copy that [Juspay's documentation links to as NPCI's document](https://docs.juspay.io/upi-merchant-stack/docs/resources/codes-guide) ([PDF](https://dth95m2xtyv8v.cloudfront.net/tesseract/assets/upi-tpap-sdk/UPI_Error_and_Response_Codes_2_9-HHLrJ.pdf)). Section 3.1 lists codes sent by the banks, and section 4.4 lists errors from NPCI's UPI service layer. TD means technical decline (the bank's or network's systems failed); BD means business decline (a normal "no").

| Code | NPCI description (v2.9) | Section | NPCI label | Shown to the customer |
|------|-------------------------|---------|-----------|------------------------|
| ZM | INVALID MPIN | 3.1 | BD | Wrong UPI PIN |
| Z9 | INSUFFICIENT FUNDS IN CUSTOMER (REMITTER) ACCOUNT | 3.1 | BD | Not enough money in the account |
| U16 | RISK THRESHOLD EXCEEDED | 4.4 | BD | UPI risk limit reached. Try later or use another method |
| U69 | COLLECT EXPIRED | 4.4 | BD | The payment request expired before it was approved |
| U30 | DEBIT HAS BEEN FAILED | 4.4 | NA | Your bank could not debit the account |
| U67 | DEBIT TIMEOUT | 4.4 | TD | Your bank did not answer in time |

- **U30 is labelled NA by NPCI:** whether it is technical or business depends on the bank's own response code that comes with it. The lab treats it as a bank outage, such as XY "REMITTER CBS OFFLINE" (TD in section 3.1), so it counts as technical.
- **U69 is a collect request** that expired before the customer approved it. The pretend provider uses the collect flow: the shop sends a request to the customer's UPI app and waits.

## Failure rates

The rates come from [UPI Pulse](https://anubhavkumarkanth.github.io/upi-pulse/) ([data.json](https://anubhavkumarkanth.github.io/upi-pulse/data.json), built 2026-10-26), which tracks NPCI's monthly Top 50 Member Performance figures. All six codes are failures on the payer's side, so the lab uses NPCI's remitter (payer's bank) table, averaged over UPI Pulse's last 12 months (Oct 2025 to Sep 2026) and weighted by number of payments. `python scripts/upi_rates.py` recomputes them.

| Outcome | Rate | Per 10,000 payments |
|---------|-----:|--------------------:|
| Approved | 90.09% | about 9,009 |
| Business declines (ZM, Z9, U16, U69) | 9.62% | about 962 |
| Technical declines (U30, U67) | 0.29% | about 29 (1 in 345) |

NPCI does not publish declines by code, so the lab splits each group evenly between its codes. That split is an assumption; the two group totals are data.

## Sandbox UPI IDs

Like a gateway's test mode, these UPI IDs fix the outcome: `success@sandbox`, `pending@sandbox` (the bank never answers), and `zm@sandbox`, `z9@sandbox`, `u16@sandbox`, `u69@sandbox`, `u30@sandbox`, `u67@sandbox`. Any other well-formed UPI ID gets a random outcome at the rates above. The UPI ID goes to the provider and is never stored (REQ-PAY-007).

## Payment states

```
PENDING --provider says SUCCESS, order still PLACED-----------> SUCCESS --order cancelled--> REFUNDED
PENDING --provider says SUCCESS, order cancelled or paid-------> REFUNDED
PENDING --provider says FAILED, with a code--------------------> FAILED   (the customer may try again)
```

The answer arrives in one of three ways, and all three use the same code, which applies only the first answer:

- **Callback:** the provider posts to `POST /api/payments/callback`, signed with HMAC-SHA256 in `X-Upi-Signature`.
- **Status check:** `GET /api/payments/{id}`. The checkout page polls it every 1.5 seconds.
- **Reconciliation:** `POST /api/payments/reconcile` checks every pending payment, for when a callback is lost.

On the live app the callback secret is random at each start, so payments there settle through the page's status checks.

## Risk ranking

New test cases are ranked by **how often the problem happens x how much it hurts**. Frequency uses UPI Pulse where NPCI's figures cover the problem and an assumption where they don't; each row says which.

**Frequency (F):**

| F | How often |
|---|-----------|
| 5 | about 1 payment in 10 or more often (approvals; business declines) |
| 4 | about 1 in 100 to 1 in 1,000 (technical declines: 1 in 345) |
| 3 | rarer than technical declines, but weekly for a busy shop (assumed) |
| 2 | occasional, such as only during a sale (assumed) |
| 1 | only when someone attacks the shop (assumed) |

**Impact (I):**

| I | What it costs |
|---|---------------|
| 5 | the customer loses money: charged twice, charged with no confirmed order, or charged for a cancelled order |
| 4 | the shop loses money or trust: stock oversold, or personal data stored |
| 3 | the customer cannot finish paying, or is not told why |
| 2 | a bad entry is accepted, or a message is unclear |

Ties are broken by impact, then by data-backed frequency before assumed frequency.

| Rank | Test case | What goes wrong in real life | F | Frequency basis | I | F x I |
|-----:|-----------|------------------------------|--:|-----------------|--:|------:|
| 1 | TC-PAY-004 | A paid order is not marked paid | 5 | 90.09% of payments are approved (UPI Pulse) | 5 | 25 |
| 2 | TC-PAY-012 | A second attempt starts while one is pending, or a retry that cannot succeed is allowed | 5 | each of the 9.62% business declines ends in a retry decision (UPI Pulse) | 5 | 25 |
| 3 | TC-PAY-010 | A payment stays pending for ever because its callback was lost | 4 | at most the 0.29% technical declines, which include debit timeouts (UPI Pulse) | 5 | 20 |
| 4 | TC-PAY-001 | The customer's UPI ID is stored | 5 | every payment (UPI Pulse volumes) | 4 | 20 |
| 5 | TC-PAY-005 | A repeated callback charges or ships twice | 3 | assumed: gateways resend callbacks the shop is slow to acknowledge; NPCI does not publish this | 5 | 15 |
| 6 | TC-PAY-006 | Two Pay requests at once start two payments | 3 | assumed | 5 | 15 |
| 7 | TC-PAY-008 | A late success after cancel is kept, or the order ships | 3 | assumed: a part of the 0.29% where the customer also gives up | 5 | 15 |
| 8 | TC-PAY-009 | Cancelling a UPI-paid order keeps the money | 3 | assumed | 5 | 15 |
| 9 | TC-UI-008 | A double tap on a slow phone starts two payments, or the totals do not fit the screen | 3 | assumed | 5 | 15 |
| 10 | TC-DAT-008 | Stored payments show a double charge or a wrong amount | 3 | assumed: the SQL backstop for ranks 5 to 8 | 5 | 15 |
| 11 | TC-PAY-003 | A decline leaves the order in a wrong state or gives no reason | 5 | 9.91% of payments are declined (UPI Pulse) | 3 | 15 |
| 12 | TC-PAY-011 | A customer who fixed the problem cannot try again | 5 | 9.62% business declines (UPI Pulse) | 3 | 15 |
| 13 | TC-UI-009 | The page hides the reason for a decline | 5 | 9.62% business declines (UPI Pulse) | 3 | 15 |
| 14 | TC-STK-003 | A flash sale oversells the last units | 2 | assumed: only during sales | 4 | 8 |
| 15 | TC-PAY-002 | A malformed UPI ID is accepted | 3 | assumed | 2 | 6 |
| 16 | TC-PAY-007 | A forged callback marks an order paid | 1 | assumed | 5 | 5 |

TC-UPI-001 and TC-UPI-002 check the pretend provider itself, not the shop, so they are not ranked.

**How the ranking is used:** it set the order in which these tests were written. If CI time ever forces a smaller smoke pack, the top of the list goes in first. Today every test runs in every CI build, and the security and privacy checks (ranks 4 and 16) stay in whatever their rank.

## Mobile on 3G

TC-UI-008 runs the checkout on a 360 px touch screen with Chromium's network throttled to Puppeteer's ["Fast 3G" preset](https://github.com/puppeteer/puppeteer/blob/main/packages/puppeteer-core/src/cdp/PredefinedNetworkConditions.ts), which Puppeteer describes as generally aligned with DevTools: 562.5 ms round trip, about 1.44 Mbit/s down and 0.68 Mbit/s up. The CPU is slowed 4 times. It is emulation in desktop Chromium, not a real phone.

## Can the new tests fail?

Before opening the pull request I broke the code once per check, ran the test meant to catch it, and put the code back. Each of these 18 broken builds made its test fail:

| Broken on purpose | Caught by |
|-------------------|-----------|
| The UPI ID is echoed back in the reply | TC-PAY-001 |
| UPI IDs are not validated | TC-PAY-002 |
| A decline marks the order paid | TC-PAY-003 |
| A success does not mark the order paid | TC-PAY-004 |
| Callbacks are applied every time, not once | TC-PAY-005 |
| No "one attempt at a time" rule | TC-PAY-006 |
| No signature check on callbacks | TC-PAY-007 |
| A late success is kept instead of refunded | TC-PAY-008, and TC-DAT-008 in SQL |
| Cancelling a paid order does not refund it | TC-PAY-009 |
| Reconciliation does nothing | TC-PAY-010 |
| No retry allowed after any decline | TC-PAY-011 |
| Retries allowed after U16 | TC-PAY-012 |
| Orders placed without the lock | TC-STK-003 |
| The page's double-tap guards removed | TC-UI-008 |
| The page hides the decline reason | TC-UI-009 |
| The rate split adds up wrongly | TC-UPI-001 |
| A code's NPCI description changed | TC-UPI-002 |

The page has two double-tap guards, a flag and a disabled button. Removing only the flag was not caught, because the disabled button still stopped the second tap; removing both was. These broken builds were one-off checks, not seeded defects, so CI does not repeat them.

## Honest limits

- The provider is simulated. Only its codes (NPCI) and its two group rates (UPI Pulse) come from real sources.
- NPCI publishes monthly bank totals, not single payments, so it cannot say how often callbacks repeat or customers double-tap. Those frequencies are marked as assumed.
- Refunds always succeed at once here. A real gateway can report a refund as pending or failed.
- These checks were written by the same person as the payment code, the same limit the README states for the seeded defects.
