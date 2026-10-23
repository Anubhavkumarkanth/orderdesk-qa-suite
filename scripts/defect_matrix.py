"""Run the whole suite once per seeded defect and record which tests catch it.

A defect is "detected" when at least one test fails with only that defect switched on.
Also runs a clean build and checks that it is fully green.
Usage: python scripts/defect_matrix.py            (writes reports/defect-matrix.md and .json)
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.defects import ALL  # noqa: E402

REPORTS = ROOT / "reports"
EXPECTED_MIN = 1  # every defect must be caught by at least this many tests


def run(defect: str | None) -> tuple[int, list[str], int]:
    xml = REPORTS / f"junit-{defect or 'clean'}.xml"
    env = {**os.environ, "ORDERDESK_DEFECTS": defect or ""}
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={xml}", "-p", "no:cacheprovider"],
                          cwd=ROOT, env=env, capture_output=True, text=True)
    cases = ET.parse(xml).getroot().iter("testcase")
    failed, total = [], 0
    for c in cases:
        total += 1
        if c.find("failure") is not None or c.find("error") is not None:
            failed.append(f"{c.get('classname').replace('tests.', '').replace('.', '/')}::{c.get('name')}")
    xml.unlink()
    return proc.returncode, failed, total


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    results, ok = {}, True
    code, failed, total = run(None)
    results["clean"] = {"failed": failed, "total": total}
    if failed:
        ok = False
    for bug in ALL:
        code, failed, total = run(bug)
        results[bug] = {"failed": failed, "total": total}
        if len(failed) < EXPECTED_MIN:
            ok = False
        print(f"{bug}: {len(failed)} of {total} tests fail", flush=True)
    (REPORTS / "defect-matrix.json").write_text(json.dumps(results, indent=2))
    lines = ["# Defect detection matrix", "",
             f"Each row runs the full suite ({results['clean']['total']} tests) with only that defect switched on.", "",
             "| Defect | Tests failing | Caught by |", "|---|---:|---|"]
    lines.append(f"| none (clean build) | {len(results['clean']['failed'])} | all {results['clean']['total']} tests pass |"
                 if not results["clean"]["failed"] else f"| none (clean build) | {len(results['clean']['failed'])} | UNEXPECTED FAILURES |")
    for bug in ALL:
        f = results[bug]["failed"]
        shown = "<br>".join(f"`{n}`" for n in f[:6]) + (f"<br>...and {len(f) - 6} more" if len(f) > 6 else "")
        lines.append(f"| {bug} | {len(f)} | {shown or 'NOT DETECTED'} |")
    (REPORTS / "defect-matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("clean build failures:", len(results["clean"]["failed"]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
