"""Orderdesk: a small order-processing service used as the application under test."""
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from . import db, defects, pricing
from . import upi_provider as upi

app = FastAPI(title="Orderdesk (application under test)", version="1.0")
STATIC = Path(__file__).parent / "static"

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_LOOSE = re.compile(r"^[^@\s]+@[^@\s]+$")  # used only when BUG-006 is active
UPI_ID = re.compile(r"^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,63}$")
MAX_QTY, MAX_LINES = 10, 5
MAX_PAYMENT_ATTEMPTS = 3
STATUSES = ("PLACED", "PAID", "SHIPPED", "DELIVERED", "CANCELLED")
TRANSITIONS = {  # action -> (allowed current statuses, new status)
    "pay": (("PLACED",), "PAID"),
    "ship": (("PAID",), "SHIPPED"),
    "deliver": (("SHIPPED",), "DELIVERED"),
    "cancel": (("PLACED", "PAID"), "CANCELLED"),
}


def mask_email(email: str) -> str:
    """Keep the first character of the name and of the domain, e.g. anubhav@gmail.com -> a***@g***.com (REQ-DAT-003)."""
    local, _, domain = email.partition("@")
    name, dot, tld = domain.rpartition(".")
    if not dot:  # no dot in the domain (only reachable when BUG-006 is active)
        name = domain
    return f"{local[:1]}***@{name[:1]}***{dot}{tld}"


class Line(BaseModel):
    sku: str
    quantity: int


class NewOrder(BaseModel):
    customer_email: str
    items: list[Line]
    coupon: str | None = None


class NewPayment(BaseModel):
    upi_id: str


class Callback(BaseModel):
    provider_txn: str
    status: Literal["SUCCESS", "FAILED"]
    code: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _order_json(order_id: int) -> dict:
    con = db.connect()
    row = con.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "order not found")
    items = con.execute(
        "SELECT sku, quantity, unit_price_paise FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    ).fetchall()
    return {
        "id": row["id"], "customer_email": row["customer_email"], "status": row["status"], "coupon": row["coupon"],
        "subtotal_paise": row["subtotal_paise"], "discount_paise": row["discount_paise"],
        "shipping_paise": row["shipping_paise"], "total_paise": row["total_paise"], "created_at": row["created_at"],
        "items": [dict(i) for i in items],
    }


def _payment_json(payment_id: int) -> dict:
    row = db.connect().execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "payment not found")
    return {**dict(row), "reason": upi.FAILURES[row["code"]][3] if row["code"] else None}


def _settle(con, pay, status: str, code: str | None) -> None:
    """Apply the provider's answer to a PENDING payment once; later answers change nothing (REQ-PAY-002, -003)."""
    if pay["status"] != "PENDING" or status == "PENDING":
        return
    order_status = con.execute("SELECT status FROM orders WHERE id = ?", (pay["order_id"],)).fetchone()["status"]
    if status == "SUCCESS" and order_status != "PLACED":  # cancelled or paid another way meanwhile (REQ-PAY-004)
        upi.refund(pay["provider_txn"])
        status = "REFUNDED"
    con.execute("UPDATE payments SET status = ?, code = ?, updated_at = ? WHERE id = ?", (status, code, _now(), pay["id"]))
    if status == "SUCCESS":
        con.execute("UPDATE orders SET status = 'PAID' WHERE id = ?", (pay["order_id"],))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {"ui_defects": sorted(d for d in defects.active() if d == "BUG-008")}


@app.get("/api/products")
def products():
    rows = db.connect().execute("SELECT sku, name, price_paise, stock FROM products ORDER BY sku").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/orders", status_code=201)
