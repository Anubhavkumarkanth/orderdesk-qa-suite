"""Black-box fixtures: the suite starts the real application as a subprocess and talks to it over HTTP."""
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
    env = {**os.environ, "ORDERDESK_DB": str(db_path), "ORDERDESK_TEST_MODE": "1"}
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
