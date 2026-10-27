"""UPI payment tests against the pretend provider (REQ-PAY-*). Ranked by risk in docs/upi-failure-lab.md.

The suite plays the provider's side: sandbox UPI IDs fix each outcome, and callbacks are signed with the test secret.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.api

CODES = ["ZM", "Z9", "U16", "U69", "U30", "U67"]
NO_REFUNDS = {"refunds_retried": 0, "refunds_still_pending": 0}


def _order(api, qty=2):
    return api.place([("NB-A5", qty)]).json()


def _fail(api, oid, code):
    """One payment attempt that the payer's bank declines with `code`, settled by a status check."""
    p = api.pay(oid, f"{code.lower()}@sandbox").json()
    return api.get(f"/api/payments/{p['id']}").json()


def test_tc_pay_001_payment_starts_pending_and_the_upi_id_is_never_stored(api, db_path):
    """TC-PAY-001: a UPI payment starts PENDING for the order total; the UPI ID is neither returned nor stored."""
    order = _order(api)
    r = api.pay(order["id"], "anubhav.k@okaxis")
    assert r.status_code == 201
    p = r.json()
    assert (p["order_id"], p["status"], p["amount_paise"], p["code"]) == (order["id"], "PENDING", order["total_paise"], None)
    assert "anubhav.k" not in r.text
    assert b"anubhav.k" not in db_path.read_bytes()
    assert api.get(f"/api/orders/{order['id']}").json()["status"] == "PLACED"


@pytest.mark.parametrize("upi_id", ["", "no-at-sign", "a@", "@okaxis", "a b@okaxis"])
def test_tc_pay_002_invalid_upi_id_is_rejected(api, upi_id):
    """TC-PAY-002: a malformed UPI ID returns 422 and starts no payment."""
    oid = _order(api)["id"]
    assert api.pay(oid, upi_id).status_code == 422
    assert api.get(f"/api/orders/{oid}/payments").json() == []


@pytest.mark.parametrize("code", CODES)
def test_tc_pay_003_each_decline_code_fails_the_payment_and_keeps_the_order(api, code):
    """TC-PAY-003: each NPCI decline code ends the payment FAILED with that code and a reason; the order stays PLACED with its stock held."""
    oid = _order(api, qty=3)["id"]
    p = _fail(api, oid, code)
    assert (p["status"], p["code"]) == ("FAILED", code) and p["reason"]
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PLACED"
    assert api.stock("NB-A5") == 47


def test_tc_pay_004_successful_payment_marks_the_order_paid(api):
    """TC-PAY-004: a status check that finds SUCCESS marks the order PAID, which can then ship."""
    oid = _order(api)["id"]
    p = api.pay(oid).json()
    assert api.get(f"/api/payments/{p['id']}").json()["status"] == "SUCCESS"
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PAID"
    assert api.post(f"/api/orders/{oid}/ship").status_code == 200


