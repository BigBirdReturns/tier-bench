#!/usr/bin/env python3
"""Regression tests for the session-burn hook (PR #84 follow-up finding 1).

The crash shape: usage rows where the scalar `cache_creation_input_tokens` is
0 (present) alongside a `cache_creation` breakdown OBJECT — `0 or dict`
selected the dict and int+dict raised TypeError, killing the Stop hook before
it wrote state. These tests pin the precedence rules and the fail-safe.

Runs under pytest or standalone, stdlib only.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "experiments/breadth/hooks/session_burn_hook.py"

spec = importlib.util.spec_from_file_location("session_burn_hook", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def test_present_zero_scalar_with_nested_object():
    # the reproduced crash shape: scalar 0 is PRESENT and must be honored
    u = {"input_tokens": 1, "output_tokens": 2,
         "cache_creation_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 3}}
    assert hook._new_tokens(u) == 3  # 1 + 2 + 0 (scalar honored, dict ignored)


def test_absent_scalar_falls_back_to_nested_sum():
    u = {"input_tokens": 1, "output_tokens": 2,
         "cache_creation": {"ephemeral_5m_input_tokens": 3,
                            "ephemeral_1h_input_tokens": 4}}
    assert hook._new_tokens(u) == 10  # 1 + 2 + (3 + 4)


def test_malformed_values_count_zero_never_raise():
    cases = [
        {"input_tokens": "x", "output_tokens": None,
         "cache_creation_input_tokens": "bad", "cache_creation": {"a": "b"}},
        {"cache_creation": "weird"},
        {"input_tokens": True, "cache_creation": {"a": None, "b": 2}},
        {},
    ]
    expected = [0, 0, 2, 0]  # bools/strings/None are not counts
    for u, want in zip(cases, expected):
        assert hook._new_tokens(u) == want, (u, hook._new_tokens(u), want)


def test_scalar_present_nonzero_wins_over_nested():
    u = {"cache_creation_input_tokens": 7, "cache_creation": {"a": 100}}
    assert hook._new_tokens(u) == 7


def test_hook_end_to_end_with_breakdown_row(tmp_path=None):
    # a transcript containing the crash-shape row must produce a burn row
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        transcript = d / "t.jsonl"
        rows = [
            {"type": "assistant", "message": {"usage": {
                "input_tokens": 10, "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_creation": {"ephemeral_5m_input_tokens": 99}}}},
            {"type": "assistant", "message": {"usage": {
                "input_tokens": 1, "output_tokens": 1,
                "cache_creation": {"ephemeral_1h_input_tokens": 4}}}},
        ]
        transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        env = dict(os.environ)
        env["TIER_BENCH_ACCOUNT"] = "test-tier"
        payload = json.dumps({"session_id": "hooktest-sess",
                              "transcript_path": str(transcript),
                              "hook_event_name": "Stop"})
        p = subprocess.run([sys.executable, str(HOOK)], input=payload,
                           capture_output=True, text=True, env=env)
        assert p.returncode == 0, p.stderr
        burn = REPO / "experiments/breadth/run/burn_log.jsonl"
        lines = [json.loads(l) for l in burn.read_text().splitlines() if l.strip()]
        mine = [l for l in lines if l.get("session") == "hooktest-sess"]
        try:
            assert len(mine) == 1, f"expected exactly one row, got {len(mine)}"
            # 10+5+0 (scalar-zero honored) + 1+1+4 (nested fallback) = 21
            assert mine[0]["tokens"] == 21, mine[0]
            assert mine[0]["calls"] == 2
            assert mine[0]["account"] == "test-tier"
        finally:
            # remove the test row — burn_log is committed telemetry
            keep = [l for l in burn.read_text().splitlines()
                    if l.strip() and json.loads(l).get("session") != "hooktest-sess"]
            burn.write_text("\n".join(keep) + "\n")
            state = REPO / "experiments/breadth/run/.burn_state/hooktest-sess.json"
            state.unlink(missing_ok=True)


def test_closure_is_monotonic_sessionend_then_stop():
    # A Stop checkpoint AFTER SessionEnd may refresh counts but must never
    # strip closed:true or the terminal event name (the ca75826 regression).
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        transcript = d / "t.jsonl"
        transcript.write_text(json.dumps(
            {"type": "assistant", "message": {"usage": {
                "input_tokens": 5, "output_tokens": 5}}}) + "\n")
        env = dict(os.environ)
        env["TIER_BENCH_ACCOUNT"] = "test-tier"
        burn = REPO / "experiments/breadth/run/burn_log.jsonl"

        def fire(event):
            payload = json.dumps({"session_id": "hooktest-mono",
                                  "transcript_path": str(transcript),
                                  "hook_event_name": event})
            p = subprocess.run([sys.executable, str(HOOK)], input=payload,
                               capture_output=True, text=True, env=env)
            assert p.returncode == 0, p.stderr

        try:
            fire("SessionEnd")  # terminal row: closed=true, event=SessionEnd
            # session emits one more turn, then a trailing Stop flush arrives
            with transcript.open("a") as f:
                f.write(json.dumps({"type": "assistant", "message": {"usage": {
                    "input_tokens": 3, "output_tokens": 4}}}) + "\n")
            fire("Stop")
            rows = [json.loads(l) for l in burn.read_text().splitlines()
                    if l.strip() and json.loads(l).get("session") == "hooktest-mono"]
            assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
            r = rows[0]
            assert r["closed"] is True, "closed:true disappeared after a later Stop"
            assert r["event"] == "SessionEnd", f"terminal event lost: {r['event']}"
            assert r["tokens"] == 17, f"counts not refreshed: {r['tokens']}"  # 10 + 7
            assert r["calls"] == 2
        finally:
            keep = [l for l in burn.read_text().splitlines()
                    if l.strip() and json.loads(l).get("session") != "hooktest-mono"]
            burn.write_text("\n".join(keep) + "\n")
            (REPO / "experiments/breadth/run/.burn_state/hooktest-mono.json").unlink(missing_ok=True)


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