def create_order(body: NewOrder):
    email_ok = (EMAIL_LOOSE if defects.on("BUG-006") else EMAIL).match(body.customer_email) and len(body.customer_email) <= 254
    if not email_ok:
        raise HTTPException(422, "invalid customer_email")
    if not 1 <= len(body.items) <= MAX_LINES:
        raise HTTPException(422, f"order must have 1 to {MAX_LINES} lines")
    skus = [i.sku for i in body.items]
    if len(set(skus)) != len(skus):
        raise HTTPException(422, "duplicate sku in order")
    max_qty = MAX_QTY + 1 if defects.on("BUG-001") else MAX_QTY
    for line in body.items:
        if not 1 <= line.quantity <= max_qty:
            raise HTTPException(422, f"quantity for {line.sku} must be 1 to {MAX_QTY}")

    with db.LOCK:
        con = db.connect()
        con.execute("BEGIN IMMEDIATE")
        try:
            subtotal, priced = 0, []
            for line in body.items:
                prod = con.execute("SELECT price_paise, stock FROM products WHERE sku = ?", (line.sku,)).fetchone()
                if prod is None:
                    raise HTTPException(422, f"unknown sku {line.sku}")
                if line.quantity > prod["stock"]:
                    raise HTTPException(409, f"insufficient stock for {line.sku}")
                subtotal += prod["price_paise"] * line.quantity
                priced.append((line, prod["price_paise"]))
            try:
                totals = pricing.price_order(subtotal, body.coupon)
            except pricing.CouponError as exc:
                raise HTTPException(422, str(exc))
            cur = con.execute(
                "INSERT INTO orders (customer_email, status, coupon, subtotal_paise, discount_paise, shipping_paise, total_paise, created_at) "
                "VALUES (?, 'PLACED', ?, ?, ?, ?, ?, ?)",
                (mask_email(body.customer_email), body.coupon, totals.subtotal, totals.discount, totals.shipping, totals.total,
                 _now()),
            )
            order_id = cur.lastrowid
            for line, price in priced:
                con.execute("INSERT INTO order_items (order_id, sku, quantity, unit_price_paise) VALUES (?, ?, ?, ?)",
                            (order_id, line.sku, line.quantity, price))
                con.execute("UPDATE products SET stock = stock - ? WHERE sku = ?", (line.quantity, line.sku))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return _order_json(order_id)


@app.get("/api/orders/{order_id}")
def get_order(order_id: int):
    return _order_json(order_id)


@app.get("/api/orders")
def list_orders(status: str | None = Query(default=None)):
    if status is not None and status not in STATUSES:
        raise HTTPException(422, "invalid status filter")
    sql, args = "SELECT id FROM orders", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    ids = [r["id"] for r in db.connect().execute(sql + " ORDER BY id", args).fetchall()]
    return [_order_json(i) for i in ids]


