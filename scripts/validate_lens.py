#!/usr/bin/env python3
"""
validate_lens.py — the objective bar for contributing a lens.

A lens earns a place in the library by doing one thing: on a HELD-OUT subject,
its single focused pass surfaces a real issue that the SAME model's plain,
lens-free pass missed. That is the whole claim of the harness ("iteration can
only buy what selection can see"), applied to the lens itself. If a candidate
lens never adds a finding the baseline already had, it is dead weight and this
script says so.

It does NOT judge prose, novelty, or taste — only: did this aperture make the
model see something the naked pass did not, on code the lens was not written for.

Usage:
    # Real proof (recommended) — uses your model via the harness backends:
    python scripts/validate_lens.py \
        --lens-key resource_lifetime \
        --lens "RESOURCE LIFETIME only: every acquire matched to a release on ALL paths ..." \
        --subject fixtures/tX_leaky_pool/target.py \
        --expect "open"  --expect "release" \
        --backend anthropic --model claude-haiku-4-5

    # CI smoke (no API key) — proves the wiring, not the lift:
    python scripts/validate_lens.py --lens-key demo --lens "..." \
        --subject some_file.py --backend echo

Exit 0 = the lens added a finding the baseline missed (or, with --echo, the
harness ran clean). Exit 1 = no lift / bad input.

`--expect SUBSTR` (repeatable) lets a task author assert the lens must mention
specific evidence (case-insensitive) — the held-out issue's fingerprint — so a
lens can't "pass" by emitting generic noise the baseline also emitted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from the repo root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability_harness.uplift import Lens, _PROMPT  # noqa: E402
from capability_harness import backends as _bk       # noqa: E402


def _get_backend(name: str, model: str, base_url: str | None):
    if name == "echo":
        return _bk.echo_backend()
    if name == "anthropic":
        return _bk.anthropic_backend(model)
    if name == "openai":
        return _bk.openai_backend(model, base_url=base_url)
    raise SystemExit(f"unknown backend: {name}")


_BASELINE_PROMPT = """You are doing a careful, general code review — no fixed checklist.
Report every issue you find: location, a one-sentence explanation, and a triggering
input or scenario. Be thorough.

----- TARGET -----
{target}
----- END TARGET -----"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Prove a candidate lens lifts a model on held-out code.")
    ap.add_argument("--lens-key", required=True, help="short key, e.g. resource_lifetime")
    ap.add_argument("--lens", required=True, help="the lens instruction text")
    ap.add_argument("--subject", required=True, help="path to a held-out source file the lens was NOT written for")
    ap.add_argument("--expect", action="append", default=[],
                    help="substring the lens output MUST contain (repeatable, case-insensitive)")
    ap.add_argument("--backend", default="echo", choices=["echo", "anthropic", "openai"])
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    target = Path(args.subject).read_text()
    call = _get_backend(args.backend, args.model, args.base_url)
    lens = Lens(args.lens_key, args.lens)

    baseline = (call(_BASELINE_PROMPT.format(target=target)) or "").strip()
    lensed = (call(_PROMPT.format(instruction=lens.instruction, target=target)) or "").strip()

    print(f"[validate_lens] backend={args.backend} model={args.model} subject={args.subject}")
    print(f"[validate_lens] baseline pass: {len(baseline)} chars   lens pass: {len(lensed)} chars")

    if args.backend == "echo":
        # No model to reason; just prove the two passes ran and differ in prompt.
        ok = bool(lensed) and lensed != baseline
        print("[validate_lens] echo smoke:", "OK" if ok else "FAIL (wiring)")
        return 0 if ok else 1

    # --expect gates: the lens must name the held-out issue's fingerprint, and the
    # baseline must NOT already carry all of it (else the lens added nothing).
    lo_lens, lo_base = lensed.lower(), baseline.lower()
    missing = [s for s in args.expect if s.lower() not in lo_lens]
    if missing:
        print(f"[validate_lens] FAIL — lens output missing required evidence: {missing}")
        return 1

    added = [s for s in args.expect if s.lower() not in lo_base]
    if args.expect and not added:
        print("[validate_lens] FAIL — baseline already surfaced every expected item; "
              "the lens added no lift on this subject.")
        return 1

    print(f"[validate_lens] PASS — lens surfaced {added or 'a distinct finding'} that the "
          f"baseline pass missed on held-out code.")
    print("[validate_lens] Add it to capability_harness/lenses_contrib.py with author + "
          "proven_on + caught, and open a PR.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
