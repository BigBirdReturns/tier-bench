#!/usr/bin/env python3
"""
Seal a tier-bench session's decisions into verifiable memory.

This is the industrial version of driver/policy/: instead of an ad-hoc JSON
snapshot, a session's decisions become a cryptographically signed, byte-traceable
decision shard you can query deterministically and verify offline forever. See
memory/README.md for why (horizon = memory) and the proof it holds.

The loop (each step is one axm-chat command; this just orchestrates them):

    convert   transcript .jsonl -> export.json        (stdlib, memory/transcript_to_export.py)
    import    export.json       -> conversation shard (axm-chat import)
    distill   conversation shard -> decision shard    (axm-chat distill — needs a Tier-3 model)
    verify    decision shard     -> PASS/FAIL         (axm-chat verify — Merkle + PQ signature)

Requires the AXM toolchain on PATH (axm-genesis + axm-core + axm-chat):
    pip install -e axm-genesis -e axm-core -e axm-chat   # sibling checkouts
    pip install dilithium-py                              # ML-DSA-44 backend
Distillation additionally needs a local Tier-3 model (Ollama: `ollama pull mistral`).
Without one, import + verify still run; distill is where the model reads the
conversation and extracts decisions.

    python memory/seal_session.py ~/.claude/projects/<slug>/<uuid>.jsonl
    python memory/seal_session.py SESSION.jsonl --model mistral --no-distill
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcript_to_export import extract_utterances, to_export  # noqa: E402
import json  # noqa: E402


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(argv: list[str]) -> int:
    print(f"  $ {' '.join(argv)}")
    return subprocess.call(argv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", help="Claude Code session .jsonl")
    ap.add_argument("--name", default=None)
    ap.add_argument("--model", default="mistral", help="Tier-3 model for distill (Ollama)")
    ap.add_argument("--no-distill", action="store_true", help="import + verify only")
    ap.add_argument("--out-dir", default=None, help="where to write the export.json")
    a = ap.parse_args()

    if not _have("axm-chat"):
        sys.exit("axm-chat not on PATH — install the AXM toolchain (see this file's docstring).")

    utt = extract_utterances(a.transcript)
    if not utt:
        sys.exit("no utterances extracted — is this a Claude Code transcript?")
    stem = Path(a.transcript).stem
    export = to_export(utt, a.name or f"tier-bench session {stem}", f"claude-code-session-{stem}")
    out_dir = Path(a.out_dir) if a.out_dir else Path.cwd()
    export_path = out_dir / f"{stem}.export.json"
    export_path.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    print(f"convert: {len(utt)} utterances -> {export_path}")

    print("import:")
    if _run(["axm-chat", "import", str(export_path)]) != 0:
        sys.exit("import failed")

    if not a.no_distill:
        print(f"distill (Tier-3 model = {a.model}):")
        rc = _run(["axm-chat", "distill", "--model", a.model])
        if rc != 0:
            print("  distill did not complete — a local Tier-3 model (Ollama) is required.")
            print("  import + verify still stand; run distill later once a model is available.")

    print("verify:")
    _run(["axm-chat", "verify"])
    print("\nquery it:  axm-chat query \"what was rejected\"")


if __name__ == "__main__":
    main()
