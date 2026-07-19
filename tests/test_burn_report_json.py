"""Referee for burn_report_json_v1. Driver-authored, frozen."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "burn_report.py"


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def check(cond, msg):
    if not cond:
        print(f"FAIL test_burn_report_json: {msg}")
        sys.exit(1)


def approx(a, b):
    return abs(a - b) < 1e-9


def make_fixture(d):
    (d / "a.json").write_text(json.dumps({"cost_usd": 1.5, "tier": "T2"}))
    (d / "b.json").write_text(json.dumps({"cost_usd": 3.25}))
    (d / "c.json").write_text(json.dumps({"cost_usd": 3.25, "tier": "T0"}))
    (d / "d.json").write_text(json.dumps({"cost_usd": 0.1, "tier": None}))
    (d / "bad.json").write_text("not json {{")
    (d / "notdict.json").write_text("[1, 2, 3]")


def main():
    with tempfile.TemporaryDirectory() as td:
        full = Path(td) / "state"
        full.mkdir()
        make_fixture(full)
        empty = Path(td) / "empty"
        empty.mkdir()

        # 1. Text mode unchanged (populated). Expected order: cost DESC, sid ASC.
        r = run("--state-dir", str(full))
        check(r.returncode == 0, f"text mode exit {r.returncode}")
        expected_text = [
            "b  $3.25  -",
            "c  $3.25  T0",
            "a  $1.50  T2",
            "d  $0.10  -",
            "",
            "sessions: 4",
            "total: $8.10",
            "median: $1.50",
            "p90: $3.25",
        ]
        got = r.stdout.strip("\n").split("\n")
        check([ln.rstrip() for ln in got] == expected_text,
              f"text output changed: {got!r}")

        # 2. Text mode unchanged (empty).
        r = run("--state-dir", str(empty))
        check(r.returncode == 0, f"text empty exit {r.returncode}")
        check(r.stdout.strip() == "no sessions",
              f"text empty output changed: {r.stdout!r}")

        # 3. --json populated: exactly one JSON object, same data.
        r = run("--state-dir", str(full), "--json")
        check(r.returncode == 0, f"--json exit {r.returncode}")
        try:
            obj = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            check(False, f"--json stdout is not a single JSON object: {e}")
        check(isinstance(obj, dict), f"--json top level is {type(obj).__name__}")
        check(set(obj) == {"sessions", "count", "total", "median", "p90"},
              f"--json keys: {sorted(obj)}")
        check(obj["sessions"] == [
            {"sid": "b", "cost_usd": 3.25, "tier": None},
            {"sid": "c", "cost_usd": 3.25, "tier": "T0"},
            {"sid": "a", "cost_usd": 1.5, "tier": "T2"},
            {"sid": "d", "cost_usd": 0.1, "tier": None},
        ], f"--json sessions wrong: {obj['sessions']!r}")
        check(obj["count"] == 4, f"count {obj['count']!r}")
        check(approx(obj["total"], 8.1), f"total {obj['total']!r}")
        check(approx(obj["median"], 1.5), f"median {obj['median']!r}")
        check(approx(obj["p90"], 3.25), f"p90 {obj['p90']!r}")

        # 4. --json empty.
        r = run("--state-dir", str(empty), "--json")
        check(r.returncode == 0, f"--json empty exit {r.returncode}")
        try:
            obj = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            check(False, f"--json empty stdout not JSON: {e}")
        check(obj == {"sessions": [], "count": 0, "total": 0.0,
                      "median": 0.0, "p90": 0.0},
              f"--json empty object wrong: {obj!r}")

    print("PASS test_burn_report_json")


if __name__ == "__main__":
    main()
