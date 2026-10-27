"""Pretend UPI provider: a stand-in for a payment gateway, so the checkout's payment handling can be tested.

Nothing here moves money. Failure codes and meanings are NPCI's ("Unified Payments Interface: Error and Response
Codes", version 2.9, 17 Jan 2024). Failure rates come from UPI Pulse (see RATES). Every collect request starts
pending; the result is read with a status check, or sent to the shop by a signed callback.

Sandbox UPI IDs fix the outcome, like a gateway's test mode: success@sandbox, pending@sandbox (never answers),
zm@sandbox, z9@sandbox, u30@sandbox, u67@sandbox, u69@sandbox, u16@sandbox. refund-fails@sandbox and
refund-pending@sandbox pay, and then their refund fails once or never completes. Any other UPI ID gets a random
outcome at the real-world rates.
"""
import hashlib
import hmac
import os
import random
import secrets
import uuid

# code: (NPCI description, NPCI section, NPCI TD/BD label, message shown to the customer)
FAILURES = {
    "ZM": ("INVALID MPIN", "3.1", "BD", "Wrong UPI PIN"),
    "Z9": ("INSUFFICIENT FUNDS IN CUSTOMER (REMITTER) ACCOUNT", "3.1", "BD", "Not enough money in the account"),
    "U16": ("RISK THRESHOLD EXCEEDED", "4.4", "BD", "UPI risk limit reached. Try later or use another method"),
    "U69": ("COLLECT EXPIRED", "4.4", "BD", "The payment request expired before it was approved"),
    # NPCI marks U30 "NA": the bank's own response code decides TD or BD. Here it stands for a bank outage
    # such as XY "REMITTER CBS OFFLINE" (TD), so it counts as technical.
    "U30": ("DEBIT HAS BEEN FAILED", "4.4", "NA", "Your bank could not debit the account"),
    "U67": ("DEBIT TIMEOUT", "4.4", "TD", "Your bank did not answer in time"),
}
BUSINESS, TECHNICAL = ("ZM", "Z9", "U16", "U69"), ("U30", "U67")
# Sandbox UPI IDs whose payment succeeds and whose refund answers these in turn: one failure then success, or never done.
REFUNDS = {"refund-fails": ("FAILED", "SUCCESS"), "refund-pending": ("PENDING",)}

# Payer's-bank (remitter) decline rates, Oct 2025 to Sep 2026, weighted by payments, from UPI Pulse's data.json
# (built 2026-10-26, NPCI Top 50 Member Performance). Recompute with scripts/upi_rates.py.
BUSINESS_DECLINE_RATE = 0.0962
TECHNICAL_DECLINE_RATE = 0.0029
# shortcut: NPCI does not publish declines by code, so each group's rate is split evenly between its codes.
RATES = {**{c: BUSINESS_DECLINE_RATE / len(BUSINESS) for c in BUSINESS},
         **{c: TECHNICAL_DECLINE_RATE / len(TECHNICAL) for c in TECHNICAL}}

SECRET = (os.environ.get("ORDERDESK_UPI_SECRET") or secrets.token_hex(32)).encode()
_rng = random.Random()
_txns: dict[str, dict] = {}  # provider-side record of each collect request; the UPI ID is not kept


def draw(rng: random.Random) -> tuple[str, str | None]:
    """One outcome at the real-world rates: ("SUCCESS", None) or ("FAILED", code)."""
    x = rng.random()
    for code, rate in RATES.items():
        if x < rate:
            return "FAILED", code
        x -= rate
    return "SUCCESS", None


def _outcome(upi_id: str) -> tuple[str, str | None]:
    name, _, handle = upi_id.lower().partition("@")
    if handle == "sandbox":
        if name in ("success", *REFUNDS):
            return "SUCCESS", None
        if name == "pending":
            return "PENDING", None
        if name.upper() in FAILURES:
            return "FAILED", name.upper()
    return draw(_rng)


def collect(upi_id: str, amount_paise: int) -> str:
    """Send a collect request to the payer's UPI app. Returns the provider's transaction id."""
    txn = "PUPI" + uuid.uuid4().hex[:16].upper()
    status, code = _outcome(upi_id)
    name, _, handle = upi_id.lower().partition("@")
    refund_answers = list(REFUNDS[name]) if handle == "sandbox" and name in REFUNDS else []
    _txns[txn] = {"amount_paise": amount_paise, "status": status, "code": code, "refund_answers": refund_answers}
    return txn


def status(txn: str) -> tuple[str, str | None]:
    """Status check: PENDING until the payer's bank has answered, then SUCCESS or FAILED with a code."""
    t = _txns.get(txn)
    return ("PENDING", None) if t is None else (t["status"], t["code"])


def refund(txn: str) -> str:
    """Ask for a payment's money back: SUCCESS, or PENDING or FAILED, and the shop asks again later.
    Asking again after a refund succeeded answers SUCCESS again, so the money is returned once."""
    t = _txns.get(txn)
    if t is None:
        return "FAILED"
    answers = t["refund_answers"] or ["SUCCESS"]
    return answers.pop(0) if len(answers) > 1 else answers[0]  # the last answer repeats


def sign(body: bytes) -> str:
    return hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def signature_ok(body: bytes, signature: str | None) -> bool:
    return signature is not None and hmac.compare_digest(sign(body), signature)


def reset() -> None:
    _txns.clear()
