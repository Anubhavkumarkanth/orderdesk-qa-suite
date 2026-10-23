# Orderdesk QA Suite: API, SQL and browser testing of an order service

[![ci](https://github.com/Anubhavkumarkanth/orderdesk-qa-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Anubhavkumarkanth/orderdesk-qa-suite/actions/workflows/ci.yml)

A small order-processing application (FastAPI + SQLite + one HTML checkout page) and the test suite I wrote for it: **86 automated tests across API, database and browser layers**, a written test plan, requirement-to-test traceability, and reproducible bug reports.

The application contains **8 defects that I seeded deliberately** and can switch on one at a time. That lets the repository show the whole defect cycle with real evidence: reproduce, report, fix, and prove a test now guards it.

> Honest framing: I wrote the application, the requirements, the defects and the tests. The suite catching all 8 defects shows its sensitivity to those kinds of faults. It does not show that I found bugs in software I did not write, and nothing here claims that.

![Checkout page under test](reports/screenshots/evidence-checkout-happy-path.png)

## Why this stack
I read nine fresher-level Data Analyst and QA postings in Bengaluru and across India (sources and method in [`docs/market-research.md`](docs/market-research.md)). In the three QA postings, manual testing with test cases and bug reports, Jira, and API testing (Postman or similar) appeared in all three, Selenium or Playwright in two, and SQL in two. So the project leads with test design and defect reports, adds API tests and SQL checks, and uses one browser-automation layer. Playwright was chosen because it installs and runs reliably here; Selenium is more common in those postings, and the concepts (locators, waits, page state) carry over, but I have not used Selenium in this project.

## Quick start
Python 3.10+ (developed on 3.12).

```bash
git clone https://github.com/Anubhavkumarkanth/orderdesk-qa-suite.git
cd orderdesk-qa-suite
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python -m pytest -v                                    # clean build: expect 86 passed
python scripts/defect_matrix.py                        # runs the suite once per seeded defect (about 2 minutes)
```

Run the app yourself: `uvicorn app.main:app` then open http://127.0.0.1:8000 (interactive API docs at `/docs`). Switch a defect on with `ORDERDESK_DEFECTS=BUG-004` (or `all`); unset it for the correct build. `ORDERDESK_TEST_MODE=1` enables the reset endpoint the tests use.

## What is tested
| Layer | Tests | Techniques | Folder |
|-------|------:|------------|--------|
| API | 72 | Boundary values (quantity, coupon minimums, free-shipping threshold), equivalence partitions (e-mail), state-transition table (12 invalid transitions), rounding edge case, all-or-nothing stock handling, negative cases | `tests/api/` |
| Database | 7 | SQL invariants after a mixed scenario: totals identity, subtotal = sum of items, stock conservation, no negative stock, FK consistency | `tests/db/` |
| Browser | 7 | Catalogue and stock display, order summary figures, coupon total, validation message, cancel flow, blocked cancel after shipping; screenshot saved on failure | `tests/ui/` |

(86 tests come from 44 test cases once parametrized; see [`docs/traceability.md`](docs/traceability.md).)

Documents: [requirements](docs/requirements.md) (the test oracle), [test plan](docs/test-plan.md), [test cases](docs/test-cases.md), [traceability](docs/traceability.md).

## Results
Recorded runs, Windows 11, Python 3.12, Chromium via Playwright:

- **Clean build:** `86 passed in 13.14s` ([full log](reports/results-clean-build.txt)).
- **Defect detection:** every seeded defect is caught by at least one test, and the clean build has zero failures ([matrix](reports/defect-matrix.md)).

| Defect | What is wrong | Caught by |
|--------|---------------|-----------|
| [BUG-001](docs/bugs/BUG-001.md) | Quantity 11 accepted (limit 10) | 1 test (boundary value 11) |
| [BUG-002](docs/bugs/BUG-002.md) | SAVE10 rejected at exactly Rs 500.00 | 3 tests |
| [BUG-003](docs/bugs/BUG-003.md) | Free shipping lost after a discount | 1 test |
| [BUG-004](docs/bugs/BUG-004.md) | Cancel does not return stock | 5 tests across API, SQL and browser |
| [BUG-005](docs/bugs/BUG-005.md) | Shipped order can be cancelled | 2 tests (API, browser) |
| [BUG-006](docs/bugs/BUG-006.md) | `user@nodot` accepted as e-mail | 1 test (one equivalence partition) |
| [BUG-007](docs/bugs/BUG-007.md) | Discount truncated, not rounded half up (1 paisa) | 1 test |
| [BUG-008](docs/bugs/BUG-008.md) | Checkout page total ignores the coupon | 1 browser test; the API tests all pass in that build |

Each bug report has steps, expected vs actual, the real request/response captured by `scripts/capture_evidence.py`, root cause, fix and the guarding test. BUG-008 also has before/after screenshots.

![BUG-008 caught by the browser test](reports/screenshots/evidence-BUG-008-detected-by-test.png)

## CI
GitHub Actions ([`ci.yml`](.github/workflows/ci.yml)) installs dependencies and Chromium, requires the clean build to be fully green, then runs the defect matrix and fails if any seeded defect goes undetected.

## Limitations
- **The defects and tests share an author.** Detection rates show the suite's sensitivity to these fault types, not how it would fare against defects I did not anticipate.
- Not covered: performance and load, security testing, accessibility auditing, cross-browser and mobile, concurrent orders (the app serialises writes with a lock, so a race is not tested), payments.
- Chromium only. No Selenium and no Postman collection in this project.
- The six manual cases in [`docs/test-cases.md`](docs/test-cases.md) are designed but **not executed**; no manual execution results are claimed.
- The specification is mine, written alongside the code, so it is a clean oracle rather than an ambiguous client document. Real requirements are rarely this tidy.
- Boundary fixtures (`BND-*` products) exist only to hit thresholds exactly; they would not exist in a real catalogue.

## Layout
```
app/        main.py (API)  pricing.py (rules)  db.py (SQLite)  defects.py (switches)  static/index.html
tests/      api/ db/ ui/  conftest.py (starts the real server, resets data per test)
docs/       requirements  test-plan  test-cases  traceability (generated)  bugs/ (8 reports + evidence)
scripts/    defect_matrix.py  capture_evidence.py  make_traceability.py  make_bug_reports.py
reports/    results-clean-build.txt  defect-matrix.md/json  screenshots/
```

MIT licensed.
