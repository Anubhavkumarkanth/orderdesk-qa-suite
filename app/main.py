"""Orderdesk: a small order-processing service used as the application under test."""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db, defects, pricing

app = FastAPI(title="Orderdesk (application under test)", version="1.0")
STATIC = Path(__file__).parent / "static"
PUBLIC_DEMO = os.environ.get("ORDERDESK_PUBLIC_DEMO") == "1"
DEMO_EMAIL = "guest@example.test"

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_LOOSE = re.compile(r"^[^@\s]+@[^@\s]+$")  # used only when BUG-006 is active
MAX_QTY, MAX_LINES = 10, 5
STATUSES = ("PLACED", "PAID", "SHIPPED", "DELIVERED", "CANCELLED")
TRANSITIONS = {  # action -> (allowed current statuses, new status)
    "pay": (("PLACED",), "PAID"),
    "ship": (("PAID",), "SHIPPED"),
    "deliver": (("SHIPPED",), "DELIVERED"),
    "cancel": (("PLACED", "PAID"), "CANCELLED"),
}


class Line(BaseModel):
    sku: str
    quantity: int


class NewOrder(BaseModel):
    customer_email: str
    items: list[Line]
    coupon: str | None = None


def _order_json(order_id: int) -> dict:
    con = db.connect()
    row = con.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "order not found")
    items = con.execute(
        "SELECT sku, quantity, unit_price_paise FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    ).fetchall()
    return {
        "id": row["id"], "customer_email": DEMO_EMAIL if PUBLIC_DEMO else row["customer_email"], "status": row["status"], "coupon": row["coupon"],
        "subtotal_paise": row["subtotal_paise"], "discount_paise": row["discount_paise"],
        "shipping_paise": row["shipping_paise"], "total_paise": row["total_paise"], "created_at": row["created_at"],
        "items": [dict(i) for i in items],
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {"ui_defects": sorted(d for d in defects.active() if d == "BUG-008"), "public_demo": PUBLIC_DEMO}


@app.get("/api/products")
def products():
    rows = db.connect().execute("SELECT sku, name, price_paise, stock FROM products ORDER BY sku").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/orders", status_code=201)
def create_order(body: NewOrder):
    customer_email = DEMO_EMAIL if PUBLIC_DEMO else body.customer_email
    email_ok = (EMAIL_LOOSE if defects.on("BUG-006") else EMAIL).match(customer_email) and len(customer_email) <= 254
    if not PUBLIC_DEMO and not email_ok:
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
                (customer_email, body.coupon, totals.subtotal, totals.discount, totals.shipping, totals.total,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
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
    return _order_json(order_id)


if os.environ.get("ORDERDESK_TEST_MODE") == "1":
    @app.post("/api/test/reset")
    def reset():
        db.reset()
        return {"status": "reset"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

