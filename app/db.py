"""SQLite storage. One connection guarded by a lock keeps the app simple."""
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE products (
    sku TEXT PRIMARY KEY, name TEXT NOT NULL, price_paise INTEGER NOT NULL CHECK (price_paise > 0),
    stock INTEGER NOT NULL CHECK (stock >= 0), initial_stock INTEGER NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_email TEXT NOT NULL, status TEXT NOT NULL,
    coupon TEXT, subtotal_paise INTEGER NOT NULL, discount_paise INTEGER NOT NULL,
    shipping_paise INTEGER NOT NULL, total_paise INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
    sku TEXT NOT NULL REFERENCES products(sku), quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_paise INTEGER NOT NULL
);
"""

SEED = [
    ("NB-A5", "Notebook A5", 12_000, 50),
    ("PEN-GEL", "Gel Pen Pack", 8_050, 100),
    ("LAMP-01", "Desk Lamp", 89_900, 10),
    ("CBL-USBC", "USB-C Cable", 24_999, 30),
    ("BTL-STL", "Water Bottle", 34_900, 20),
    ("BAG-01", "Backpack", 149_900, 5),
    # Boundary-test fixtures: prices chosen so subtotals can hit Rs 300.00 / Rs 500.00 and rounding edges exactly.
    ("BND-A", "Boundary fixture A", 24_999, 100),
    ("BND-B", "Boundary fixture B", 25_000, 100),
    ("BND-C", "Boundary fixture C", 25_001, 100),
    ("BND-D", "Boundary fixture D", 5_000, 100),
    ("BND-E", "Boundary fixture E", 25_005, 100),
]

LOCK = threading.RLock()
_conn: sqlite3.Connection | None = None


def path() -> Path:
    return Path(os.environ.get("ORDERDESK_DB", "orderdesk.db"))


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(path(), check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        reset()
    return _conn


def reset() -> None:
    """Drop and re-seed. Called at start-up and by the test-mode reset endpoint."""
    with LOCK:
        conn = _conn or sqlite3.connect(path(), check_same_thread=False, isolation_level=None)
        conn.executescript("DROP TABLE IF EXISTS order_items; DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS products;")
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO products (sku, name, price_paise, stock, initial_stock) VALUES (?, ?, ?, ?, ?)",
            [(s, n, p, q, q) for s, n, p, q in SEED],
        )
