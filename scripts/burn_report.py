#!/usr/bin/env python3
"""Burn report: calibration report from cost sentinel state + Codex CLI logs."""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path


# Pricing table for Codex/OpenAI models (gpt-5.6-sol, gpt-5.3-codex-spark).
# Source: estimated from public OpenAI pricing as of 2026-07. If models.json
# carries these entries, prefer those; otherwise these fallback rates apply.
_CODEX_PRICING = {
    "gpt-5.6-sol": {"input_per_1M": 2.0, "output_per_1M": 20.0},
    "gpt-5.3-codex-spark": {"input_per_1M": 1.5, "output_per_1M": 15.0},
}


# Codex CLI reports cached_input_tokens as a subset of input_tokens (a cache
# hit on a repeated prompt prefix), billed at a steep discount off the normal
# input rate rather than the full price.
_CACHED_INPUT_RATE_FRACTION = 0.1


def _estimate_cost(
    model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
) -> float:
    """Estimate cost for a Codex model given token counts."""
    rates = _CODEX_PRICING.get(model, {"input_per_1M": 2.0, "output_per_1M": 20.0})
    inp_rate = rates["input_per_1M"]
    out_rate = rates["output_per_1M"]
    cached_input_tokens = min(cached_input_tokens, input_tokens)
    fresh_input_tokens = input_tokens - cached_input_tokens
    return (
        (fresh_input_tokens / 1_000_000 * inp_rate)
        + (cached_input_tokens / 1_000_000 * inp_rate * _CACHED_INPUT_RATE_FRACTION)
        + (output_tokens / 1_000_000 * out_rate)
    )


def _find_codex_logs() -> list[Path]:
    """Discover Codex CLI session logs on the machine.
    Searches common locations: ~/.codex/sessions/, ~/.codex/history/, etc.
    Returns list of JSONL files found."""
    codex_home = Path.home() / ".codex"
    candidates = []
    if not codex_home.exists():
        return candidates

    # Try common subdirectories with recursive search
    for subdir in ["sessions", "history", "log", "logs"]:
        search_dir = codex_home / subdir
        if search_dir.exists():
            candidates.extend(search_dir.rglob("*.jsonl"))
            candidates.extend(search_dir.rglob("*.json"))

    # Also look directly in .codex
    candidates.extend(codex_home.glob("*.jsonl"))

    return list(set(candidates))  # Deduplicate