def test_tc_pay_005_repeated_callbacks_are_applied_once(api, db):
    """TC-PAY-005: the same SUCCESS callback sent 5 times at once and again later is acknowledged each time but pays the order once."""
    oid = _order(api)["id"]
    txn = api.pay(oid).json()["provider_txn"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        replies = list(pool.map(lambda _: api.callback(txn, "SUCCESS"), range(5)))
    replies += [api.callback(txn, "SUCCESS"), api.callback(txn, "FAILED", "U67")]  # a late, contradicting repeat changes nothing
    assert [r.status_code for r in replies] == [200] * 7
    assert {r.json()["status"] for r in replies} == {"SUCCESS"}
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PAID"
    assert db.execute("SELECT COUNT(*) FROM payments WHERE order_id = ? AND status = 'SUCCESS'", (oid,)).fetchone()[0] == 1


def test_tc_pay_006_two_pay_requests_at_once_start_one_payment(api):
    """TC-PAY-006: two Pay requests for one order at the same moment start one payment; the other gets 409."""
    oid = _order(api)["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(r.status_code for r in pool.map(lambda _: api.pay(oid), range(2)))
    assert codes == [201, 409]
    assert len(api.get(f"/api/orders/{oid}/payments").json()) == 1


@pytest.mark.parametrize("case, status, code, secret, expected", [
    ("no signature", "SUCCESS", None, None, 401),
    ("wrong secret", "SUCCESS", None, "guessed-secret", 401),
    ("unknown transaction", "SUCCESS", None, "test-only-upi-secret", 404),
    ("FAILED without a code", "FAILED", None, "test-only-upi-secret", 422),
])
def test_tc_pay_007_bad_callbacks_are_rejected_and_change_nothing(api, case, status, code, secret, expected):
    """TC-PAY-007: an unsigned, wrongly signed, unknown or malformed callback is rejected and the payment stays PENDING."""
    oid = _order(api)["id"]
    p = api.pay(oid).json()
    txn = "PUPI-NOT-ISSUED" if case == "unknown transaction" else p["provider_txn"]
    assert api.callback(txn, status, code, secret=secret).status_code == expected
    assert api.get(f"/api/orders/{oid}/payments").json()[0]["status"] == "PENDING"
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PLACED"


@pytest.mark.parametrize("meanwhile, order_status", [("cancel", "CANCELLED"), ("pay", "PAID")])
def test_tc_pay_008_late_success_is_refunded_not_shipped(api, meanwhile, order_status):
    """TC-PAY-008: a SUCCESS that arrives after the order was cancelled (or paid another way) is refunded and nothing extra ships."""
    oid = _order(api, qty=3)["id"]
    txn = api.pay(oid).json()["provider_txn"]
    assert api.post(f"/api/orders/{oid}/{meanwhile}").status_code == 200
    assert api.callback(txn, "SUCCESS").json()["status"] == "REFUNDED"
    assert api.get(f"/api/orders/{oid}").json()["status"] == order_status
    if meanwhile == "cancel":
        assert api.post(f"/api/orders/{oid}/ship").status_code == 409
        assert api.stock("NB-A5") == 50


def test_tc_pay_009_cancelling_a_upi_paid_order_refunds_it(api):
    """TC-PAY-009: cancelling an order that was paid by UPI refunds the payment."""
    oid = _order(api)["id"]
    p = api.pay(oid).json()
    api.callback(p["provider_txn"], "SUCCESS")
    assert api.post(f"/api/orders/{oid}/cancel").json()["status"] == "CANCELLED"
    assert api.get(f"/api/orders/{oid}/payments").json()[0]["status"] == "REFUNDED"


def test_tc_pay_010_reconciliation_settles_pending_payments(api):
    """TC-PAY-010: with every callback lost, reconciliation settles the answered payments, leaves the unanswered one PENDING and is safe to repeat."""
    ids = {}
    for upi_id in ("success@sandbox", "z9@sandbox", "u67@sandbox", "pending@sandbox"):
        oid = _order(api, qty=1)["id"]
        ids[upi_id] = (oid, api.pay(oid, upi_id).json())
    assert api.post("/api/payments/reconcile").json() == {"checked": 4, "settled": 3, "still_pending": 1, **NO_REFUNDS}
    state = {u: (api.get(f"/api/orders/{o}").json()["status"], api.get(f"/api/orders/{o}/payments").json()[0]) for u, (o, _) in ids.items()}
    assert {u: (s, p["status"], p["code"]) for u, (s, p) in state.items()} == {
        "success@sandbox": ("PAID", "SUCCESS", None),
        "z9@sandbox": ("PLACED", "FAILED", "Z9"),
        "u67@sandbox": ("PLACED", "FAILED", "U67"),
        "pending@sandbox": ("PLACED", "PENDING", None),
    }
    assert api.post("/api/payments/reconcile").json() == {"checked": 1, "settled": 0, "still_pending": 1, **NO_REFUNDS}
    oid, p = ids["pending@sandbox"]
    assert api.callback(p["provider_txn"], "SUCCESS").json()["status"] == "SUCCESS"  # the bank answers at last
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PAID"


@pytest.mark.parametrize("code", ["ZM", "Z9", "U69", "U30", "U67"])
def test_tc_pay_011_customer_may_retry_after_an_ordinary_decline(api, code):
    """TC-PAY-011: after a wrong PIN, low balance, expiry, bank failure or timeout, a new attempt is allowed and can pay the order."""
    oid = _order(api)["id"]
    _fail(api, oid, code)
    retry = api.pay(oid)
    assert retry.status_code == 201
    assert api.get(f"/api/payments/{retry.json()['id']}").json()["status"] == "SUCCESS"
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PAID"


@pytest.mark.parametrize("before, message", [
    ("pending", "already in progress"),
    ("paid", "cannot pay an order that is PAID"),
    ("three failures", "no more than 3 payment attempts"),
    ("risk limit", "risk limit"),
])
def test_tc_pay_012_retry_is_refused_when_it_could_charge_twice_or_cannot_succeed(api, before, message):
    """TC-PAY-012: a new attempt is refused while one is pending, after the order is paid, after 3 attempts and after a U16 risk decline."""
    oid = _order(api)["id"]
    if before == "pending":
        api.pay(oid, "pending@sandbox")
    elif before == "paid":
        api.get(f"/api/payments/{api.pay(oid).json()['id']}")
    elif before == "three failures":
        for code in ("ZM", "ZM", "Z9"):
            _fail(api, oid, code)
    else:
        _fail(api, oid, "U16")
    r = api.pay(oid)
    assert r.status_code == 409 and message in r.json()["detail"]


# Edge cases suggested by AI and kept after review (docs/upi-failure-lab.md, "Edge cases added after review").

@pytest.mark.parametrize("retried", [False, True])
def test_tc_pay_013_success_after_a_failure_is_refunded(api, db, retried):
    """TC-PAY-013: a SUCCESS that arrives after the payment was marked FAILED (a debit timeout) is refunded, whether or not the customer paid again meanwhile, and the order is never charged twice."""
    oid = _order(api)["id"]
    timed_out = _fail(api, oid, "U67")
    if retried:
        api.get(f"/api/payments/{api.pay(oid).json()['id']}")
    for _ in range(2):  # the late answer, and a repeat of it
        assert api.callback(timed_out["provider_txn"], "SUCCESS").json()["status"] == "REFUNDED"
    assert api.get(f"/api/orders/{oid}").json()["status"] == ("PAID" if retried else "PLACED")
    kept = db.execute("SELECT COUNT(*) FROM payments WHERE order_id = ? AND status = 'SUCCESS'", (oid,)).fetchone()[0]
    assert kept == (1 if retried else 0)


@pytest.mark.parametrize("amount", ["less", "more", "missing"])
def test_tc_pay_014_success_for_a_different_amount_does_not_pay_the_order(api, amount):
    """TC-PAY-014: a correctly signed SUCCESS callback for a different amount, or none, is rejected; the payment stays PENDING until the right amount is reported."""
    oid = _order(api)["id"]
    p = api.pay(oid, "pending@sandbox").json()
    wrong = {"less": p["amount_paise"] - 1, "more": p["amount_paise"] + 1, "missing": None}[amount]
    r = api.callback(p["provider_txn"], "SUCCESS", amount_paise=wrong)
    assert r.status_code == 422 and "amount" in r.json()["detail"]
    assert api.get(f"/api/payments/{p['id']}").json()["status"] == "PENDING"
    assert api.get(f"/api/orders/{oid}").json()["status"] == "PLACED"
    assert api.callback(p["provider_txn"], "SUCCESS").json()["status"] == "SUCCESS"


def test_tc_pay_015_a_refund_counts_only_once_the_provider_confirms_it(api):
    """TC-PAY-015: a refund that fails or stays pending leaves the payment REFUND_PENDING, never REFUNDED; reconciliation asks again until the provider confirms it."""
    fails, pending = _order(api)["id"], _order(api)["id"]
    for oid, upi_id in ((fails, "refund-fails@sandbox"), (pending, "refund-pending@sandbox")):
        api.get(f"/api/payments/{api.pay(oid, upi_id).json()['id']}")
        assert api.post(f"/api/orders/{oid}/cancel").json()["status"] == "CANCELLED"
        assert api.get(f"/api/orders/{oid}/payments").json()[0]["status"] == "REFUND_PENDING"
    assert api.post("/api/payments/reconcile").json() == {
        "checked": 0, "settled": 0, "still_pending": 0, "refunds_retried": 2, "refunds_still_pending": 1}
    assert api.get(f"/api/orders/{fails}/payments").json()[0]["status"] == "REFUNDED"
    assert api.get(f"/api/orders/{pending}/payments").json()[0]["status"] == "REFUND_PENDING"
    assert api.post("/api/payments/reconcile").json()["refunds_still_pending"] == 1  # safe to repeat


@pytest.mark.parametrize("items, allowed", [
    ([("BND-UPI", 1)], True),                  # Rs 1,00,000.00: exactly the limit
    ([("BND-UPI", 1), ("BND-P", 1)], False),   # Rs 1,00,000.01
])
def test_tc_pay_016_orders_above_the_upi_limit_are_refused_before_any_request(api, items, allowed):
    """TC-PAY-016: an order above UPI's Rs 1,00,000 limit for one payment is refused with a reason before any collect request is sent; an order at the limit can pay."""
    order = api.place(items).json()
    r = api.pay(order["id"])
    if allowed:
        assert order["total_paise"] == 10_000_000 and r.status_code == 201
    else:
        assert order["total_paise"] == 10_000_001 and r.status_code == 422 and "1,00,000" in r.json()["detail"]
        assert api.get(f"/api/orders/{order['id']}/payments").json() == []
