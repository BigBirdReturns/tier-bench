#!/usr/bin/env python3
"""Regression tests for the cost sentinel (lesson 18 enforcement layer).

Pins the accounting rules (duplicate message.id rows billed once, cache reads
INCLUDED at 0.1x, pessimistic pricing for unknown models), the tier ladder,
the PreToolUse hard-cap deny with operator-attested ack, and the fail-open
guarantee. Runs under pytest or standalone, stdlib only.
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
HOOK = REPO / "experiments/breadth/hooks/session_sentinel.py"

spec = importlib.util.spec_from_file_location("session_sentinel", HOOK)
sentinel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sentinel)

FABLE = {"claude-fable-5": (10.0, 50.0)}


def _row(mid, out_tokens, reads=0, writes=0, model="claude-fable-5"):
    return {"type": "assistant", "message": {"id": mid, "model": model,
            "usage": {"input_tokens": 100, "output_tokens": out_tokens,
                      "cache_read_input_tokens": reads,
                      "cache_creation_input_tokens": writes}}}


# ─── pricing ─────────────────────────────────────────────────────────

def test_row_cost_includes_cache_reads():
    # the $700 finding: cache reads ARE the bill. 10M reads at 0.1x of $10/1M = $10.
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 10_000_000}
    assert abs(sentinel.row_cost_usd("claude-fable-5", u, FABLE) - 10.0) < 1e-9


def test_row_cost_cache_write_multiplier():
    u = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    assert abs(sentinel.row_cost_usd("claude-fable-5", u, FABLE) - 12.5) < 1e-9


def test_unknown_model_priced_pessimistically():
    rates = {"cheap": (1.0, 5.0), "dear": (10.0, 50.0)}
    u = {"input_tokens": 0, "output_tokens": 1_000_000}
    assert sentinel.row_cost_usd("never-heard-of-it", u, rates) == 50.0


def test_cache_write_scalar_zero_wins_over_breakdown():
    # inherited from the burn hook's reproduced crash shape
    u = {"input_tokens": 0, "output_tokens": 0,
         "cache_creation_input_tokens": 0,
         "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}
    assert sentinel.row_cost_usd("claude-fable-5", u, FABLE) == 0.0


def test_malformed_usage_never_raises():
    u = {"input_tokens": "x", "output_tokens": None,
         "cache_read_input_tokens": True, "cache_creation": "weird"}
    assert sentinel.row_cost_usd("claude-fable-5", u, FABLE) == 0.0


# ─── dedup + incremental scan ────────────────────────────────────────

def _scan(rows, state=None):
    state = state if state is not None else {}
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        path = Path(f.name)
    try:
        sentinel.scan_new(path, state, FABLE)
    finally:
        path.unlink(missing_ok=True)
    return state


def test_duplicate_message_id_billed_once():
    # one API response is written as several rows sharing message.id
    once = _scan([_row("m1", 10_000)])["cost_usd"]
    twice = _scan([_row("m1", 10_000), _row("m1", 10_000)])["cost_usd"]
    assert abs(once - twice) < 1e-9


def test_duplicate_id_fuller_row_bills_the_delta():
    state = _scan([_row("m1", 10_000), _row("m1", 20_000)])
    assert abs(state["cost_usd"] - _scan([_row("m1", 20_000)])["cost_usd"]) < 1e-9


def test_refire_does_not_double_count():
    rows = [_row("a", 10_000), _row("b", 10_000)]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        path = Path(f.name)
    try:
        state = {}
        sentinel.scan_new(path, state, FABLE)
        first = state["cost_usd"]
        sentinel.scan_new(path, state, FABLE)  # same offset, nothing new
        assert state["cost_usd"] == first
    finally:
        path.unlink(missing_ok=True)


def test_partial_trailing_line_left_for_next_fire():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(_row("a", 10_000)) + "\n")
        f.write('{"truncated')  # no newline — a live writer mid-line
        path = Path(f.name)
    try:
        state = {}
        sentinel.scan_new(path, state, FABLE)
        assert state["last_msg_id"] == "a"
        # offset stops after the last complete line (platform newlines vary)
        data = path.read_bytes()
        assert state["offset"] == data.rfind(b"\n") + 1 < len(data)
    finally:
        path.unlink(missing_ok=True)


# ─── tier ladder ─────────────────────────────────────────────────────

def test_tier_ladder():
    th = {"NOTICE": 10.0, "WARN": 40.0, "CRITICAL": 100.0, "HARDCAP": 200.0}
    assert sentinel.tier_of(5, th) is None
    assert sentinel.tier_of(10, th) == "NOTICE"
    assert sentinel.tier_of(99.99, th) == "WARN"
    assert sentinel.tier_of(150, th) == "CRITICAL"
    assert sentinel.tier_of(10_000, th) == "HARDCAP"


# ─── end-to-end via subprocess (the wired path) ──────────────────────

def _fire(event, transcript, sid, state_dir, extra_env=None):
    env = dict(os.environ, TIER_SENTINEL_STATE_DIR=str(state_dir))
    env.update(extra_env or {})
    payload = json.dumps({"session_id": sid, "transcript_path": str(transcript),
                          "hook_event_name": event})
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def test_hardcap_denies_then_ack_reopens():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        with open(transcript, "w") as f:
            for i in range(10):  # 10 x 500k out x $50/1M = $250 > $200 cap
                f.write(json.dumps(_row(f"b{i}", 500_000)) + "\n")
        out = _fire("PreToolUse", transcript, "s1", td)
        hso = out["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "hard cap" in hso["permissionDecisionReason"].lower()
        # operator-attested raise: a human writes a new cap; sentinel reopens
        (Path(td) / "s1.ack").write_text("400\n")
        assert _fire("PreToolUse", transcript, "s1", td) is None


def test_warn_tier_injects_context_on_post_tool_use():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        with open(transcript, "w") as f:
            for i in range(4):  # $50 -> WARN
                f.write(json.dumps(_row(f"w{i}", 250_000)) + "\n")
        out = _fire("PostToolUse", transcript, "s2", td)
        assert "handoff crate" in out["hookSpecificOutput"]["additionalContext"]
        # unchanged transcript, same tier, under re-warn cadence: silent
        assert _fire("PostToolUse", transcript, "s2", td) is None


def test_pretooluse_does_not_swallow_crossing_warning():
    # Live-fire finding 2026-07-18 (session ccb7a62c): PreToolUse fires between
    # the first response and the first PostToolUse; it must not record the tier,
    # or PostToolUse sees crossed=False and the crossing warning is lost.
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        with open(transcript, "w") as f:
            for i in range(4):  # $50 -> WARN
                f.write(json.dumps(_row(f"w{i}", 250_000)) + "\n")
        assert _fire("PreToolUse", transcript, "s5", td) is None  # under cap: silent
        out = _fire("PostToolUse", transcript, "s5", td)
        assert out is not None, "crossing warning swallowed by PreToolUse"
        assert "systemMessage" in out  # it must present as a crossing, not a re-warn


def test_dated_model_id_prefix_matches_registry():
    rates = {"claude-haiku-4-5": (1.0, 5.0), "claude-haiku-4": (99.0, 99.0),
             "claude-fable-5": (10.0, 50.0)}
    # longest prefix wins; dated transcript ids map to their registry family
    assert sentinel._rate_for("claude-haiku-4-5-20251001", rates) == (1.0, 5.0)
    assert sentinel._rate_for("claude-fable-5", rates) == (10.0, 50.0)
    # no match at all -> dearest registry row (here the synthetic 99-rate key)
    assert sentinel._rate_for("gpt-99", rates) == (99.0, 99.0)
    assert sentinel._rate_for("", rates) == (99.0, 99.0)


def test_under_notice_stays_silent():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        transcript.write_text(json.dumps(_row("m1", 10_000)) + "\n")
        assert _fire("UserPromptSubmit", transcript, "s3", td) is None


def test_env_thresholds_override():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        transcript.write_text(json.dumps(_row("m1", 10_000)) + "\n")  # ~$0.60
        out = _fire("UserPromptSubmit", transcript, "s4", td,
                    {"TIER_SENTINEL_NOTICE_USD": "0.25"})
        assert "notice" in out["hookSpecificOutput"]["additionalContext"]


def test_fail_open_on_garbage_stdin():
    proc = subprocess.run([sys.executable, str(HOOK)], input="not json",
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL  {name}: {e}")
    raise SystemExit(1 if fails else 0)
