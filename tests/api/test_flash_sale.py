"""Flash-sale race: many buyers at once for the last few units (REQ-STK-002)."""
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

pytestmark = pytest.mark.api

BUYERS, UNITS = 500, 5  # BAG-01 is seeded with exactly 5 units


def test_tc_stk_003_flash_sale_500_buyers_for_the_last_5_units(api, db, base_url):
    """TC-STK-003: 500 buyers order the last 5 backpacks at once; exactly 5 succeed, 495 get 409, and stock ends at 0, never below."""
    assert api.stock("BAG-01") == UNITS
    body = {"customer_email": "buyer@example.com", "items": [{"sku": "BAG-01", "quantity": 1}]}
    with ThreadPoolExecutor(max_workers=50) as pool:
        codes = list(pool.map(lambda _: requests.post(f"{base_url}/api/orders", json=body, timeout=60).status_code, range(BUYERS)))
    # Selling a unit that is not there would break the stock >= 0 constraint and show up here as a 500.
    assert {c: codes.count(c) for c in set(codes)} == {201: UNITS, 409: BUYERS - UNITS}
    assert api.stock("BAG-01") == 0
    assert db.execute("SELECT SUM(quantity) FROM order_items WHERE sku = 'BAG-01'").fetchone()[0] == UNITS
