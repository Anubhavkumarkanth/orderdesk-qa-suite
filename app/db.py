"""MySQL storage. One connection guarded by a lock keeps the app simple."""
import os
import threading
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit

import pymysql
import pymysql.cursors

# Binary collation compares and sorts text exactly (case-sensitive). BIGINT holds any 64-bit whole number.
TABLE = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin"
SCHEMA = f"""
CREATE TABLE products (
    sku VARCHAR(64) PRIMARY KEY, name TEXT NOT NULL, price_paise BIGINT NOT NULL CHECK (price_paise > 0),
    stock BIGINT NOT NULL CHECK (stock >= 0), initial_stock BIGINT NOT NULL
) {TABLE};
CREATE TABLE orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT, customer_email TEXT NOT NULL, status TEXT NOT NULL,
    coupon TEXT, subtotal_paise BIGINT NOT NULL, discount_paise BIGINT NOT NULL,
    shipping_paise BIGINT NOT NULL, total_paise BIGINT NOT NULL, created_at TEXT NOT NULL
) {TABLE};
CREATE TABLE order_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT, order_id BIGINT NOT NULL, sku VARCHAR(64) NOT NULL,
    quantity BIGINT NOT NULL CHECK (quantity > 0), unit_price_paise BIGINT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id), FOREIGN KEY (sku) REFERENCES products(sku)
) {TABLE};
CREATE TABLE payments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT, order_id BIGINT NOT NULL,
    provider_txn VARCHAR(64) NOT NULL UNIQUE, amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
    status VARCHAR(16) NOT NULL CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'REFUNDED', 'REFUND_PENDING')), code TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    -- At most one payment per order can be in progress or paid, so a second charge cannot be recorded (REQ-PAY-006).
    -- MySQL has no partial index, so a hidden column holds order_id only for live payments, and UNIQUE ignores the NULLs.
    live_order_id BIGINT AS (CASE WHEN status IN ('PENDING', 'SUCCESS') THEN order_id END) INVISIBLE,
    UNIQUE KEY one_live_payment_per_order (live_order_id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
) {TABLE};
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
    # UPI limit fixtures: BND-UPI alone is exactly Rs 1,00,000.00; adding BND-P makes Rs 1,00,000.01.
    ("BND-UPI", "Boundary fixture UPI", 10_000_000, 5),
    ("BND-P", "Boundary fixture P", 1, 100),
]

LOCK = threading.RLock()


class _Cursor(pymysql.cursors.DictCursor):
    def fetchall(self):
        return list(super().fetchall())  # PyMySQL returns () for no rows; callers compare with []


class Connection(pymysql.connections.Connection):
    def execute(self, sql: str, args=None) -> _Cursor:
        """Run one statement and return its cursor. PyMySQL connections are not thread-safe, so the lock covers the round trip;
        the cursor holds every row afterwards, so reading them needs no lock."""
        with LOCK:
            cur = self.cursor()
            cur.execute(sql, args)
        return cur


def open_connection(url: str) -> Connection:
    """Open a connection from a URL such as mysql://user:password@host:3306/orderdesk."""
    u = urlsplit(url)
    return Connection(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""),
                      password=unquote(u.password or ""), database=u.path.lstrip("/"),
                      autocommit=True, cursorclass=_Cursor)


_conn: Connection | None = None


def connect() -> Connection:
    global _conn
    with LOCK:
        if _conn is None:
            _conn = open_connection(os.environ["DATABASE_URL"])
            reset()
        else:
            _conn.ping(reconnect=True)  # MySQL drops idle connections (wait_timeout); reopen instead of failing
        return _conn


@contextmanager
def transaction():
    """Hold the lock and run the block as one transaction, rolled back on any error."""
    with LOCK:
        con = connect()
        con.execute("BEGIN")
        try:
            yield con
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise


def reset() -> None:
    """Drop and re-seed. Called at start-up and by the test-mode reset endpoint."""
    with LOCK:
        conn = connect()
        for stmt in ["DROP TABLE IF EXISTS payments, order_items, orders, products"] + SCHEMA.split(";")[:-1]:
            conn.execute(stmt)
        conn.cursor().executemany(
            "INSERT INTO products (sku, name, price_paise, stock, initial_stock) VALUES (%s, %s, %s, %s, %s)",
            [(s, n, p, q, q) for s, n, p, q in SEED],
        )
