#!/usr/bin/env python3
"""Tests for scripts/validate_primitives.py and the committed AXM registry.

Runs under pytest or standalone (`python tests/test_validate_primitives.py`),
stdlib-only. The happy-path test is the acceptance gate for the committed
registry; the failure tests prove the guard actually bites on each rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import validate_primitives as vp  # noqa: E402


# A minimal, valid source set the failure-case primitives can cite.
GOOD_SOURCES = {"known_source", "another_source"}


def _prim(**over):
    """A valid baseline primitive; override single fields to build failure cases."""
    p = {
        "primitive_id": "example",
        "name": "Example",
        "status": "derived",
        "source_basis": [
            {"source_id": "known_source", "support_type": "direct_fact", "supports": "a fact"}
        ],
        "derived_claim": "an architectural mapping",
        "not_source_claim": ["the source does not define AXM"],
        "verifier": "scripts/validate_primitives.py",
        "failure_mode": "drifts into metaphor",
    }
    p.update(over)
    return p


# ---- happy path: the committed registry must validate ----

def test_committed_registry_is_valid():
    errs = vp.validate_registry(vp.DEFAULT_PRIMITIVES, vp.DEFAULT_SOURCES)
    assert errs == [], "committed registry should be clean, got:\n" + "\n".join(errs)


def test_committed_registry_has_expected_primitives():
    reg = vp.load(vp.DEFAULT_PRIMITIVES)
    ids = {p["primitive_id"] for p in reg["primitives"]}
    # the anti-vibes seeds, including the two model-authored provenance records
    assert {"black_letter_axm", "waterline", "hidden_grading",
            "proof_knot", "capture_ledger", "axm_provenance_layer",
            "axm_ontology"} <= ids


def test_model_synthesis_sources_name_their_author():
    ledger = vp.load(vp.DEFAULT_SOURCES)
    ms = [s for s in ledger["sources"] if s.get("kind") == "model_synthesis"]
    assert ms, "expected the gpt-5.5-high ledger and gpt-4o spectra sources"
    for s in ms:
        assert s.get("author"), f"{s['source_id']} must name its author model"


# ---- failure cases: each rule must reject ----

def _has(errs, needle):
    return any(needle in e for e in errs)


def test_missing_source_basis_fails():
    errs = vp.validate_primitive(_prim(source_basis=[]), GOOD_SOURCES)
    assert _has(errs, "source_basis must be a non-empty list")


def test_invalid_support_type_fails():
    p = _prim(source_basis=[{"source_id": "known_source", "support_type": "vibes", "supports": "x"}])
    errs = vp.validate_primitive(p, GOOD_SOURCES)
    assert _has(errs, "invalid support_type")


def test_dangling_source_id_fails():
    p = _prim(source_basis=[{"source_id": "ghost_source", "support_type": "direct_fact", "supports": "x"}])
    errs = vp.validate_primitive(p, GOOD_SOURCES)
    assert _has(errs, "does not resolve")


def test_missing_not_source_claim_fails():
    errs = vp.validate_primitive(_prim(not_source_claim=[]), GOOD_SOURCES)
    assert _has(errs, "not_source_claim must be a non-empty list")


def test_analogy_without_guard_fails():
    p = _prim(
        source_basis=[{"source_id": "known_source", "support_type": "analogy", "supports": "a metaphor"}],
        not_source_claim=[],
    )
    errs = vp.validate_primitive(p, GOOD_SOURCES)
    assert _has(errs, "analogy") and _has(errs, "not_source_claim")


def test_missing_required_field_fails():
    p = _prim()
    del p["derived_claim"]
    errs = vp.validate_primitive(p, GOOD_SOURCES)
    assert _has(errs, "missing required field 'derived_claim'")


def test_model_synthesis_without_author_fails():
    src = {"source_id": "some_model_doc", "title": "t", "kind": "model_synthesis",
           "locator": "x", "retrieved": "2026-07-09", "basis_class": "synthesis"}
    errs = vp.validate_source(src)
    assert _has(errs, "requires a non-empty 'author'")


def test_valid_primitive_passes():
    assert vp.validate_primitive(_prim(), GOOD_SOURCES) == []


def _run_standalone() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