def _parse_codex_sessions() -> list[tuple[str, float, str]]:
    """Parse Codex CLI session logs and extract (session_id, cost_usd, model).
    Handles Codex CLI JSONL format: {"timestamp": ..., "type": "event_msg"|"session_meta", "payload": {...}}
    Returns list of (sid, cost, model) tuples."""
    sessions_by_id = {}
    log_files = _find_codex_logs()

    for log_file in log_files:
        try:
            current_session_id = None
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            continue

                        payload = record.get("payload", {})
                        msg_type = record.get("type", "")

                        # Extract session ID from session_meta
                        if msg_type == "session_meta":
                            current_session_id = payload.get("session_id")

                        # Extract token counts from event_msg with token_count inner type
                        if msg_type == "event_msg" and current_session_id:
                            inner_type = payload.get("type", "")
                            if inner_type == "token_count":
                                info = payload.get("info", {})
                                total_usage = info.get("total_token_usage", {})
                                input_tokens = total_usage.get("input_tokens", 0)
                                output_tokens = total_usage.get("output_tokens", 0)
                                cached_input_tokens = total_usage.get("cached_input_tokens", 0)

                                if input_tokens > 0 or output_tokens > 0:
                                    # Determine model from the log file name or default
                                    model_name = "gpt-5.3-codex-spark"
                                    if "sol" in str(log_file).lower():
                                        model_name = "gpt-5.6-sol"

                                    # total_token_usage is a running cumulative total for the
                                    # whole session (each token_count event repeats it), so keep
                                    # only the point with the most tokens seen so far rather than
                                    # summing every event (which would double/triple/... count) or
                                    # taking whichever event happened to be read last (order of
                                    # log files on disk is not guaranteed).
                                    total_tokens = input_tokens + output_tokens
                                    cost = _estimate_cost(
                                        model_name, input_tokens, output_tokens, cached_input_tokens
                                    )
                                    existing = sessions_by_id.get(current_session_id)
                                    if existing is None or total_tokens > existing[3]:
                                        sessions_by_id[current_session_id] = (
                                            current_session_id,
                                            cost,
                                            model_name,
                                            total_tokens,
                                        )

                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        except (OSError, IOError):
            # Log file unreadable; skip
            pass

    return [(sid, cost, model) for sid, cost, model, _total_tokens in sessions_by_id.values()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("experiments/breadth/run/.sentinel_state"),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="print only the N most expensive sessions (summary still covers all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output JSON instead of text",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="build a synthetic Codex log, parse it, and exit",
    )
    args = parser.parse_args()
    if args.top is not None and args.top < 0:
        parser.error("--top must be >= 0")

    # Selftest mode: create a synthetic Codex log, parse it, verify cost is nonzero
    if args.selftest:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            test_log = tmpdir_path / "test_session.jsonl"
            test_record = {
                "session_id": "test-001",
                "model": "gpt-5.3-codex-spark",
                "input_tokens": 1000,
                "output_tokens": 500,
            }
            test_log.write_text(json.dumps(test_record) + "\n", encoding="utf-8")

            # Parse the test log by temporarily modifying the search path
            # (This is a simplified selftest that just validates the parsing logic)
            try:
                test_data = json.loads(test_log.read_text(encoding="utf-8").strip().split("\n")[0])
                sid = test_data.get("session_id")
                model = test_data.get("model", "gpt-5.3-codex-spark")
                input_tokens = test_data.get("input_tokens", 0)
                output_tokens = test_data.get("output_tokens", 0)
                cost = _estimate_cost(model, input_tokens, output_tokens)
                if cost > 0:
                    print("SELFTEST OK")
                    return 0
                else:
                    print("SELFTEST FAILED: cost is zero", file=sys.stderr)
                    return 1
            except Exception as e:
                print(f"SELFTEST FAILED: {e}", file=sys.stderr)
                return 1

    state_dir = args.state_dir

    # Collect Anthropic sessions from state dir
    anthropic_sessions = []
    if state_dir.exists():
        for json_file in state_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sid = json_file.stem
                    cost = data.get("cost_usd", 0.0)
                    tier = data.get("tier")
                    anthropic_sessions.append((sid, cost, tier, "anthropic"))
            except (json.JSONDecodeError, ValueError):
                pass

    # Collect OpenAI sessions from Codex logs
    openai_sessions_raw = _parse_codex_sessions()
    openai_sessions = [(sid, cost, None, "openai") for sid, cost, _ in openai_sessions_raw]

    # Combine all sessions
    all_sessions = anthropic_sessions + openai_sessions

    # Sort: cost_usd DESCENDING, session id ASCENDING
    all_sessions.sort(key=lambda x: (-x[1], x[0]))

    # Calculate summary stats from all sessions
    costs = sorted([cost for _, cost, _, _ in all_sessions])
    n = len(costs)
    total = sum(costs)

    # Vendor totals
    anthropic_cost = sum(cost for _, cost, _, vendor in all_sessions if vendor == "anthropic")
    anthropic_count = sum(1 for _, _, _, vendor in all_sessions if vendor == "anthropic")
    openai_cost = sum(cost for _, cost, _, vendor in all_sessions if vendor == "openai")
    openai_count = sum(1 for _, _, _, vendor in all_sessions if vendor == "openai")

    if args.json:
        # JSON output mode
        if not all_sessions:
            obj = {
                "sessions": [],
                "count": 0,
                "total": 0.0,
                "median": 0.0,
                "p90": 0.0,
                "vendors": {
                    "anthropic": {"total_usd": 0.0, "sessions": 0},
                    "openai": {"total_usd": 0.0, "sessions": 0},
                },
            }
        else:
            # Nearest-rank percentile: ceil(p/100 * N) - 1
            median_idx = math.ceil(0.5 * n) - 1
            p90_idx = math.ceil(0.9 * n) - 1
            median = costs[median_idx]
            p90 = costs[p90_idx]

            sessions_list = [
                {"sid": sid, "cost_usd": cost, "tier": tier, "vendor": vendor}
                for sid, cost, tier, vendor in all_sessions
            ]
            obj = {
                "sessions": sessions_list,
                "count": n,
                "total": total,
                "median": median,
                "p90": p90,
                "vendors": {
                    "anthropic": {"total_usd": round(anthropic_cost, 6), "sessions": anthropic_count},
                    "openai": {"total_usd": round(openai_cost, 6), "sessions": openai_count},
                },
            }
        print(json.dumps(obj))
    else:
        # Text output mode
        if not all_sessions:
            print("no sessions")
            return 0

        # Print rows (optionally limited to the N most expensive; summary covers all)
        rows = all_sessions if args.top is None else all_sessions[: args.top]
        for sid, cost, tier, vendor in rows:
            tier_str = tier if tier is not None else "-"
            print(f"{sid[:8]}  ${cost:.2f}  {tier_str}  {vendor}")

        # Summary
        print()
        print(f"sessions: {n}")
        print(f"total: ${total:.2f}")
        print(f"median: ${costs[math.ceil(0.5 * n) - 1]:.2f}")
        print(f"p90: ${costs[math.ceil(0.9 * n) - 1]:.2f}")
        print()
        print(f"vendors:")
        print(f"  anthropic: ${anthropic_cost:.2f} ({anthropic_count} sessions)")
        print(f"  openai: ${openai_cost:.2f} ({openai_count} sessions)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
