#!/usr/bin/env python3
"""
Seal the capability-harness lens registry into a living AXM Genesis shard.

The lens library is the compounding asset — every validated lens is a captured
frontier move a cheap model can run. This makes it a *sovereign, verifiable,
queryable* object instead of just a Python list:

  * every lens is a signed **claim**, bound to the exact source bytes of its
    instruction (byte-range provenance);
  * the whole registry is one BLAKE3 Merkle tree, signed axm-hybrid1
    (Ed25519 ‖ ML-DSA-44) — flip one byte and `axm-verify` fails;
  * it is queried deterministically (`axm chat query`, or the zero-dep reader
    in `capability_harness/lens_shard.py`) — the model is off the query path.

"Living": add a lens to `capability_harness/lenses_contrib.py` (validated by
`scripts/validate_lens.py`), rebuild, re-seal, re-verify. The Merkle root and
shard identity move; the lineage records the supersession.

    # build your own sovereign lens shard (mints a fresh publisher key):
    python memory/lenses/build_lens_shard.py --keygen memory/lenses/keys --out memory/lenses/shard --verify

    # or seal under an existing publisher key (kept offline / a CI secret):
    python memory/lenses/build_lens_shard.py --private-key path/to/publisher.key --out memory/lenses/shard --verify

Requires the AXM toolchain on PATH (axm-genesis): `axm-build`, `axm-verify`.
The harness itself never imports axm — only this build step does.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Read the registry straight from the harness — one source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from capability_harness.uplift import DEFAULT_LENSES          # noqa: E402
from capability_harness.lenses_contrib import CONTRIB_LENSES   # noqa: E402

NAMESPACE = "lenses/tier-bench"
TITLE = "tier-bench capability lens registry — captured frontier moves, cheap to run"
REGISTRY_ENTITY = "capability_harness/lens_registry"

# Short, honest summary of the failure class each frozen default catches. The
# lens instruction is the sealed evidence; this is the queryable object label.
CAUGHT = {
    "control_flow": "control-flow & boundary errors — off-by-one, missed first/last, wrong stop",
    "state": "state & effects — mutation, aliasing, partial updates, invariant disagreement",
    "data_types": "data & types — int/float precision, None/empty/degenerate, bad conversion/comparison",
    "contracts": "contracts & errors — missing validation, silent failure, misleading return, unguarded division",
    "adversarial": "adversarial semantics — a wrong algorithm/greedy/sort-key, exposed by a constructed counterexample",
}


def _rows():
    """(key, instruction, caught, proven_on, status, tier) for every lens."""
    for ln in DEFAULT_LENSES:
        yield (ln.key, ln.instruction, CAUGHT.get(ln.key, "operational defects"),
               "experiments/tier-uplift", "frozen-default", 3)
    for c in CONTRIB_LENSES:
        # community lens: single-source until a second contributor corroborates
        yield (c.lens.key, c.lens.instruction, c.caught, c.proven_on,
               f"community-validated (author {c.author})", 2)


def build_source(rows) -> str:
    out = [
        "# tier-bench capability lens registry — AXM Genesis sealed source",
        "#",
        "# Each lens is a generic, held-out-proven way of looking that a cheap model",
        "# can run. 'Iteration can only buy what selection can see' — the lens is the",
        "# aperture. Frozen defaults were proven blind in experiments/tier-uplift.",
        "",
    ]
    for key, instr, caught, proven, status, tier in rows:
        out += [
            f"[lens {key}] tier={tier} status={status}",
            f"catches: {caught}",
            f"proven-on: {proven}",
            f"instruction: {instr}",
            "",
        ]
    return "\n".join(out)


def build_candidates(source: str, rows) -> list[dict]:
    src_bytes = source.encode("utf-8")
    cands: list[dict] = []
    for key, instr, caught, proven, status, tier in rows:
        needle = f"instruction: {instr}".encode("utf-8")
        i = src_bytes.find(needle)
        if i < 0:
            raise SystemExit(f"evidence not found in source for lens {key!r}")
        if src_bytes.count(needle) != 1:
            raise SystemExit(f"ambiguous evidence for lens {key!r}")
        ev = {"source_file": "source.txt", "byte_start": i, "byte_end": i + len(needle),
              "text": needle.decode("utf-8")}
        subj = f"lens/{key}"
        cands.append({"type": "claim", "subject_label": subj, "predicate": "catches",
                      "object_label": caught, "object_type": "literal:string",
                      "tier": tier, "evidence": ev})
        cands.append({"type": "claim", "subject_label": subj, "predicate": "proven_on",
                      "object_label": proven, "object_type": "entity",
                      "tier": tier, "evidence": ev})
        cands.append({"type": "claim", "subject_label": REGISTRY_ENTITY, "predicate": "includes",
                      "object_label": subj, "object_type": "entity",
                      "tier": tier, "evidence": ev})
    return cands


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="memory/lenses/shard", help="shard output dir")
    ap.add_argument("--private-key", default=None, help="3904-byte axm-hybrid1 secret key (keep offline)")
    ap.add_argument("--keygen", default=None, metavar="DIR", help="mint a fresh publisher keypair in DIR and seal with it")
    ap.add_argument("--created-at", default="2026-07-07T00:00:00Z", help="RFC3339 UTC (fixed for reproducible builds)")
    ap.add_argument("--verify", action="store_true", help="run axm-verify after sealing")
    a = ap.parse_args()

    rows = list(_rows())
    source = build_source(rows)
    cands = build_candidates(source, rows)

    work = Path(a.out).resolve().parent / "_build"
    content = work / "content"
    content.mkdir(parents=True, exist_ok=True)
    (content / "source.txt").write_text(source, encoding="utf-8")
    cand_path = work / "candidates.jsonl"
    import json
    cand_path.write_text("".join(json.dumps(c) + "\n" for c in cands), encoding="utf-8")

    key = a.private_key
    if a.keygen:
        kd = Path(a.keygen); kd.mkdir(parents=True, exist_ok=True)
        pub = kd / "publisher.pub"
        if not (kd / "publisher.key").exists():
            subprocess.check_call(["axm-build", "keygen", str(kd), "--name", "publisher"])
        key = str(kd / "publisher.key")
        print(f"  publisher key: {key} (KEEP OFFLINE)  public: {pub}")
    if not key:
        raise SystemExit("need --private-key PATH or --keygen DIR")

    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"  sealing {len(rows)} lenses -> {out}")
    subprocess.check_call([
        "axm-build", "compile", str(cand_path), str(content), str(out),
        "--private-key", key, "--namespace", NAMESPACE, "--title", TITLE,
        "--created-at", a.created_at, "--license-spdx", "MIT",
    ])

    if a.verify:
        pub = (Path(a.keygen) / "publisher.pub") if a.keygen else (out / "sig" / "publisher.pub")
        print("  verifying...")
        subprocess.check_call(["axm-verify", "shard", str(out), "--trusted-key", str(pub)])
    print(f"  done. {len(rows)} lenses sealed. query: axm chat query \"...\"  |  load: capability_harness/lens_shard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
