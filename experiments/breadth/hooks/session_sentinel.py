#!/usr/bin/env python3
"""Cost sentinel — the harness-enforced layer of "the driver is not exempt"
(LESSONS.md lesson 18, mechanism follow-through).

The burn hook (session_burn_hook.py) is telemetry: it records the driver
lane's burn after the fact. This hook is enforcement: it watches the SAME
main-loop transcript live and pushes escalating warnings INTO the model's
context as dollar thresholds are crossed, ending in a mechanical gate. The
model cannot skip it, forget it, or rationalize past it — the harness runs
it, not the model. That is the point: no model reliably turns its cost
discipline on itself while incentivized to keep going (measured all day,
2026-07-18; the $700 main loop that motivated this was run WITH lesson 7
in context).

Wired to three events (.claude/settings.json):

  * UserPromptSubmit — a gauge line each user turn once burn >= NOTICE.
  * PostToolUse      — escalating warnings mid-turn: on every tier crossing,
                       then on a per-tier re-warn cadence. A long autonomous
                       turn cannot outrun the sentinel between user turns.
  * PreToolUse       — the gate. At >= HARDCAP every tool call is DENIED
                       with instructions to write the handoff crate and end
                       the turn. Raising the cap is an operator-attested act
                       (adapt.py GATED spirit): a human writes a new cap
                       into the session's .ack file; the model cannot.

Unlike the burn gauge (new-token convention, cache reads excluded), the
sentinel meters DOLLARS with cache reads included — the $700 finding was
that cache reads (618M tokens at ~0.1x) WERE the bill. Rates come from
models.json (input/output per 1M; cache_write = 1.25x input, cache_read =
0.1x input, the provider's standard multipliers). Unknown models are priced
at the registry's most expensive Anthropic row — the sentinel must
overestimate, never underestimate.

Accounting hazard pinned by tests: one API response is written to the
transcript as SEVERAL rows sharing one `message.id`, each repeating the
same usage block. Rows are deduped by consecutive message id, keeping the
max-cost row, so a response is billed once.

Fail-safety: every event fails OPEN (exit 0, note to stderr). A broken
sentinel must never deny work or corrupt a session — it just goes silent,
and the burn hook still records the spend.

Thresholds (USD, env-overridable):
  TIER_SENTINEL_NOTICE_USD   default 10
  TIER_SENTINEL_WARN_USD     default 40
  TIER_SENTINEL_CRITICAL_USD default 100
  TIER_SENTINEL_HARDCAP_USD  default 200

Operator override for one session:
  echo 400 > experiments/breadth/run/.sentinel_state/<session_id>.ack

DESK GUARD — same mechanism, a different meter: not dollars but tool-result
TEXT landing in the chat context (proxy tokens = chars // 4), the thing
every later turn re-pays rent on (CRATE_OPS: the chat is a desk, not a
workshop). PostToolUse-only: injects once when a single tool_result crosses
TIER_SENTINEL_BULK_SINGLE, and again at each multiple of
TIER_SENTINEL_BULK_TOTAL crossed cumulatively. Merges into the same single
JSON emit as the cost-sentinel warning when both are due.

Desk guard thresholds (proxy tokens, env-overridable):
  TIER_SENTINEL_BULK_SINGLE  default 2000
  TIER_SENTINEL_BULK_TOTAL   default 20000
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MODELS_JSON = REPO / "models.json"


def _state_dir() -> Path:
    """Sidecar dir for per-session state; env-overridable so tests never
    write into the repo's run/ tree."""
    override = os.environ.get("TIER_SENTINEL_STATE_DIR")
    return Path(override) if override else REPO / "experiments/breadth/run/.sentinel_state"

CACHE_WRITE_MULT = 1.25  # x input rate — provider standard (5m/1h both billed >= 1.25x)
CACHE_READ_MULT = 0.10   # x input rate

TIERS = ("NOTICE", "WARN", "CRITICAL", "HARDCAP")
_DEFAULTS = {"NOTICE": 10.0, "WARN": 40.0, "CRITICAL": 100.0, "HARDCAP": 200.0}
# Once inside a tier, re-warn on PostToolUse every N dollars of further burn
# (0 = tier-crossing warning only, no repeats).
REWARN_STEP = {"NOTICE": 0.0, "WARN": 20.0, "CRITICAL": 10.0, "HARDCAP": 5.0}

