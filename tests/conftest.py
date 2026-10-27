"""Black-box fixtures: the suite starts the real application as a subprocess and talks to it over HTTP."""
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "reports" / "screenshots"
UPI_SECRET = "test-only-upi-secret"  # the suite signs provider callbacks with it, as the pretend provider would
SCREENSHOTS.mkdir(parents=True, exist_ok=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("orderdesk") / "orderdesk.db"


@pytest.fixture(scope="session")
def base_url(db_path):
    port = _free_port()
    env = {**os.environ, "ORDERDESK_DB": str(db_path), "ORDERDESK_TEST_MODE": "1", "ORDERDESK_UPI_SECRET": UPI_SECRET}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if requests.get(f"{url}/api/health", timeout=0.5).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("application did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


class Api:
    def __init__(self, base_url: str):
        self.base, self.http = base_url, requests.Session()
        self.amounts = {}  # provider_txn -> amount, so callbacks carry it as the provider's would

    def get(self, path, **kw):
        return self.http.get(self.base + path, **kw)

    def post(self, path, json=None):
        return self.http.post(self.base + path, json=json)

    def place(self, items, email="qa@example.com", coupon=None):
        body = {"customer_email": email, "items": [{"sku": s, "quantity": q} for s, q in items]}
        if coupon is not None:
            body["coupon"] = coupon
        return self.post("/api/orders", body)

    def stock(self, sku) -> int:
        return next(p["stock"] for p in self.get("/api/products").json() if p["sku"] == sku)

    def pay(self, order_id, upi_id="success@sandbox"):
        r = requests.post(f"{self.base}/api/orders/{order_id}/payments", json={"upi_id": upi_id})  # thread-safe
        if r.status_code == 201:
            self.amounts[r.json()["provider_txn"]] = r.json()["amount_paise"]
        return r

    def callback(self, provider_txn, status, code=None, secret=UPI_SECRET, amount_paise="the payment's"):
        """Send the provider's callback, signed the way the pretend provider signs it (HMAC-SHA256 of the body)."""
        amount = self.amounts.get(provider_txn) if amount_paise == "the payment's" else amount_paise
        body = json.dumps({"provider_txn": provider_txn, "status": status, "code": code, "amount_paise": amount}).encode()
        headers = {"Content-Type": "application/json"}
        if secret is not None:
            headers["X-Upi-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return requests.post(f"{self.base}/api/payments/callback", data=body, headers=headers)


@pytest.fixture()
def api(base_url):
    client = Api(base_url)
    assert client.post("/api/test/reset").ok  # every test starts from the seeded state
    return client


@pytest.fixture()
def db(db_path, api):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session")
def screenshots() -> Path:
    return SCREENSHOTS
