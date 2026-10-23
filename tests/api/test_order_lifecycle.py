"""Order state machine and cancellation tests (REQ-LIF-*)."""
import pytest

pytestmark = pytest.mark.api


def _order(api, status="PLACED", sku="NB-A5", qty=2):
    oid = api.place([(sku, qty)]).json()["id"]
    path = {"PLACED": [], "PAID": ["pay"], "SHIPPED": ["pay", "ship"], "DELIVERED": ["pay", "ship", "deliver"], "CANCELLED": ["cancel"]}[status]
    for action in path:
        assert api.post(f"/api/orders/{oid}/{action}").status_code == 200
    return oid


def test_tc_lif_001_happy_path_through_all_states(api):
    """TC-LIF-001: PLACED -> PAID -> SHIPPED -> DELIVERED, each step returns the new status."""
    oid = api.place([("NB-A5", 1)]).json()["id"]
    for action, status in [("pay", "PAID"), ("ship", "SHIPPED"), ("deliver", "DELIVERED")]:
        r = api.post(f"/api/orders/{oid}/{action}")
        assert r.status_code == 200 and r.json()["status"] == status


@pytest.mark.parametrize("current, action", [
    ("PLACED", "ship"), ("PLACED", "deliver"),
    ("PAID", "pay"), ("PAID", "deliver"),
    ("SHIPPED", "pay"), ("SHIPPED", "ship"),
    ("DELIVERED", "pay"), ("DELIVERED", "ship"), ("DELIVERED", "deliver"),
    ("CANCELLED", "pay"), ("CANCELLED", "ship"), ("CANCELLED", "deliver"),
])
def test_tc_lif_002_invalid_transitions_return_409_and_keep_status(api, current, action):
    """TC-LIF-002: transitions that skip or repeat a state are rejected and the status is unchanged."""
    oid = _order(api, current)
    assert api.post(f"/api/orders/{oid}/{action}").status_code == 409
    assert api.get(f"/api/orders/{oid}").json()["status"] == current


@pytest.mark.parametrize("current", ["SHIPPED", "DELIVERED", "CANCELLED"])
def test_tc_lif_003_cancel_is_only_allowed_before_shipping(api, current):
    """TC-LIF-003: cancel is rejected once an order is SHIPPED, DELIVERED or already CANCELLED."""
    oid = _order(api, current)
    assert api.post(f"/api/orders/{oid}/cancel").status_code == 409
    assert api.get(f"/api/orders/{oid}").json()["status"] == current


@pytest.mark.parametrize("current", ["PLACED", "PAID"])
def test_tc_lif_004_cancel_restores_stock(api, current):
    """TC-LIF-004: cancelling a PLACED or PAID order returns its quantity to stock."""
    before = api.stock("NB-A5")
    oid = _order(api, current, qty=3)
    assert api.stock("NB-A5") == before - 3
    r = api.post(f"/api/orders/{oid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert api.stock("NB-A5") == before


def test_tc_lif_005_cancel_restores_every_line_of_a_multi_line_order(api):
    """TC-LIF-005: all lines of a cancelled order go back to stock, not just the first."""
    before = {s: api.stock(s) for s in ("NB-A5", "PEN-GEL")}
    oid = api.place([("NB-A5", 2), ("PEN-GEL", 4)]).json()["id"]
    api.post(f"/api/orders/{oid}/cancel")
    assert {s: api.stock(s) for s in before} == before


def test_tc_lif_006_unknown_order_and_unknown_action(api):
    """TC-LIF-006: transitions on a missing order are 404; an unknown action is 404."""
    assert api.post("/api/orders/999999/pay").status_code == 404
    oid = _order(api)
    assert api.post(f"/api/orders/{oid}/refund").status_code == 404