# Desk guard thresholds (proxy tokens).
_BULK_DEFAULTS = {"SINGLE": 2000, "TOTAL": 20000}


def thresholds() -> dict[str, float]:
    out = {}
    for t in TIERS:
        try:
            out[t] = float(os.environ.get(f"TIER_SENTINEL_{t}_USD", _DEFAULTS[t]))
        except ValueError:
            out[t] = _DEFAULTS[t]
    return out


def bulk_thresholds() -> dict[str, int]:
    """Desk guard thresholds (proxy tokens), env-overridable with fail-open defaults."""
    out = {}
    for k in ("SINGLE", "TOTAL"):
        try:
            val = os.environ.get(f"TIER_SENTINEL_BULK_{k}", str(_BULK_DEFAULTS[k]))
            out[k] = int(val)
        except (ValueError, TypeError):
            out[k] = _BULK_DEFAULTS[k]
    return out


# ─── pricing ─────────────────────────────────────────────────────────


def _load_rates() -> dict[str, tuple[float, float]]:
    """model -> (input_per_1M, output_per_1M) from the repo registry."""
    try:
        models = json.loads(MODELS_JSON.read_text(encoding="utf-8")).get("models", {})
        return {
            name: (float(info.get("input_per_1M", 0)), float(info.get("output_per_1M", 0)))
            for name, info in models.items()
        }
    except Exception:
        return {}


