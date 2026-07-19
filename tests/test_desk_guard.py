#!/usr/bin/env python3
"""Frozen referee for the DESK GUARD (bulk-in-chat sentinel extension).

The cost sentinel meters dollars; the desk guard meters BULK — tool_result
text landing in the chat context, the thing every later turn re-pays rent on
(CRATE_OPS: the chat is a desk, not a workshop). Pins:

  * small tool results stay silent;
  * a single result over TIER_SENTINEL_BULK_SINGLE proxy tokens injects
    "[desk-guard] ..." on PostToolUse, once (no repeat on refire), and a
    PreToolUse scan in between must not swallow it;
  * cumulative bulk injects at EACH multiple of TIER_SENTINEL_BULK_TOTAL;
  * sidecar tracks bulk_tokens (cumulative) and bulk_biggest_single;
  * desk-guard and cost-sentinel messages merge into ONE JSON emit;
  * malformed tool_result shapes count 0 and never raise (fail-open);
  * the existing sentinel suite (tests/test_session_sentinel.py) still passes.

Driver-authored, frozen BEFORE dispatch. Runs under pytest or standalone,
stdlib only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "experiments/breadth/hooks/session_sentinel.py"
SENTINEL_TESTS = REPO / "tests/test_session_sentinel.py"


def _tool_row(chars: int, as_string: bool = False, tid: str = "t1") -> dict:
    text = "x" * chars
    content = text if as_string else [{"type": "text", "text": text}]
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": content}]}}


def _cost_row(mid: str, out_tokens: int) -> dict:
    return {"type": "assistant", "message": {"id": mid, "model": "claude-fable-5",
            "usage": {"input_tokens": 100, "output_tokens": out_tokens,
                      "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}}}


def _write(transcript: Path, rows, append: bool = False) -> None:
    with open(transcript, "a" if append else "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _fire(event, transcript, sid, state_dir, extra_env=None):
    env = dict(os.environ, TIER_SENTINEL_STATE_DIR=str(state_dir))
    env.update(extra_env or {})
    payload = json.dumps({"session_id": sid, "transcript_path": str(transcript),
                          "hook_event_name": event})
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def _ctx(out) -> str:
    return out["hookSpecificOutput"]["additionalContext"]


# ─── silence below thresholds ────────────────────────────────────────

def test_small_results_stay_silent():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, [_tool_row(400, tid=f"t{i}") for i in range(3)])
        assert _fire("PostToolUse", transcript, "dg1", td) is None


# ─── single big result ───────────────────────────────────────────────

def test_single_big_result_injects_then_stays_quiet():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, [_tool_row(12_000)])  # 3000 proxy > default 2000
        out = _fire("PostToolUse", transcript, "dg2", td)
        assert out is not None, "big single result did not inject"
        ctx = _ctx(out)
        assert "[desk-guard]" in ctx
        assert "3000" in ctx          # names the size (plain integer)
        assert "docs/CRATE_OPS.md" in ctx
        assert "hand" in ctx
        assert "rent" in ctx
        # unchanged transcript: warned once, not every PostToolUse
        assert _fire("PostToolUse", transcript, "dg2", td) is None


def test_pretooluse_scan_does_not_swallow_single_warning():
    # PreToolUse may scan the big result first (it fires between response and
    # PostToolUse — same live-fire ordering pinned for the cost tiers); the
    # PostToolUse injection must survive that.
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, [_tool_row(12_000)])
        assert _fire("PreToolUse", transcript, "dg3", td) is None  # under cap: silent
        out = _fire("PostToolUse", transcript, "dg3", td)
        assert out is not None, "single-result warning swallowed by PreToolUse"
        assert "[desk-guard]" in _ctx(out)


def test_string_content_counted():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, [_tool_row(12_000, as_string=True)])
        out = _fire("PostToolUse", transcript, "dg4", td)
        assert out is not None
        assert "3000" in _ctx(out)


# ─── cumulative multiples ────────────────────────────────────────────

def test_cumulative_crossing_injects_at_each_multiple():
    env = {"TIER_SENTINEL_BULK_TOTAL": "1000",
           "TIER_SENTINEL_BULK_SINGLE": "1000000"}  # isolate the cumulative rule
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, [_tool_row(1800, tid="a"), _tool_row(1800, tid="b")])
        assert _fire("PostToolUse", transcript, "dg5", td, env) is None  # 900 < 1000
        _write(transcript, [_tool_row(1800, tid="c")], append=True)     # 1350
        out = _fire("PostToolUse", transcript, "dg5", td, env)
        assert out is not None, "first multiple crossing did not inject"
        ctx = _ctx(out)
        assert "[desk-guard]" in ctx and "1350" in ctx
        # same multiple, nothing new: silent
        assert _fire("PostToolUse", transcript, "dg5", td, env) is None
        _write(transcript, [_tool_row(1800, tid="d"), _tool_row(1800, tid="e")],
               append=True)                                             # 2250
        out2 = _fire("PostToolUse", transcript, "dg5", td, env)
        assert out2 is not None, "second multiple crossing did not inject"
        assert "2250" in _ctx(out2)


# ─── sidecar accounting ──────────────────────────────────────────────

def test_sidecar_tracks_bulk_totals():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, [_tool_row(400, tid="a"), _tool_row(12_000, tid="b"),
                            _tool_row(2000, tid="c")])
        _fire("PostToolUse", transcript, "dg6", td)
        state = json.loads((Path(td) / "dg6.json").read_text(encoding="utf-8"))
        assert state["bulk_tokens"] == 100 + 3000 + 500
        assert state["bulk_biggest_single"] == 3000


# ─── one JSON emit, merged with the cost sentinel ────────────────────

def test_merges_with_cost_warning_into_one_json():
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        rows = [_cost_row(f"w{i}", 250_000) for i in range(4)]  # $50 -> WARN
        rows.append(_tool_row(12_000))
        _write(transcript, rows)
        out = _fire("PostToolUse", transcript, "dg7", td)  # json.loads pins ONE object
        ctx = _ctx(out)
        assert "[cost-sentinel]" in ctx
        assert "[desk-guard]" in ctx


# ─── fail-open ───────────────────────────────────────────────────────

def test_fail_open_on_malformed_tool_results():
    rows = [
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": 42}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": [{"type": "text", "text": 5},
                                                {"no": "type"}, "bare"]}]}},
        {"type": "user", "message": {"content": "just a string"}},
        {"type": "user", "message": {"content": [None, 7, []]}},
        {"type": "user", "message": None},
    ]
    with tempfile.TemporaryDirectory() as td:
        transcript = Path(td) / "t.jsonl"
        _write(transcript, rows)
        # counts 0, injects nothing, exits 0 (asserted inside _fire)
        assert _fire("PostToolUse", transcript, "dg8", td) is None
        state = json.loads((Path(td) / "dg8.json").read_text(encoding="utf-8"))
        assert state.get("bulk_tokens", 0) == 0


# ─── the sentinel suite is untouched ─────────────────────────────────

def test_sentinel_suite_still_passes():
    proc = subprocess.run([sys.executable, str(SENTINEL_TESTS)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except Exception as e:  # noqa: BLE001 — any escape is a FAIL, not a crash
                fails += 1
                print(f"FAIL  {name}: {e!r}")
    print(("FAIL" if fails else "PASS") + " test_desk_guard")
    raise SystemExit(1 if fails else 0)
