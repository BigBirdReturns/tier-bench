#!/usr/bin/env python3
"""Build deterministic, self-contained ARC-D exploratory subject prompts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data" / "oss-replay" / "arc_d_buffalo_pilot_v1"
ITEMS = PILOT / "items"
SOURCE_THREAD_ID = "019f4fdc-f3f9-7b52-87f3-3452d231d67e"
PREAMBLE = """You are a cold OSS diagnostic subject. This packet is complete.
Do not browse, call tools, inspect a repository, or assume unseen files. Analyze only
the public problem report and pinned source excerpt below. Do not claim that you ran
tests. This is an exploratory observation, not a benchmark or an upstream verdict.

Return exactly these five Markdown sections:

1. `## Diagnosis` — the concrete execution path and root cause, including uncertainty.
2. `## Minimal change design` — the smallest coherent change surface and its invariants.
3. `## Regression matrix` — tests, inputs, and expected results, including boundaries.
4. `## Candidate residue` — one falsifiable reusable rule plus its applicability limit.
5. `## Confidence and disconfirmation` — confidence from 0 to 1 and evidence that would
   disprove or materially change the answer.
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_item(item_dir: Path) -> dict[str, object]:
    problem = (item_dir / "packet" / "problem.md").read_text(encoding="utf-8")
    source = (item_dir / "packet" / "source_excerpt.py").read_text(encoding="utf-8")
    prompt = (
        PREAMBLE
        + "\n## Public problem report\n\n"
        + problem.rstrip()
        + "\n\n## Pinned source excerpt\n\n```python\n"
        + source.rstrip()
        + "\n```\n"
    )
    prompt_bytes = prompt.encode("utf-8")
    prompt_path = item_dir / "packet" / "PROMPT.md"
    prompt_path.write_bytes(prompt_bytes)
    transported_prompt = html.escape(prompt, quote=False)
    envelope = (
        "<codex_delegation>\n"
        f"  <source_thread_id>{SOURCE_THREAD_ID}</source_thread_id>\n"
        f"  <input>{transported_prompt}</input>\n"
        "</codex_delegation>"
    )
    envelope_bytes = envelope.encode("utf-8")
    (item_dir / "packet" / "delivered_envelope.txt").write_bytes(envelope_bytes)
    receipt = {
        "schema": "tier-bench/arc-d-packet-build@1",
        "item_id": item_dir.name,
        "builder": "scripts/build_buffalo_packets.py",
        "problem_sha256": sha256(problem.encode("utf-8")),
        "source_excerpt_sha256": sha256(source.encode("utf-8")),
        "prompt_sha256": sha256(prompt_bytes),
        "prompt_bytes": len(prompt_bytes),
        "delivered_envelope_sha256": sha256(envelope_bytes),
        "delivered_envelope_bytes": len(envelope_bytes),
        "source_thread_id": SOURCE_THREAD_ID,
        "transport_transform": "html.escape(prompt, quote=False)",
        "line_endings": "LF",
    }
    receipt_path = item_dir / "packet" / "build_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    item_dirs = sorted(path for path in ITEMS.iterdir() if path.is_dir())
    before = {
        path.name: (path / "packet" / "PROMPT.md").read_bytes()
        if (path / "packet" / "PROMPT.md").exists()
        else None
        for path in item_dirs
    }
    receipts = [build_item(path) for path in item_dirs]
    if args.check:
        changed = [
            path.name
            for path in item_dirs
            if before[path.name] != (path / "packet" / "PROMPT.md").read_bytes()
        ]
        if changed:
            raise SystemExit(f"packet drift: {', '.join(changed)}")
    print(json.dumps(receipts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