def _fallback_rate(rates: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """Most expensive known rate — unknown models are priced pessimistically."""
    if rates:
        return max(rates.values(), key=lambda r: r[0] + r[1])
    return (10.0, 50.0)  # claude-fable-5 published rates, last-resort constant


def _num(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _cache_write_tokens(u: dict) -> int:
    """Same precedence as the burn hook: present scalar wins (even 0), else
    sum the cache_creation breakdown object."""
    v = u.get("cache_creation_input_tokens")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    cc = u.get("cache_creation")
    if isinstance(cc, dict):
        return sum(_num(x) for x in cc.values())
    return _num(cc)


def _rate_for(model: str, rates: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """Exact registry hit, else longest prefix match (transcripts carry dated
    ids like claude-haiku-4-5-20251001 for registry key claude-haiku-4-5),
    else the pessimistic fallback. Live-fire finding 2026-07-18: without the
    prefix rule a haiku session was billed at fable rates, ~10x."""
    hit = rates.get(model)
    if hit:
        return hit
    if model:
        prefixes = [k for k in rates if model.startswith(k)]
        if prefixes:
            return rates[max(prefixes, key=len)]
    return _fallback_rate(rates)


def row_cost_usd(model: str, u: dict, rates: dict[str, tuple[float, float]]) -> float:
    inp, out = _rate_for(model, rates)
    return (
        _num(u.get("input_tokens")) * inp
        + _num(u.get("output_tokens")) * out
        + _cache_write_tokens(u) * inp * CACHE_WRITE_MULT
        + _num(u.get("cache_read_input_tokens")) * inp * CACHE_READ_MULT
    ) / 1_000_000


# ─── incremental transcript scan ─────────────────────────────────────


def _usage_of(obj: dict) -> dict | None:
    u = obj.get("usage")
    if isinstance(u, dict):
        return u
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        return msg["usage"]
    return None


def _tool_result_chars(item: dict) -> int:
    """Text length of one tool_result block's content. Fail-open: any shape
    that isn't a plain str or a list of {"type": "text", "text": str} counts
    0 — never raises."""
    content = item.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for sub in content:
            if isinstance(sub, dict) and sub.get("type") == "text" and isinstance(sub.get("text"), str):
                total += len(sub["text"])
        return total
    return 0


def _bulk_blocks_of(obj: dict) -> list[int]:
    """Proxy token sizes (chars // 4) for every tool_result block in this
    row's message.content list. [] if there is none or the shape is
    malformed — never raises."""
    try:
        msg = obj.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return []
        return [
            _tool_result_chars(item) // 4
            for item in content
            if isinstance(item, dict) and item.get("type") == "tool_result"
        ]
    except Exception:
        return []


def scan_new(transcript: Path, state: dict, rates: dict) -> None:
    """Advance state over new complete transcript lines, accumulating
    state['cost_usd']. Rows sharing a consecutive message.id are one API
    response written several times — billed once, at the max-cost row."""
    data = transcript.read_bytes()
    offset = int(state.get("offset", 0))
    if offset > len(data):  # rotated/truncated → recount
        offset = 0
        state.update(cost_usd=0.0, last_msg_id=None, last_msg_cost=0.0)
    chunk = data[offset:]
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return
    complete = chunk[: last_nl + 1]
    cost = float(state.get("cost_usd", 0.0))
    last_id = state.get("last_msg_id")
    last_cost = float(state.get("last_msg_cost", 0.0))
    bulk_tokens = int(state.get("bulk_tokens", 0))
    bulk_biggest_single = int(state.get("bulk_biggest_single", 0))
    scan_max_single = 0
    for raw in complete.splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        for size in _bulk_blocks_of(obj):  # scanned whether or not the row carries usage
            bulk_tokens += size
            if size > bulk_biggest_single:
                bulk_biggest_single = size
            if size > scan_max_single:
                scan_max_single = size
        u = _usage_of(obj)
        if u is None:
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        mid = msg.get("id")
        model = msg.get("model") or obj.get("model") or ""
        c = row_cost_usd(model, u, rates)
        if mid is not None and mid == last_id:
            if c > last_cost:  # same response, fuller usage row — bill the delta
                cost += c - last_cost
                last_cost = c
        else:
            cost += c
            last_id, last_cost = mid, c
    state.update(
        offset=offset + len(complete),
        cost_usd=cost,
        last_msg_id=last_id,
        last_msg_cost=last_cost,
        bulk_tokens=bulk_tokens,
        bulk_biggest_single=bulk_biggest_single,
        bulk_pending_single=max(int(state.get("bulk_pending_single", 0)), scan_max_single),
    )


# ─── tiers and messages ──────────────────────────────────────────────


def tier_of(cost: float, th: dict[str, float]) -> str | None:
    current = None
    for t in TIERS:
        if cost >= th[t]:
            current = t
    return current


def _gauge(cost: float, th: dict[str, float]) -> str:
    return (f"main-loop burn ≈ ${cost:.2f} "
            f"(notice ${th['NOTICE']:.0f} / warn ${th['WARN']:.0f} / "
            f"critical ${th['CRITICAL']:.0f} / hard cap ${th['HARDCAP']:.0f})")


def tier_message(tier: str, cost: float, th: dict[str, float]) -> str:
    g = _gauge(cost, th)
    if tier == "NOTICE":
        return (f"[cost-sentinel] {g}. You are past the notice line. Prefer "
                "delegating bulk reads and searches to subagents; keep "
                "main-loop context narrow (lesson 18: the driver is not "
                "exempt from lesson 7).")
    if tier == "WARN":
        return (f"[cost-sentinel] {g}. This session's context is now "
                "expensive rent. Finish the current unit of work, then write "
                "a handoff crate and continue in a fresh session instead of "
                "growing this one.")
    if tier == "CRITICAL":
        return (f"[cost-sentinel] {g}. CRITICAL: stop absorbing new bulk "
                "context in the main loop. Write the handoff crate NOW, "
                "commit it, and end the turn. Beyond the hard cap the "
                "harness will deny further tool calls.")
    return (f"[cost-sentinel] {g}. HARD CAP reached — tool calls are now "
            "denied by the harness. Summarize state for the operator and "
            "end the turn.")


def _desk_guard_messages(state: dict, bulk_th: dict[str, int]) -> list[str]:
    """PostToolUse-only. Reads and resets bulk_pending_single (every call,
    warn or not — the sidecar rule that keeps a PreToolUse/UserPromptSubmit
    scan from swallowing a pending warning). Returns 0, 1, or 2 messages."""
    msgs: list[str] = []

    pending = int(state.get("bulk_pending_single", 0))
    state["bulk_pending_single"] = 0
    single = bulk_th["SINGLE"]
    if pending > single:
        msgs.append(
            f"[desk-guard] a single tool result of ~{pending} proxy tokens "
            f"just landed in this chat context (limit {single}). Bulk "
            "belongs in a hand — delegate per docs/CRATE_OPS.md; every "
            "future turn re-pays rent on every token of it."
        )

    bulk_tokens = int(state.get("bulk_tokens", 0))
    total = bulk_th["TOTAL"]
    mult = bulk_tokens // total if total > 0 else 0
    warned_mult = int(state.get("bulk_warned_mult", 0))
    if mult > warned_mult:
        state["bulk_warned_mult"] = mult
        msgs.append(
            f"[desk-guard] cumulative tool-result bulk in this chat ≈ "
            f"{bulk_tokens} proxy tokens (crossed {mult} x {total}). Bulk "
            "belongs in a hand — delegate per docs/CRATE_OPS.md; every "
            "future turn re-pays rent on every token of it."
        )

    return msgs


def deny_reason(cost: float, th: dict[str, float], ack_path: Path) -> str:
    return (f"[cost-sentinel] {_gauge(cost, th)}. Hard cap reached: this "
            "tool call is denied by the harness (lesson 18 — run the driver "
            "as a crate visitor, not a tenant). Do not retry tool calls. "
            "Write nothing further except a final summary of state and how "
            "to resume from files. Operator: to raise this session's cap, "
            f"write a new dollar cap into {ack_path} "
            f"(e.g. `echo 400 > \"{ack_path}\"`).")


# ─── main ────────────────────────────────────────────────────────────


def _emit(payload: dict) -> None:
    print(json.dumps(payload))


def main() -> int:
    try:
        return _main()
    except Exception as e:  # noqa: BLE001 — the sentinel fails OPEN, always
        print(f"[session_sentinel] suppressed: {e!r}", file=sys.stderr)
        return 0


def _main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    sid = payload.get("session_id")
    tpath = payload.get("transcript_path")
    event = payload.get("hook_event_name", "")
    if not sid or not tpath:
        return 0
    transcript = Path(tpath).expanduser()
    if not transcript.exists():
        return 0

    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{sid}.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    scan_new(transcript, state, _load_rates())
    cost = float(state.get("cost_usd", 0.0))
    th = thresholds()

    # Operator-attested cap raise for this session (a human wrote a number).
    ack_path = state_dir / f"{sid}.ack"
    try:
        th["HARDCAP"] = max(th["HARDCAP"], float(ack_path.read_text().strip()))
    except (OSError, ValueError):
        pass

    # `tier` in state means "tier the model has been WARNED about", so only the
    # warn-emitting branches below may record it. Live-fire finding 2026-07-18:
    # PreToolUse fires between the first response and the first PostToolUse; if
    # it records the tier, PostToolUse sees crossed=False and the crossing
    # warning is swallowed forever.
    tier = tier_of(cost, th)
    prev_tier = state.get("tier")
    crossed = tier is not None and (prev_tier is None or TIERS.index(tier) > TIERS.index(prev_tier))

    if event == "PreToolUse":
        if tier == "HARDCAP":
            _emit({
                "systemMessage": f"cost-sentinel: hard cap — {_gauge(cost, th)}",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": deny_reason(cost, th, ack_path),
                },
            })
        _save(state_file, state)
        return 0

    if event == "UserPromptSubmit":
        if tier is not None:
            _emit({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": tier_message(tier, cost, th),
            }})
            state["tier"] = tier
            state["last_warned_usd"] = cost
        _save(state_file, state)
        return 0

    # PostToolUse (and any future event wired here): warn on tier crossing,
    # then on the tier's re-warn cadence. Desk-guard (bulk) messages are
    # PostToolUse-only and merge into the same single JSON emit, cost first.
    messages: list[str] = []
    system_message = None
    if tier is not None:
        step = REWARN_STEP[tier]
        due = crossed or (step > 0 and cost - float(state.get("last_warned_usd", 0.0)) >= step)
        if due:
            messages.append(tier_message(tier, cost, th))
            if crossed:
                system_message = f"cost-sentinel: {tier} — {_gauge(cost, th)}"
            state["tier"] = tier
            state["last_warned_usd"] = cost

    if event == "PostToolUse":
        messages.extend(_desk_guard_messages(state, bulk_thresholds()))

    if messages:
        out = {"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(messages),
        }}
        if system_message:
            out["systemMessage"] = system_message
        _emit(out)
    _save(state_file, state)
    return 0


def _save(state_file: Path, state: dict) -> None:
    try:
        state_file.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        print(f"[session_sentinel] state write failed: {e!r}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
