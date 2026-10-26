"""Recompute the pretend UPI provider's decline rates (app/upi_provider.py) from UPI Pulse's published data.

Rates are for the payer's bank (NPCI's remitter table) over UPI Pulse's last 12 months, weighted by payments.
Usage: python scripts/upi_rates.py [path or URL of data.json]      (default: the published copy)
"""
import json
import sys
import urllib.request

URL = "https://anubhavkumarkanth.github.io/upi-pulse/data.json"


def rates(data: dict) -> tuple[float, float, str, str]:
    months, (first, last) = data["meta"]["months"], data["meta"]["last12"]
    rows = [r for r in data["summary"]["remitter"] if first <= months[r["m"]] <= last]
    vol = sum(r["vol"] for r in rows)
    return sum(r["bd"] * r["vol"] for r in rows) / vol, sum(r["td"] * r["vol"] for r in rows) / vol, first, last


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else URL
    with (urllib.request.urlopen(src, timeout=30) if src.startswith("http") else open(src, encoding="utf-8")) as f:
        bd, td, first, last = rates(json.load(f))
    print(f"{first[:7]} to {last[:7]}, payer's bank: business declines {bd:.2f}%, technical declines {td:.2f}%")
