"""SQL validation of the persisted data after a realistic scenario (REQ-DAT-*).

These checks query the SQLite file directly, so they catch defects that an API response could hide.
"""
import pytest

pytestmark = pytest.mark.db


@pytest.fixture()
def scenario(api):
    """A mix of orders: coupons, multi-line, paid, shipped, cancelled."""
    ids = {}
    ids["plain"] = api.place([("NB-A5", 2)]).json()["id"]
    ids["save10"] = api.place([("BND-B", 1), ("BND-E", 1)], coupon="SAVE10").json()["id"]
    ids["flat50"] = api.place([("BND-B", 1), ("BND-D", 1)], coupon="FLAT50").json()["id"]
    ids["multi"] = api.place([("PEN-GEL", 3), ("LAMP-01", 1), ("BTL-STL", 2)]).json()["id"]
    ids["cancel_placed"] = api.place([("CBL-USBC", 4)]).json()["id"]
    ids["cancel_paid"] = api.place([("BAG-01", 2)]).json()["id"]
    api.post(f"/api/orders/{ids['cancel_placed']}/cancel")
    api.post(f"/api/orders/{ids['cancel_paid']}/pay")
    api.post(f"/api/orders/{ids['cancel_paid']}/cancel")
    api.post(f"/api/orders/{ids['multi']}/pay")
    api.post(f"/api/orders/{ids['multi']}/ship")
    return ids


def test_tc_dat_001_order_total_equals_subtotal_minus_discount_plus_shipping(db, scenario):
    """TC-DAT-001: orders.total_paise = subtotal - discount + shipping for every row."""
    bad = db.execute("SELECT id FROM orders WHERE total_paise != subtotal_paise - discount_paise + shipping_paise").fetchall()
    assert bad == []


def test_tc_dat_002_subtotal_equals_sum_of_items(db, scenario):
    """TC-DAT-002: orders.subtotal_paise = sum(quantity x unit_price) of its items."""
    bad = db.execute(
        "SELECT o.id FROM orders o JOIN order_items i ON i.order_id = o.id "
        "GROUP BY o.id HAVING SUM(i.quantity * i.unit_price_paise) != o.subtotal_paise").fetchall()
    assert bad == []


def test_tc_dat_003_stock_is_conserved(db, scenario):
    """TC-DAT-003: stock + units held by non-cancelled orders = initial stock, for every product."""
    rows = db.execute(
        "SELECT p.sku, p.stock + COALESCE(SUM(CASE WHEN o.status != 'CANCELLED' THEN i.quantity END), 0) AS accounted, p.initial_stock "
        "FROM products p LEFT JOIN order_items i ON i.sku = p.sku LEFT JOIN orders o ON o.id = i.order_id "
        "GROUP BY p.sku").fetchall()
    assert [(r["sku"], r["accounted"], r["initial_stock"]) for r in rows if r["accounted"] != r["initial_stock"]] == []


def test_tc_dat_004_no_negative_stock(db, scenario):
    """TC-DAT-004: no product has negative stock."""
    assert db.execute("SELECT sku FROM products WHERE stock < 0").fetchall() == []


def test_tc_dat_005_every_order_has_items_and_a_valid_status(db, scenario):
    """TC-DAT-005: no empty orders and only the five documented statuses."""
    assert db.execute("SELECT id FROM orders WHERE id NOT IN (SELECT order_id FROM order_items)").fetchall() == []
    assert db.execute("SELECT id FROM orders WHERE status NOT IN ('PLACED','PAID','SHIPPED','DELIVERED','CANCELLED')").fetchall() == []


def test_tc_dat_006_item_price_is_a_snapshot_of_the_catalogue_price(db, scenario):
    """TC-DAT-006: unit prices stored on items match the catalogue (prices never change in this app)."""
    bad = db.execute("SELECT i.id FROM order_items i JOIN products p ON p.sku = i.sku WHERE i.unit_price_paise != p.price_paise").fetchall()
    assert bad == []


def test_tc_dat_007_foreign_keys_are_consistent(db, scenario):
    """TC-DAT-007: PRAGMA foreign_key_check reports no violations."""
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.fixture()
def payment_scenario(api):
    """UPI payments: paid, declined then paid, repeated callbacks, a late success after cancel, one still pending."""
    def order():
        return api.place([("NB-A5", 1)]).json()["id"]
    paid, retried, late, pending = order(), order(), order(), order()
    api.get(f"/api/payments/{api.pay(paid).json()['id']}")
    api.get(f"/api/payments/{api.pay(retried, 'z9@sandbox').json()['id']}")
    txn = api.pay(retried).json()["provider_txn"]
    for _ in range(3):
        api.callback(txn, "SUCCESS")
    txn = api.pay(late).json()["provider_txn"]
    api.post(f"/api/orders/{late}/cancel")
    api.callback(txn, "SUCCESS")
    api.pay(pending, "pending@sandbox")
    api.post(f"/api/orders/{paid}/ship")


def test_tc_dat_008_payments_never_charge_twice_and_match_their_order(db, payment_scenario):
    """TC-DAT-008: no order holds two live payments, every SUCCESS is for the order total of a paid order, and no cancelled order keeps a SUCCESS."""
    assert db.execute("SELECT order_id FROM payments WHERE status IN ('PENDING', 'SUCCESS') "
                      "GROUP BY order_id HAVING COUNT(*) > 1").fetchall() == []
    assert db.execute("SELECT p.id FROM payments p JOIN orders o ON o.id = p.order_id WHERE p.status = 'SUCCESS' "
                      "AND (p.amount_paise != o.total_paise OR o.status NOT IN ('PAID', 'SHIPPED', 'DELIVERED'))").fetchall() == []
    assert [tuple(r) for r in db.execute("SELECT status, COUNT(*) FROM payments GROUP BY status ORDER BY status")] == [
        ("FAILED", 1), ("PENDING", 1), ("REFUNDED", 1), ("SUCCESS", 2)]
