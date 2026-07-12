#!/usr/bin/env python3
"""Tests for scripts/validate_oss_replay_field.py — the field gate bites.

Runs under pytest or standalone, stdlib only.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import validate_oss_replay_field as vf  # noqa: E402


def _entry() -> dict:
    return json.loads((REPO / "data/oss_replay/field.jsonl").read_text(encoding="utf-8").splitlines()[0])


def test_committed_field_is_valid():
    rows = vf._load_field(vf.FIELD)
    assert rows, "expected the fnmatch worked entry"
    assert vf.validate_field(rows) == []


def test_license_gate_bites():
    e = _entry()
    e["upstream"]["license"] = "GPL-3.0"
    errors = vf.validate_field([e])
    assert any("not allowlisted" in x for x in errors)


def test_vendored_hash_drift_bites():
    e = _entry()
    e["upstream"]["sha256"]["fnmatch.py"] = "0" * 64
    errors = vf.validate_field([e])
    assert any("drifted" in x for x in errors)


def test_missing_vendored_file_bites():
    e = _entry()
    e["upstream"]["sha256"]["nonexistent.py"] = "0" * 64
    errors = vf.validate_field([e])
    assert any("vendored file missing" in x for x in errors)


def test_gameable_task_refused():
    e = _entry()
    e["task_manifest"] = "tasks/t0_format_whitespace_002.json"
    errors = vf.validate_field([e])
    assert any("hidden-graded" in x for x in errors)


def test_unknown_capture_id_bites():
    e = _entry()
    e["capture_links"][0]["capture_id"] = "no_such_capture"
    errors = vf.validate_field([e])
    assert any("unknown capture_id" in x for x in errors)


def test_duplicate_distinct_item_bites():
    a, b = _entry(), _entry()
    b["entry_id"] = "ossrf_other_002"
    errors = vf.validate_field([a, b])
    assert any("duplicate distinct_work_item_id" in x for x in errors)


def test_ledger_spent_item_bites():
    e = _entry()
    spent = sorted(vf._capture_replay_ids())
    assert spent, "expected replay ids in the capture ledger"
    e["capture_links"][0]["distinct_work_item_id"] = spent[0]
    errors = vf.validate_field([e])
    assert any("same-instance rule" in x for x in errors)


def test_replayed_requires_receipt():
    e = _entry()
    e["status"] = "replayed"
    errors = vf.validate_field([e])
    assert any("requires at least one replay receipt" in x for x in errors)


def test_entries_never_carry_amortization_credit():
    e = _entry()
    e["validated_replays"] = 1
    errors = vf.validate_field([e])
    assert any("capture ledger only" in x for x in errors)


def test_bad_ref_commit_bites():
    e = _entry()
    e["upstream"]["ref_commit"] = "v3.12.0"
    errors = vf.validate_field([e])
    assert any("40-hex commit" in x for x in errors)


def _run_standalone() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