# Declared before the /{action} route below, which would otherwise swallow ".../payments".
@app.post("/api/orders/{order_id}/payments", status_code=201)
def start_payment(order_id: int, body: NewPayment):
    """Start a UPI collect request for the order total (REQ-PAY-001) within the retry rules (REQ-PAY-006)."""
    if not UPI_ID.match(body.upi_id):
        raise HTTPException(422, "invalid upi_id")
    with db.transaction() as con:
        order = con.execute("SELECT status, total_paise FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise HTTPException(404, "order not found")
        if order["status"] != "PLACED":
            raise HTTPException(409, f"cannot pay an order that is {order['status']}")
        tries = con.execute("SELECT status, code FROM payments WHERE order_id = ?", (order_id,)).fetchall()
        if any(t["status"] == "PENDING" for t in tries):
            raise HTTPException(409, "a payment for this order is already in progress")
        if any(t["code"] == "U16" for t in tries):
            raise HTTPException(409, "UPI risk limit reached for this order; use another payment method")
        if len(tries) >= MAX_PAYMENT_ATTEMPTS:
            raise HTTPException(409, f"no more than {MAX_PAYMENT_ATTEMPTS} payment attempts per order")
        txn = upi.collect(body.upi_id, order["total_paise"])  # the UPI ID goes to the provider only (REQ-PAY-007)
        payment_id = con.execute(
            "INSERT INTO payments (order_id, provider_txn, amount_paise, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'PENDING', ?, ?)", (order_id, txn, order["total_paise"], _now(), _now())).lastrowid
    return _payment_json(payment_id)


@app.get("/api/orders/{order_id}/payments")
def list_payments(order_id: int):
    _order_json(order_id)  # 404 for a missing order
    ids = db.connect().execute("SELECT id FROM payments WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
    return [_payment_json(r["id"]) for r in ids]


@app.get("/api/payments/{payment_id}")
def check_payment(payment_id: int):
    """Status check: a PENDING payment asks the provider for its latest answer (REQ-PAY-005)."""
    with db.transaction() as con:
        pay = con.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if pay is None:
            raise HTTPException(404, "payment not found")
        _settle(con, pay, *upi.status(pay["provider_txn"]))
    return _payment_json(payment_id)


@app.post("/api/payments/reconcile")
def reconcile():
    """Status-check every PENDING payment, so a lost callback cannot leave one pending for ever (REQ-PAY-005)."""
    with db.transaction() as con:
        pending = con.execute("SELECT * FROM payments WHERE status = 'PENDING' ORDER BY id").fetchall()
        for pay in pending:
            _settle(con, pay, *upi.status(pay["provider_txn"]))
        left = con.execute("SELECT COUNT(*) FROM payments WHERE status = 'PENDING'").fetchone()[0]
    return {"checked": len(pending), "settled": len(pending) - left, "still_pending": left}


@app.post("/api/payments/callback")
async def payment_callback(request: Request):
    """The provider's signed callback. Every repeat is acknowledged, but only the first one changes anything (REQ-PAY-003)."""
    body = await request.body()
    if not upi.signature_ok(body, request.headers.get("X-Upi-Signature")):
        raise HTTPException(401, "invalid signature")
    try:
        cb = Callback.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "invalid callback body")
    if not (cb.code in upi.FAILURES if cb.status == "FAILED" else cb.code is None):
        raise HTTPException(422, "FAILED needs a known code and SUCCESS none")
    with db.transaction() as con:
        pay = con.execute("SELECT * FROM payments WHERE provider_txn = ?", (cb.provider_txn,)).fetchone()
        if pay is None:
            raise HTTPException(404, "payment not found")
        _settle(con, pay, cb.status, cb.code)
    return _payment_json(pay["id"])


@app.post("/api/orders/{order_id}/{action}")
def transition(order_id: int, action: str):
    if action not in TRANSITIONS:
        raise HTTPException(404, "unknown action")
    allowed, new_status = TRANSITIONS[action]
    if action == "cancel" and defects.on("BUG-005"):
        allowed = allowed + ("SHIPPED",)
    with db.LOCK:
        con = db.connect()
        row = con.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "order not found")
        if row["status"] not in allowed:
            raise HTTPException(409, f"cannot {action} an order that is {row['status']}")
        con.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        if action == "cancel" and not defects.on("BUG-004"):
            con.execute(
                "UPDATE products SET stock = stock + (SELECT quantity FROM order_items WHERE order_id = ? AND sku = products.sku) "
                "WHERE sku IN (SELECT sku FROM order_items WHERE order_id = ?)", (order_id, order_id))
        if action == "cancel":  # a cancelled order keeps none of the customer's money (REQ-PAY-004)
            for paid in con.execute("SELECT id, provider_txn FROM payments WHERE order_id = ? AND status = 'SUCCESS'",
                                    (order_id,)).fetchall():
                upi.refund(paid["provider_txn"])
                con.execute("UPDATE payments SET status = 'REFUNDED', updated_at = ? WHERE id = ?", (_now(), paid["id"]))
    return _order_json(order_id)


if os.environ.get("ORDERDESK_TEST_MODE") == "1":
    @app.post("/api/test/reset")
    def reset():
        db.reset()
        upi.reset()
        return {"status": "reset"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

