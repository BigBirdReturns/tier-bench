#!/usr/bin/env python3
"""Run one exported hidden-free solver packet through local Ollama."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import uuid
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--raw-response", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--administration-receipt", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:11434/api/generate")
    args = parser.parse_args()

    prompt_path = args.solver / "PROMPT.md"
    packet_path = args.solver / "PACKET.json"
    if not prompt_path.is_file() or not packet_path.is_file():
        raise FileNotFoundError("solver packet must contain PROMPT.md and PACKET.json")
    for destination in (args.raw_response, args.events, args.administration_receipt):
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)

    prompt = prompt_path.read_text(encoding="utf-8")
    request_id = str(uuid.uuid4())
    payload = {
        "model": args.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": args.temperature,
            "seed": args.seed,
        },
    }
    request = urllib.request.Request(
        args.url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        native = json.loads(response.read().decode("utf-8"))
    if native.get("done") is not True or not isinstance(native.get("response"), str):
        raise ValueError("Ollama response was incomplete")

    args.raw_response.write_text(native["response"], encoding="utf-8")
    thinking = native.get("thinking") if isinstance(native.get("thinking"), str) else ""
    event = {
        "type": "ollama.completed",
        "capture_kind": "ollama-local-api-receipt-jsonl",
        "request_id": request_id,
        "model": native.get("model"),
        "created_at": native.get("created_at"),
        "done": native.get("done"),
        "done_reason": native.get("done_reason"),
        "options": payload["options"],
        "usage": {
            "input_tokens": int(native.get("prompt_eval_count", 0) or 0),
            "output_tokens": int(native.get("eval_count", 0) or 0),
        },
        "durations_ns": {
            key: int(native.get(key, 0) or 0)
            for key in (
                "total_duration", "load_duration", "prompt_eval_duration",
                "eval_duration",
            )
        },
        "response_sha256": sha256(args.raw_response),
        "response_characters": len(native["response"]),
        "thinking_characters": len(thinking),
        "thinking_sha256": hashlib.sha256(thinking.encode("utf-8")).hexdigest(),
    }
    args.events.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "thread_id": request_id,
        "prompt_sha256": sha256(prompt_path),
        "response_sha256": sha256(args.raw_response),
        "event_snapshot_sha256": sha256(args.events),
        "event_stream_capture_kind": "ollama-local-api-receipt-jsonl",
        "tool_calls": 0,
        "transport": "ollama-loopback",
        "url": args.url,
        "model": args.model,
        "temperature": args.temperature,
        "seed": args.seed,
        "response_characters": len(native["response"]),
        "thinking_characters": len(thinking),
        "thinking_sha256": hashlib.sha256(thinking.encode("utf-8")).hexdigest(),
    }
    args.administration_receipt.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
