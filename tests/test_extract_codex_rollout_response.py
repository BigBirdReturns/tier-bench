#!/usr/bin/env python3
"""The Codex rollout extractor preserves custody without publishing host context."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


REPO = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_safe_snapshot_binds_complete_rollout_and_exact_response():
    root = REPO / ".test-tmp" / f"extract-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    try:
        prompt = root / "PROMPT.md"
        rollout = root / "rollout.jsonl"
        response = root / "raw_response.txt"
        events = root / "events.jsonl"
        receipt = root / "administration_receipt.json"
        prompt.write_text("solve this exactly\n", encoding="utf-8", newline="\n")
        envelope = (
            "<codex_delegation><input>"
            + html.escape(prompt.read_text(encoding="utf-8"))
            + "</input></codex_delegation>"
        )
        rows = [
            {"timestamp": "2026-07-12T00:00:00Z", "type": "session_meta",
             "payload": {"id": "thread-test", "host_secret": "DO_NOT_PUBLISH"}},
            {"timestamp": "2026-07-12T00:00:01Z", "type": "event_msg",
             "payload": {"type": "task_started", "turn_id": "turn-test"}},
            {"timestamp": "2026-07-12T00:00:01Z", "type": "turn_context",
             "payload": {"model": "gpt-5.6-sol", "effort": "low"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": envelope}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
             "phase": "final_answer", "content": [{"type": "output_text", "text": "answer\n"}]}},
            {"timestamp": "2026-07-12T00:00:02Z", "type": "event_msg",
             "payload": {"type": "token_count", "info": {"total_token_usage": {
                 "input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3,
                 "reasoning_output_tokens": 1, "total_tokens": 13}}}},
            {"timestamp": "2026-07-12T00:00:03Z", "type": "event_msg",
             "payload": {"type": "task_complete", "turn_id": "turn-test",
                         "duration_ms": 2000, "last_agent_message": "answer\n"}},
        ]
        rollout.write_text("".join(json.dumps(row) + "\n" for row in rows),
                           encoding="utf-8", newline="\n")
        source_hash = _sha256(rollout)
        subprocess.run([
            sys.executable, str(REPO / "scripts/extract_codex_rollout_response.py"),
            "--rollout", str(rollout), "--prompt", str(prompt),
            "--expected-thread-id", "thread-test", "--response-out", str(response),
            "--events-out", str(events), "--receipt-out", str(receipt),
        ], check=True, capture_output=True, text=True)

        assert response.read_bytes() == b"answer\n"
        assert b"DO_NOT_PUBLISH" not in events.read_bytes()
        admin = json.loads(receipt.read_text(encoding="utf-8"))
        assert admin["source_rollout_sha256"] == source_hash
        assert admin["event_snapshot_sha256"] == _sha256(events)
        assert admin["response_sha256"] == _sha256(response)
        assert admin["tool_calls"] == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    test_safe_snapshot_binds_complete_rollout_and_exact_response()
    print("1/1 passed")
