#!/usr/bin/env python3
"""Validate the AXM primitive registry against its source ledger.

This is the anti-vibes gate. AXM coins vocabulary fast — black-letter AXM,
waterline, capture ledger, proof knot, terrain-divergence knot — and the danger
is that persuasive prose becomes "fact" by repetition. This validator refuses to
let a primitive exist without a source trail.

It enforces, in code (no third-party deps — the repo doctrine is stdlib-only),
exactly what schemas/primitive.schema.json and schemas/source_ledger.schema.json
declare, PLUS three cross-cutting rules a plain schema check can't express:

  1. Referential integrity — every source_basis.source_id must resolve to an
     entry in the source ledger. A primitive that cites a source that isn't in
     the ledger is exactly "metaphor without a source trail".
  2. Anti-laundering — a source of kind 'model_synthesis' MUST name its author
     model. Model-authored material is compile-time input, never runtime
     authority (AXM Genesis paper, section 8.3). This is how "spectra" (gpt-4o)
     and the provenance ledger itself (gpt-5.5-high) get recorded honestly.
  3. Analogy discipline — a source_basis entry with support_type 'analogy' is
     a non-literal mapping; the primitive must carry at least one not_source_claim
     so the metaphor can't be read as a guarantee.

Exit 0 and print a summary if everything holds; exit 1 and print every failure
otherwise. CI runs it with no arguments against the committed registry.

    python scripts/validate_primitives.py
    python scripts/validate_primitives.py --primitives <f.json> --sources <f.json>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PRIMITIVES = REPO / "data/primitives/axm_primitives.v0.1.json"
DEFAULT_SOURCES = REPO / "data/sources/source_ledger.v0.1.json"

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

STATUSES = {"settled", "derived", "synthesis"}
SUPPORT_TYPES = {"direct_fact", "baseline", "repo_evidence", "external_evidence", "analogy"}
SOURCE_KINDS = {"legal", "standard", "academic", "repo_artifact", "external_doc", "model_synthesis", "dataset"}
BASIS_CLASSES = {"primary", "secondary", "baseline", "synthesis"}

PRIMITIVE_REQUIRED = ("primitive_id", "name", "status", "source_basis",
                      "derived_claim", "not_source_claim", "verifier", "failure_mode")
SOURCE_REQUIRED = ("source_id", "title", "kind", "locator", "retrieved", "basis_class")


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_source(src: dict) -> list[str]:
    """Return a list of human-readable errors for one source entry ([] if valid)."""
    errs: list[str] = []
    sid = src.get("source_id", "<no id>")
    for key in SOURCE_REQUIRED:
        if key not in src:
            errs.append(f"source {sid}: missing required field '{key}'")
    if "source_id" in src and not ID_RE.match(str(src["source_id"])):
        errs.append(f"source {sid}: source_id must be snake_case")
    kind = src.get("kind")
    if kind is not None and kind not in SOURCE_KINDS:
        errs.append(f"source {sid}: invalid kind '{kind}' (allowed: {sorted(SOURCE_KINDS)})")
    if src.get("basis_class") is not None and src["basis_class"] not in BASIS_CLASSES:
        errs.append(f"source {sid}: invalid basis_class '{src['basis_class']}'")
    # Anti-laundering: model_synthesis must name its author model.
    if kind == "model_synthesis" and not _nonempty_str(src.get("author")):
        errs.append(f"source {sid}: kind 'model_synthesis' requires a non-empty 'author' "
                    f"(the model that authored it) — model output is not anonymous authority")
    return errs


def validate_primitive(prim: dict, source_ids: set[str]) -> list[str]:
    """Return a list of human-readable errors for one primitive ([] if valid).

    source_ids is the set of ids defined in the source ledger; source_basis
    entries are checked for referential integrity against it.
    """
    errs: list[str] = []
    pid = prim.get("primitive_id", "<no id>")
    for key in PRIMITIVE_REQUIRED:
        if key not in prim:
            errs.append(f"primitive {pid}: missing required field '{key}'")
    if "primitive_id" in prim and not ID_RE.match(str(prim["primitive_id"])):
        errs.append(f"primitive {pid}: primitive_id must be snake_case")
    if prim.get("status") is not None and prim["status"] not in STATUSES:
        errs.append(f"primitive {pid}: invalid status '{prim['status']}' (allowed: {sorted(STATUSES)})")

    basis = prim.get("source_basis")
    if not isinstance(basis, list) or len(basis) == 0:
        errs.append(f"primitive {pid}: source_basis must be a non-empty list "
                    f"— a primitive with no source is exactly what this layer rejects")
        basis = []
    has_analogy = False
    for i, b in enumerate(basis):
        where = f"primitive {pid}: source_basis[{i}]"
        if not isinstance(b, dict):
            errs.append(f"{where}: must be an object")
            continue
        for key in ("source_id", "support_type", "supports"):
            if key not in b:
                errs.append(f"{where}: missing '{key}'")
        st = b.get("support_type")
        if st is not None and st not in SUPPORT_TYPES:
            errs.append(f"{where}: invalid support_type '{st}' (allowed: {sorted(SUPPORT_TYPES)})")
        if st == "analogy":
            has_analogy = True
        if not _nonempty_str(b.get("supports")):
            errs.append(f"{where}: 'supports' must be a non-empty string")
        ref = b.get("source_id")
        if ref is not None and ref not in source_ids:
            errs.append(f"{where}: source_id '{ref}' does not resolve to any entry in the "
                        f"source ledger (unsourced primitive)")

    nsc = prim.get("not_source_claim")
    if not isinstance(nsc, list) or len(nsc) == 0:
        errs.append(f"primitive {pid}: not_source_claim must be a non-empty list of guards")
    elif not all(_nonempty_str(x) for x in nsc):
        errs.append(f"primitive {pid}: every not_source_claim must be a non-empty string")
    if has_analogy and (not isinstance(nsc, list) or len(nsc) == 0):
        errs.append(f"primitive {pid}: uses an 'analogy' basis but has no not_source_claim "
                    f"disclaiming the metaphor")

    for key in ("derived_claim", "verifier", "failure_mode"):
        if key in prim and not _nonempty_str(prim[key]):
            errs.append(f"primitive {pid}: '{key}' must be a non-empty string")
    return errs


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_registry(primitives_path: Path, sources_path: Path) -> list[str]:
    """Validate a full registry: sources first, then primitives against them."""
    errs: list[str] = []
    ledger = load(sources_path)
    sources = ledger.get("sources")
    if not isinstance(sources, list) or not sources:
        return [f"source ledger {sources_path}: 'sources' must be a non-empty list"]
    source_ids: set[str] = set()
    for src in sources:
        errs.extend(validate_source(src))
        sid = src.get("source_id")
        if isinstance(sid, str):
            if sid in source_ids:
                errs.append(f"source {sid}: duplicate source_id")
            source_ids.add(sid)

    reg = load(primitives_path)
    prims = reg.get("primitives")
    if not isinstance(prims, list) or not prims:
        errs.append(f"primitive registry {primitives_path}: 'primitives' must be a non-empty list")
        prims = []
    seen: set[str] = set()
    for prim in prims:
        errs.extend(validate_primitive(prim, source_ids))
        pid = prim.get("primitive_id")
        if isinstance(pid, str):
            if pid in seen:
                errs.append(f"primitive {pid}: duplicate primitive_id")
            seen.add(pid)
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primitives", type=Path, default=DEFAULT_PRIMITIVES)
    ap.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    a = ap.parse_args()
    errs = validate_registry(a.primitives, a.sources)
    if errs:
        print(f"FAIL — {len(errs)} problem(s) in the AXM primitive registry:\n", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    reg = load(a.primitives)
    ledger = load(a.sources)
    n_p = len(reg.get("primitives", []))
    n_s = len(ledger.get("sources", []))
    n_ms = sum(1 for s in ledger.get("sources", []) if s.get("kind") == "model_synthesis")
    print(f"OK — {n_p} primitives, all sourced; {n_s} sources "
          f"({n_ms} model_synthesis, each with a named author).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
