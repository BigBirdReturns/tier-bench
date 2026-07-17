"""Model-free tests for the content-addressed v0.3 continuation manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sol_root_matched_config"
sys.path.insert(0, str(EXPERIMENT))

from build_machine_continuation_v0_3 import DEFAULT_OUTPUT, build_manifest, verify_manifest  # noqa: E402


def main() -> int:
    git = os.environ.get("GIT_EXE", "git")
    observed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    source = observed["source"]["artifact_commit"]
    expected = build_manifest(git, source)
    assert observed == expected
    receipt = verify_manifest(git, DEFAULT_OUTPUT)
    assert receipt["all_pass"] is True
    assert receipt["provider_calls"] == 0
    assert all(ref["commit"] == source and ref["hash_basis"] == "git_blob_bytes" for ref in observed["evidence_refs"])
    checks = 1

    parent = Path(tempfile.mkdtemp(prefix="sol-root-machine-continuation-"))
    try:
        broken = parent / "000.000.json"
        tampered = json.loads(json.dumps(observed))
        tampered["evidence_refs"][0]["blob_sha256"] = "0" * 64
        broken.write_text(json.dumps(tampered), encoding="utf-8")
        assert verify_manifest(git, broken)["all_pass"] is False
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    checks += 1

    print(f"OK - {checks} machine-continuation checks; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
