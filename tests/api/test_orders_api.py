"""Functional and negative API tests (REQ-ORD-*, REQ-VAL-*). Test case IDs map to docs/test-cases.md."""
import pytest

pytestmark = pytest.mark.api


def test_tc_ord_001_product_catalogue_lists_seeded_products(api):
    """TC-ORD-001: GET /api/products returns every product with price and stock."""
    r = api.get("/api/products")
    assert r.status_code == 200
    skus = {p["sku"] for p in r.json()}
    assert {"NB-A5", "PEN-GEL", "LAMP-01", "CBL-USBC", "BTL-STL", "BAG-01"} <= skus
    assert all(set(p) == {"sku", "name", "price_paise", "stock"} for p in r.json())


def test_tc_ord_002_place_order_happy_path(api):
    """TC-ORD-002: a valid order is created with correct totals and decrements stock."""
    before = api.stock("NB-A5")
    r = api.place([("NB-A5", 2)])
    assert r.status_code == 201
    o = r.json()
    assert o["status"] == "PLACED"
    assert (o["subtotal_paise"], o["discount_paise"], o["shipping_paise"], o["total_paise"]) == (24_000, 0, 4_000, 28_000)
    assert o["items"] == [{"sku": "NB-A5", "quantity": 2, "unit_price_paise": 12_000}]
    assert api.stock("NB-A5") == before - 2


def test_tc_ord_003_multi_line_order_totals(api):
    """TC-ORD-003: subtotal is the sum of quantity x price over all lines."""
    r = api.place([("NB-A5", 1), ("PEN-GEL", 3), ("LAMP-01", 1)])
    assert r.status_code == 201
    assert r.json()["subtotal_paise"] == 12_000 + 3 * 8_050 + 89_900


def test_tc_ord_004_get_order_returns_what_was_placed(api):
    """TC-ORD-004: GET /api/orders/{id} returns the persisted order."""
    placed = api.place([("BTL-STL", 1)]).json()
    got = api.get(f"/api/orders/{placed['id']}")
    assert got.status_code == 200 and got.json() == placed


def test_tc_ord_005_unknown_order_is_404(api):
    """TC-ORD-005: an order id that does not exist returns 404."""
    assert api.get("/api/orders/999999").status_code == 404


@pytest.mark.parametrize("email", ["plainaddress", "@no-local.com", "no-at.com", "user@nodot", "a b@c.com", "", "x@@y.com"])
def test_tc_val_001_invalid_email_is_rejected(api, email):
    """TC-VAL-001: equivalence partitions of invalid e-mail addresses return 422 and create nothing."""
    assert api.place([("NB-A5", 1)], email=email).status_code == 422
    assert api.get("/api/orders").json() == []


@pytest.mark.parametrize("email, masked", [
    ("a@b.co", "a***@b***.co"),
    ("first.last+tag@example.com", "f***@e***.com"),
    ("UPPER@EXAMPLE.COM", "U***@E***.COM"),
])
def test_tc_val_002_valid_email_is_accepted(api, db, email, masked):
    """TC-VAL-002: valid e-mail forms are accepted, and only a masked copy is stored and returned."""
    r = api.place([("NB-A5", 1)], email=email)
    assert r.status_code == 201
    assert r.json()["customer_email"] == masked
    assert api.get(f"/api/orders/{r.json()['id']}").json()["customer_email"] == masked
    assert db.execute("SELECT COUNT(*) FROM orders WHERE customer_email = ?", (email,)).fetchone()[0] == 0


def test_tc_val_003_empty_order_is_rejected(api):
    """TC-VAL-003: an order with no lines returns 422."""
    assert api.place([]).status_code == 422


def test_tc_val_004_line_count_boundary(api):
    """TC-VAL-004: 5 lines are accepted, 6 are rejected."""
    five = [("NB-A5", 1), ("PEN-GEL", 1), ("LAMP-01", 1), ("CBL-USBC", 1), ("BTL-STL", 1)]
    assert api.place(five).status_code == 201
    assert api.place(five + [("BAG-01", 1)]).status_code == 422


def test_tc_val_005_duplicate_sku_is_rejected(api):
    """TC-VAL-005: the same SKU twice in one order returns 422."""
    assert api.place([("NB-A5", 1), ("NB-A5", 2)]).status_code == 422


def test_tc_val_006_unknown_sku_is_rejected_and_nothing_is_stored(api):
    """TC-VAL-006: an unknown SKU returns 422 and no order or stock change happens."""
    before = api.stock("NB-A5")
    assert api.place([("NB-A5", 1), ("NOPE-999", 1)]).status_code == 422
    assert api.stock("NB-A5") == before and api.get("/api/orders").json() == []


@pytest.mark.parametrize("quantity", ["abc", 1.5, None])
def test_tc_val_007_non_integer_quantity_is_rejected(api, quantity):
    """TC-VAL-007: non-integer quantity types return 422."""
    r = api.post("/api/orders", {"customer_email": "qa@example.com", "items": [{"sku": "NB-A5", "quantity": quantity}]})
    assert r.status_code == 422


def test_tc_stk_001_insufficient_stock_is_409_and_atomic(api):
    """TC-STK-001: ordering more than the stock returns 409 and leaves every product untouched."""
    before = {p["sku"]: p["stock"] for p in api.get("/api/products").json()}
    r = api.place([("NB-A5", 1), ("BAG-01", 6)])  # BAG-01 has 5 in stock; NB-A5 line is valid
    assert r.status_code == 409
    assert {p["sku"]: p["stock"] for p in api.get("/api/products").json()} == before
    assert api.get("/api/orders").json() == []


def test_tc_stk_002_ordering_exactly_the_remaining_stock_succeeds(api):
    """TC-STK-002: boundary - quantity equal to stock is accepted and leaves stock at 0."""
    assert api.place([("BAG-01", 5)]).status_code == 201
    assert api.stock("BAG-01") == 0
    assert api.place([("BAG-01", 1)]).status_code == 409


def test_tc_ord_006_list_orders_filters_by_status(api):
    """TC-ORD-006: GET /api/orders?status= returns only matching orders; invalid status is 422."""
    a = api.place([("NB-A5", 1)]).json()["id"]
    b = api.place([("PEN-GEL", 1)]).json()["id"]
    api.post(f"/api/orders/{b}/pay")
    assert [o["id"] for o in api.get("/api/orders", params={"status": "PAID"}).json()] == [b]
    assert [o["id"] for o in api.get("/api/orders", params={"status": "PLACED"}).json()] == [a]
    assert api.get("/api/orders", params={"status": "BOGUS"}).status_code == 422
