#!/usr/bin/env python3
"""SessionEnd / Stop hook — auto-append this session's driver-lane burn to the
quota burn log, so the gauge stops needing a human to extract usage by hand.

The manual step this replaces: read the main-session transcript, sum assistant-row
usage (input + output + cache_write; cache reads excluded — they bill ~0.1x and
the whole gauge is calibrated on "new tokens"), and append a `spend` row to
experiments/breadth/run/burn_log.jsonl. quota.py windows those rows between the
operator-attested `limit_hit` markers.

Design decisions that matter:

  * INCREMENTAL. State per session (byte offset + running totals) lives in a
    gitignored sidecar, so each fire reads only the NEW transcript bytes. A Stop
    hook fires every turn; re-parsing a multi-MB Max20x transcript each time would
    be wasteful, so we never re-read what we already counted.
  * IDEMPOTENT. The burn row is UPSERTed, keyed by session_id (`session` field,
    `auto: true`). Fire it 300 times in a session and burn_log ends with exactly
    ONE accurate row for that session — the latest cumulative total. Survives an
    abrupt container reclaim: the last Stop before death already wrote the total.
  * ACCOUNT-TAGGED. A Plus wall and a Max20x wall are DIFFERENT meters — pooling
    them makes SAFE meaningless. Every row carries `account` from $TIER_BENCH_ACCOUNT
    (default "unknown") so quota.py can gauge per-account (see `--account`).
  * FAIL-SAFE. Any error → exit 0, note to stderr. A telemetry hook must never
    block or fail the session. It also never writes a `limit_hit` — closing a
    window is an operator-attested act (adapt.py GATED spirit), not an automatic one.

Wired via .claude/settings.json (SessionEnd finalizes; Stop checkpoints).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BURN_LOG = REPO / "experiments/breadth/run/burn_log.jsonl"
STATE_DIR = REPO / "experiments/breadth/run/.burn_state"


def _usage_of(obj: dict) -> dict | None:
    """Pull the usage block off a transcript row, tolerating both shapes
    (top-level `usage` or nested under `message`)."""
    u = obj.get("usage")
    if isinstance(u, dict):
        return u
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        return msg["usage"]
    return None


def _num(v) -> int:
    """A usage field as an int; anything non-numeric counts as 0 (telemetry
    must tolerate malformed rows, never crash on them)."""
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _cache_write(u: dict) -> int:
    """Cache-write tokens. The scalar `cache_creation_input_tokens` is the
    total and is honored whenever PRESENT — including when it is 0. Only when
    it is absent (or non-numeric) do we fall back to the `cache_creation`
    breakdown object, summing its numeric values. (`0 or breakdown` would
    select the dict and crash the arithmetic — the exact bug this replaces.)"""
    v = u.get("cache_creation_input_tokens")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    cc = u.get("cache_creation")
    if isinstance(cc, dict):
        return sum(_num(x) for x in cc.values())
    return _num(cc)


def _new_tokens(u: dict) -> int:
    """New tokens = input + output + cache_write. Cache READS are excluded
    (~0.1x bill; the gauge's established convention, per BURN_LOG_README)."""
    return _num(u.get("input_tokens")) + _num(u.get("output_tokens")) + _cache_write(u)


def _scan_new(transcript: Path, offset: int) -> tuple[int, int, int]:
    """Read transcript bytes from `offset` to the last COMPLETE line. Returns
    (new_offset, delta_calls, delta_tokens). Partial trailing line (live session
    still writing) is left for the next fire."""
    data = transcript.read_bytes()
    if offset > len(data):  # transcript rotated/truncated → recount from 0
        offset = 0
    chunk = data[offset:]
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return offset, 0, 0  # no complete new line yet
    complete = chunk[: last_nl + 1]
    calls = tokens = 0
    for raw in complete.splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        u = _usage_of(obj)
        if u is None:
            continue
        # Count any row that carries usage (assistant turns) — matches the manual
        # "assistant-row usage" extraction the README documents.
        calls += 1
        tokens += _new_tokens(u)
    return offset + len(complete), calls, tokens


def _upsert(row: dict) -> None:
    """Replace the auto row for this session in burn_log.jsonl (preserving every
    other line verbatim and in place), else append. Atomic via temp + replace.

    CLOSURE IS MONOTONIC. `closed: true` means "a SessionEnd event has been
    observed for this session"; once set it never disappears, and the terminal
    event name is retained — a later Stop checkpoint may only refresh the
    counts (the harness can flush trailing Stop events after a SessionEnd).
    Without this, a late checkpoint silently reopens a finalized session row."""
    sid = row["session"]
    lines: list[str] = []
    replaced = False
    if BURN_LOG.exists():
        for raw in BURN_LOG.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                lines.append(raw)  # keep unparseable lines untouched
                continue
            if obj.get("auto") and obj.get("session") == sid:
                if obj.get("closed"):
                    row["closed"] = True
                    row["event"] = obj.get("event", row.get("event"))
                lines.append(json.dumps(row, ensure_ascii=False))
                replaced = True
            else:
                lines.append(raw)
    if not replaced:
        lines.append(json.dumps(row, ensure_ascii=False))
    BURN_LOG.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(BURN_LOG.parent), prefix=".burnlog.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, BURN_LOG)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main() -> int:
    try:
        return _main()
    except Exception as e:  # noqa: BLE001 — telemetry must never block the session
        print(f"[session_burn_hook] suppressed: {e!r}", file=sys.stderr)
        return 0


def _main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # nothing to do; never block the session

    sid = payload.get("session_id")
    tpath = payload.get("transcript_path")
    event = payload.get("hook_event_name", "")
    if not sid or not tpath:
        return 0
    transcript = Path(tpath).expanduser()
    if not transcript.exists():
        return 0

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{sid}.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"offset": 0, "calls": 0, "tokens": 0}

    try:
        new_offset, dc, dt = _scan_new(transcript, int(state.get("offset", 0)))
    except OSError:
        return 0
    state["offset"] = new_offset
    state["calls"] = int(state.get("calls", 0)) + dc
    state["tokens"] = int(state.get("tokens", 0)) + dt

    account = os.environ.get("TIER_BENCH_ACCOUNT", "unknown")
    row = {
        "type": "spend",
        "calls": state["calls"],
        "tokens": state["tokens"],
        "model": "driver-session",
        "lane": "driver",
        "account": account,
        "session": sid,
        "auto": True,
        "event": event,
        "source": ("auto hook: main-session transcript assistant-row usage "
                   "(in+out+cache_write; cache reads excluded)"),
    }
    if event == "SessionEnd":
        row["closed"] = True

    try:
        state_file.write_text(json.dumps(state), encoding="utf-8")
        _upsert(row)
    except OSError as e:
        print(f"[session_burn_hook] write failed: {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
