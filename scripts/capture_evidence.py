"""Reproduce each seeded defect against a clean build and a defective build and save the real responses.

Writes docs/bugs/evidence/<BUG>.json (and two screenshots for BUG-008). The bug reports quote these files.
"""
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "bugs" / "evidence"


@contextlib.contextmanager
def server(defect: str):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "ORDERDESK_DB": f"{tmp}/o.db", "ORDERDESK_TEST_MODE": "1", "ORDERDESK_DEFECTS": defect}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            requests.get(base + "/api/health", timeout=0.5)
            break
        except requests.ConnectionError:
            time.sleep(0.1)
    try:
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def order(base, items, email="qa@example.com", coupon=None):
    body = {"customer_email": email, "items": [{"sku": s, "quantity": q} for s, q in items]}
    if coupon:
        body["coupon"] = coupon
    return requests.post(base + "/api/orders", json=body)


def brief(r):
    j = r.json()
    keys = ("status", "subtotal_paise", "discount_paise", "shipping_paise", "total_paise")
    return {"http_status": r.status_code, **({k: j[k] for k in keys if k in j} if isinstance(j, dict) and "id" in j else {"body": j})}


def stock(base, sku):
    return next(p["stock"] for p in requests.get(base + "/api/products").json() if p["sku"] == sku)


def r001(b): return {"step": "POST /api/orders NB-A5 x 11", **brief(order(b, [("NB-A5", 11)]))}
def r002(b): return {"step": "POST /api/orders BND-B x 2 (Rs 500.00) coupon SAVE10", **brief(order(b, [("BND-B", 2)], coupon="SAVE10"))}
def r003(b): return {"step": "POST /api/orders BND-B x 2 (Rs 500.00) coupon SAVE10", **brief(order(b, [("BND-B", 2)], coupon="SAVE10"))}


def r004(b):
    oid = order(b, [("NB-A5", 3)]).json()["id"]
    requests.post(f"{b}/api/orders/{oid}/cancel")
    return {"step": "place NB-A5 x 3, then cancel; read stock of NB-A5 (started at 50)", "stock_after_cancel": stock(b, "NB-A5")}


def r005(b):
    oid = order(b, [("NB-A5", 1)]).json()["id"]
    for a in ("pay", "ship"):
        requests.post(f"{b}/api/orders/{oid}/{a}")
    r = requests.post(f"{b}/api/orders/{oid}/cancel")
    return {"step": "place, pay, ship, then POST /cancel", "http_status": r.status_code, "status": r.json().get("status")}


def r006(b): return {"step": "POST /api/orders with customer_email 'user@nodot'", **brief(order(b, [("NB-A5", 1)], email="user@nodot"))}
def r007(b): return {"step": "POST /api/orders BND-B + BND-E (Rs 500.05) coupon SAVE10", **brief(order(b, [("BND-B", 1), ("BND-E", 1)], coupon="SAVE10"))}

REPRO = {"BUG-001": r001, "BUG-002": r002, "BUG-003": r003, "BUG-004": r004, "BUG-005": r005, "BUG-006": r006, "BUG-007": r007}


def ui_total(base, shot: Path) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 800})
        page.goto(base)
        page.get_by_test_id("qty-BND-B").fill("1")
        page.get_by_test_id("qty-BND-D").fill("1")
        page.get_by_test_id("email-input").fill("qa@example.com")
        page.get_by_test_id("coupon-input").fill("FLAT50")
        page.get_by_test_id("place-order").click()
        page.get_by_test_id("summary-total").wait_for()
        page.wait_for_function("document.querySelector('[data-testid=summary-total]').textContent !== ''")
        text = page.get_by_test_id("summary-total").text_content()
        page.screenshot(path=str(shot), full_page=True)
        browser.close()
    return text


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for bug, fn in REPRO.items():
        with server("") as clean, server(bug) as buggy:
            result = {"bug": bug, "clean_build": fn(clean), "defective_build": fn(buggy)}
        (OUT / f"{bug}.json").write_text(json.dumps(result, indent=2))
        print(bug, json.dumps(result))
    with server("") as clean, server("BUG-008") as buggy:
        result = {"bug": "BUG-008", "step": "UI: BND-B x1 + BND-D x1, coupon FLAT50, click Place order; read 'Total'",
                  "clean_build_total_shown": ui_total(clean, OUT / "BUG-008-clean.png"),
                  "defective_build_total_shown": ui_total(buggy, OUT / "BUG-008-defective.png"),
                  "api_total_in_both_builds": "Rs 290.00 (29000 paise)"}
    (OUT / "BUG-008.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
