"""Deterministic tests for the strict cart0@1 bridge; zero model calls."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.cart0_anchor import build, rehydrate, resurface, verify  # noqa:E402

PYTHON = sys.executable
SPEC = ROOT / "experiments" / "cart0_anchor_prototype" / "task_state.json"
CATALOG = ROOT / "experiments" / "cart0_anchor_prototype" / "cards.json"
PROFILE = ROOT / "experiments" / "cart0_anchor_prototype" / "transition_profile.json"


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="cart0-profile-tests-"))
    try:
        bundle = parent / "bundle"
        receipt = build(ROOT, SPEC, CATALOG, PROFILE, bundle, "implementation_start", 256)
        assert receipt["profiles_checked"] == ["cart0@1"]
        assert receipt["semantic_truth_proven"] is False
        assert receipt["instruction_safety_proven"] is False
        assert receipt["anchor_metrics"]["approx_tokens_bytes_div_4"] <= 256
        verify(ROOT, bundle)
        prompt = resurface(ROOT, bundle, "implementation_start", "Run the repair.", None)
        assert b"Use only the admitted active catalog" in prompt
        evidence = rehydrate(ROOT, bundle, "000.200.GATED", None)
        assert b"TRUST: untrusted-source-evidence" in evidence
        assert b"INSTRUCTION_AUTHORITY: false" in evidence

        invalid_spec = json.loads(SPEC.read_text(encoding="utf-8"))
        invalid_spec["evidence_paths"] = ["STATE.md\x00.txt"]
        invalid_spec_path = parent / "invalid-nul-spec.json"
        invalid_spec_path.write_text(json.dumps(invalid_spec), encoding="utf-8")
        refused = subprocess.run([PYTHON, str(ROOT / "scripts" / "cart0_anchor.py"), "build",
            "--repo", str(ROOT), "--spec", str(invalid_spec_path), "--catalog", str(CATALOG),
            "--profile", str(PROFILE), "--out", str(parent / "invalid-bundle"),
            "--boundary", "implementation_start"], capture_output=True, text=True)
        assert refused.returncode != 0
        assert "CART0_ANCHOR_REFUSED:" in refused.stderr
        assert "ValueError" not in refused.stderr

        out = parent / "conformance"
        result = subprocess.run([PYTHON, str(ROOT / "experiments" / "cart0_anchor_prototype" /
            "run_profile_conformance.py"), "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        conformance = json.loads((out / "conformance_receipt.json").read_text(encoding="utf-8"))
        assert conformance["passed_count"] == conformance["count"] == 15
        assert conformance["reject_all_guard_passed"] is True
        assert conformance["model_calls"] == 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    print("OK - strict cart0@1 build/verify/quarantine plus 15/15 conformance vectors; zero model calls")
    return 0


if __name__ == "__main__": raise SystemExit(main())
