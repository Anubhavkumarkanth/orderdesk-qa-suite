# Test plan: Orderdesk

## 1. Objective
Show that the order service meets `docs/requirements.md` and that the suite would notice the kinds of defects that commonly reach production in order systems: boundary errors, pricing arithmetic, state-machine violations, stock bookkeeping, UI/API disagreement, and UPI payments that are charged twice, stay pending or succeed after a cancel.

## 2. Scope
**In scope:** the HTTP API, the persisted SQLite data, and the single-page checkout UI of a self-written application under test; UPI payment handling against a pretend provider (`docs/upi-failure-lab.md`); many buyers ordering the last units at once; the checkout on an emulated phone over throttled 3G.
**Out of scope:** performance and load, security testing beyond callback signatures, accessibility auditing, cross-browser testing and real phones, a real payment gateway (the provider is simulated), deployment. These are real gaps, listed again under Limitations in the README.

## 3. Approach
| Layer | Technique | Tooling | Location |
|-------|-----------|---------|----------|
| API | Black-box functional, negative, equivalence partitioning, boundary value analysis, state-transition testing | pytest + requests against a live server started by the suite | `tests/api/` |
| Data | SQL invariants on the stored rows after a mixed scenario | pytest + sqlite3 (read-only) | `tests/db/` |
| UI | End-to-end checks through the browser, with a failure screenshot saved automatically; runs on a 360 px touch screen over throttled 3G, one of them going offline mid-payment; a bank slower than a minute, using Playwright's fake clock | pytest + Playwright (Chromium) | `tests/ui/` |
| Payments | State-transition testing of payment states, repeated and forged callbacks, concurrency (double taps, 500 buyers for 5 units), retry rules, reconciliation, late and wrong-amount answers, refunds that fail, the UPI limit | pytest + requests; the suite plays the provider | `tests/api/test_upi_payments.py`, `tests/api/test_flash_sale.py` |
| Simulator | Checks that the pretend provider's codes match NPCI and its rates match UPI Pulse | pytest, in process | `tests/unit/` |
| Regression | The whole suite is the regression pack; `scripts/defect_matrix.py` re-runs it per defect | pytest, GitHub Actions | `.github/workflows/ci.yml` |

Design choices:
- Each test starts from a freshly seeded database (test-mode reset endpoint), so tests do not depend on order.
- Expected values are written down from the requirements, not copied from the application's output.
- Boundary values use dedicated fixture products so a subtotal can sit exactly on, one paisa below, and one paisa above a threshold.
- Payment tests act as the provider: sandbox UPI IDs fix each outcome, and callbacks are signed with a test-only secret.
- Payment cases are ranked by real-world frequency x impact, using UPI Pulse's NPCI figures where they apply (`docs/upi-failure-lab.md`).
- Each new payment, race, mobile and simulator test was shown to fail on a deliberately broken build before it was trusted (same document).

## 4. Entry and exit criteria
- Entry: application starts and `/api/health` answers.
- Exit for a build: 100% of automated tests pass with no defects switched on; each seeded defect is caught by at least one test (`reports/defect-matrix.md`).

## 5. Test data and environment
Python 3.12, SQLite, Chromium via Playwright, Windows 11 for the recorded run and Ubuntu in CI. Seeded products are in `app/db.py`. Sandbox UPI IDs, NPCI codes and UPI Pulse rates are in `docs/upi-failure-lab.md`.

## 6. Defect management
Defects are written up in `docs/bugs/` with steps, expected vs actual, evidence captured by `scripts/capture_evidence.py`, root cause and the test that now guards the fix. The eight defects in this project were **seeded deliberately** (`app/defects.py`, switched by `ORDERDESK_DEFECTS`); none was found in someone else's software.

## 7. Risks
| Risk | Mitigation |
|------|------------|
| The suite and the defects were written by the same person, so detection rates flatter the suite | Stated in the README; the matrix shows what is caught, not what a stranger's bugs would be |
| UI tests are slower and more fragile than API tests | Only user-visible behaviour is covered in the UI layer (11 tests); rules are tested at API level |
| Single browser | Chromium only, and the phone is emulated; noted as a gap |
| The pretend provider behaves more neatly than a real gateway | Its codes come from NPCI and its rates from UPI Pulse; what it simplifies is listed in `docs/upi-failure-lab.md` |
| A race test can pass by luck of timing | 500 requests over 50 threads; with the order lock removed it failed |

## 8. Deliverables
Test cases (`docs/test-cases.md`), automated suite (`tests/`), traceability (`docs/traceability.md`, generated), results (`reports/`), bug reports (`docs/bugs/`), UPI failure lab and risk ranking (`docs/upi-failure-lab.md`).
