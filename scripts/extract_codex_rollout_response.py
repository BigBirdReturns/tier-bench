#!/usr/bin/env python3
"""Extract a response and a safe, hash-bound snapshot from a Codex rollout."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def message_text(payload: dict) -> str:
    return "".join(
        item.get("text", "")
        for item in payload.get("content", [])
        if item.get("type") in {"input_text", "output_text"}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--expected-thread-id", required=True)
    parser.add_argument("--response-out", type=Path, required=True)
    parser.add_argument("--events-out", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()

    raw = args.rollout.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line]
    session = next(row["payload"] for row in rows if row.get("type") == "session_meta")
    if session.get("id") != args.expected_thread_id:
        raise ValueError("rollout session ID does not match expected thread")

    context = next(row["payload"] for row in rows if row.get("type") == "turn_context")
    if context.get("model") != "gpt-5.6-sol" or context.get("effort") != "low":
        raise ValueError("subject did not run at the registered model/effort floor")

    messages = [
        row["payload"]
        for row in rows
        if row.get("type") == "response_item"
        and row.get("payload", {}).get("type") == "message"
    ]
    prompt_bytes = args.prompt.read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    delivered = [
        message_text(item)
        for item in messages
        if item.get("role") == "user" and "<codex_delegation>" in message_text(item)
    ]
    finals = [
        message_text(item)
        for item in messages
        if item.get("role") == "assistant" and item.get("phase") == "final_answer"
    ]
    if len(delivered) != 1 or len(finals) != 1:
        raise ValueError("rollout must contain exactly one packet prompt and final answer")
    match = re.search(r"<input>(.*)</input>", delivered[0], flags=re.DOTALL)
    if not match or html.unescape(match.group(1)) != prompt:
        raise ValueError("transported delegation input does not match packet prompt bytes")
    response = finals[0]

    task_started = next(
        row for row in rows
        if row.get("type") == "event_msg"
        and row.get("payload", {}).get("type") == "task_started"
    )
    task_complete = next(
        row for row in rows
        if row.get("type") == "event_msg"
        and row.get("payload", {}).get("type") == "task_complete"
    )
    if task_complete["payload"].get("last_agent_message") != response:
        raise ValueError("task completion receipt does not match final response")

    tool_calls = [
        row for row in rows
        if row.get("type") == "response_item"
        and row.get("payload", {}).get("type") in {"custom_tool_call", "function_call"}
    ]
    if tool_calls:
        raise ValueError("packet-only subject used a tool")

    token_rows = [
        row for row in rows
        if row.get("type") == "event_msg"
        and row.get("payload", {}).get("type") == "token_count"
        and isinstance(
            row.get("payload", {}).get("info", {}).get("total_token_usage"), dict
        )
    ]
    usage = (
        token_rows[-1]["payload"]["info"]["total_token_usage"]
        if token_rows else {}
    )

    # The provider rollout contains host-injected policy and workstation
    # context that is neither solver evidence nor safe to publish. Preserve it
    # locally, bind its exact bytes in the administration receipt, and emit the
    # minimum event snapshot needed to reproduce identity, timing, usage, and
    # response custody.
    capture_kind = "coordinator-derived-codex-app-thread-snapshot"
    source_rollout_sha256 = sha256(raw)
    response_bytes = response.encode("utf-8")
    response_sha256 = sha256(response_bytes)
    turn_id = task_started["payload"].get("turn_id")
    snapshot = [
        {
            "type": "thread.started",
            "thread_id": session["id"],
            "timestamp": session.get("timestamp") or rows[0].get("timestamp"),
            "model": context["model"],
            "effort": context["effort"],
            "capture_kind": capture_kind,
            "source_rollout_sha256": source_rollout_sha256,
        },
        {
            "type": "turn.started",
            "turn_id": turn_id,
            "timestamp": task_started.get("timestamp"),
            "capture_kind": capture_kind,
        },
        {
            "type": "turn.completed",
            "turn_id": turn_id,
            "timestamp": task_complete.get("timestamp"),
            "duration_ms": task_complete["payload"].get("duration_ms"),
            "usage": usage,
            "response_sha256": response_sha256,
            "source_rollout_sha256": source_rollout_sha256,
            "capture_kind": capture_kind,
        },
    ]
    snapshot_bytes = b"".join(
        (json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        for row in snapshot
    )

    args.response_out.parent.mkdir(parents=True, exist_ok=True)
    args.events_out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.response_out.write_bytes(response_bytes)
    args.events_out.write_bytes(snapshot_bytes)
    receipt = {
        "schema": "tier-bench/codex-packet-subject-extraction@2",
        "thread_id": session["id"],
        "turn_id": task_started["payload"].get("turn_id"),
        "model": context["model"],
        "effort": context["effort"],
        "prompt_sha256": sha256(prompt_bytes),
        "delivered_envelope_sha256": sha256(delivered[0].encode("utf-8")),
        "response_sha256": response_sha256,
        "event_snapshot_sha256": sha256(snapshot_bytes),
        "event_stream_capture_kind": capture_kind,
        "source_rollout_sha256": source_rollout_sha256,
        "task_started_timestamp": task_started["timestamp"],
        "task_completed_timestamp": task_complete["timestamp"],
        "duration_ms": task_complete["payload"].get("duration_ms"),
        "usage": usage,
        "tool_calls": 0,
    }
    args.receipt_out.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
