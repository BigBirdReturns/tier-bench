#!/usr/bin/env python3
"""Independent provider-free audit of the 27-test Astra control-identity release."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

from astra_stage2.canonical import Stage2Error, sha256_object, strict_json_load
from astra_stage2.control_identity import (
    LAW_BLOB_SHA1,
    LAW_COMMIT_SHA1,
    PUBLIC_CONTROLS,
    SCAFFOLD_HEAD_SHA1,
    STAGE1_JOIN_HEAD_SHA1,
    binding_template,
    validate_binding_config,
)

BINDER_HEAD = "af03cef494a509ab7ba5df29fa4b4ccba423f1f8"
BINDER_TREE = "519ea2f8f448a464e817a024ad8ed1ac64493931"
RELEASE_HEAD = "b3948e62a66a13ed6013ea075552c09b9e3f5b1d"
RELEASE_TREE = "3a3f2919e9151736492da44911c9c3d3952a8585"
RELEASE_RUN = 33780120844
EVIDENCE_ARTIFACT_ID = 9903209622
PUBLICATION_ARTIFACT_ID = 9903210156
EVIDENCE_ZIP_SHA256 = "7c79a142e4c77df9ef9c961cd57acfdafd5b72ab4fb87f38682fafb4a184e526"
PUBLICATION_ZIP_SHA256 = "a387403acdf1d941ec64657076e80404f50ed5d0b4507c2edd7a1c60d7fa1d1c"
QUALIFICATION_PAYLOAD = "ec11af9b733f8c343b2bc41c4e4273b210837390aee501f675fb010be91d632d"
PUBLICATION_PAYLOAD = "e5a78a4503f4a246f248c93704fbd6e9d810396a9565413a6e68fb4c319fbb44"
RELEASE_PATHS = {
    ".github/workflows/astra-stage2-control-identity-release.yml",
    "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
    "tests/test_astra_stage2_control_identity_release.py",
}
AUDIT_PATHS = {
    ".github/workflows/astra-stage2-control-identity-release-audit.yml",
    "audits/astra_stage2_control_identity_release_audit.py",
}
RECOGNIZED_PROVIDER_ENV = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "MISTRAL_API_KEY", "COHERE_API_KEY", "XAI_API_KEY", "GROQ_API_KEY",
    "TOGETHER_API_KEY", "FIREWORKS_API_KEY",
}


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], text=True, encoding="utf-8", errors="replace", capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git exit {proc.returncode}")
    return proc.stdout.strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _payload(value: dict[str, Any]) -> str:
    return sha256_object({k: v for k, v in value.items() if k != "payload_sha256"})


def _safe_extract(path: Path, destination: Path) -> dict[str, dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"CRC failure: {bad}")
        if not archive.infolist():
            raise RuntimeError("empty ZIP")
        root = destination.resolve()
        for info in archive.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError(f"unsafe ZIP member: {info.filename}")
            target = (destination / member).resolve()
            target.relative_to(root)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            data = archive.read(info)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            result[info.filename] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return result


def _refusal(label: str, action: Callable[[], Any], attacks: list[dict[str, Any]]) -> None:
    try:
        action()
    except Stage2Error as exc:
        attacks.append({"label": label, "expected": "REFUSAL", "observed": "REFUSAL", "passed": True, "detail": str(exc)})
        return
    attacks.append({"label": label, "expected": "REFUSAL", "observed": "ACCEPTED", "passed": False})


def execute(repo_root: Path, evidence_zip: Path, publication_zip: Path) -> dict[str, Any]:
    audit_head = _git(repo_root, "rev-parse", "HEAD")
    audit_tree = _git(repo_root, "rev-parse", "HEAD^{tree}")
    if _git(repo_root, "rev-parse", f"{BINDER_HEAD}^{{tree}}") != BINDER_TREE:
        raise RuntimeError("binder tree drift")
    if _git(repo_root, "rev-parse", f"{RELEASE_HEAD}^{{tree}}") != RELEASE_TREE:
        raise RuntimeError("release tree drift")
    subprocess.run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", BINDER_HEAD, RELEASE_HEAD], check=True)
    subprocess.run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", RELEASE_HEAD, audit_head], check=True)
    release_paths = {x for x in _git(repo_root, "diff", "--name-only", f"{BINDER_HEAD}...{RELEASE_HEAD}").splitlines() if x}
    audit_paths = {x for x in _git(repo_root, "diff", "--name-only", f"{RELEASE_HEAD}...{audit_head}").splitlines() if x}
    if release_paths != RELEASE_PATHS:
        raise RuntimeError(f"release path set mismatch: {sorted(release_paths)}")
    if audit_paths != AUDIT_PATHS:
        raise RuntimeError(f"audit path set mismatch: {sorted(audit_paths)}")
    if _git(repo_root, "status", "--porcelain"):
        raise RuntimeError("audit checkout is dirty")
    if [x for x in RECOGNIZED_PROVIDER_ENV if os.environ.get(x)]:
        raise RuntimeError("provider credential present")

    if _sha256(evidence_zip) != EVIDENCE_ZIP_SHA256:
        raise RuntimeError("evidence artifact ZIP hash mismatch")
    if _sha256(publication_zip) != PUBLICATION_ZIP_SHA256:
        raise RuntimeError("publication artifact ZIP hash mismatch")

    with tempfile.TemporaryDirectory(prefix="astra-control-release-audit-") as temp:
        root = Path(temp)
        evidence_members = _safe_extract(evidence_zip, root / "evidence")
        publication_members = _safe_extract(publication_zip, root / "publication")
        qualification = strict_json_load(root / "evidence" / "qualification-receipt.json")
        publication = strict_json_load(root / "publication" / "publication-index.json")
        if qualification.get("payload_sha256") != QUALIFICATION_PAYLOAD or _payload(qualification) != QUALIFICATION_PAYLOAD:
            raise RuntimeError("qualification payload mismatch")
        if publication.get("payload_sha256") != PUBLICATION_PAYLOAD or _payload(publication) != PUBLICATION_PAYLOAD:
            raise RuntimeError("publication payload mismatch")
        if qualification.get("conformance") != {
            "tests": 27,
            "binder_tests": 20,
            "release_tests": 7,
            "control_roles": 3,
            "generator_cases": 108,
            "expected_empirical_observations": 648,
            "pinned_one_command_launcher_present": True,
            "launcher_pins_exact_binder_head": True,
            "launcher_prepare_mode_executes_no_model": True,
            "launcher_refuses_template_runtime_and_effort_on_bind": True,
        }:
            raise RuntimeError("27-test conformance ledger differs")
        expected_binding = {
            "state": "UNBOUND", "bound_controls": 0, "empirical_observations": 0,
            "local_model_bytes_seen": 0, "local_runtime_bytes_seen": 0,
            "local_hardware_receipts_seen": 0,
        }
        if qualification.get("actual_binding") != expected_binding:
            raise RuntimeError("release widened actual binding authority")
        if publication.get("actual_control_identities") != "UNBOUND" or publication.get("tests") != 27:
            raise RuntimeError("publication widened authority or lost test denominator")
        log = (root / "evidence" / "test-control-identity-release.log").read_text(encoding="utf-8")
        if re.findall(r"^Ran\s+(\d+)\s+tests?\s+in\s+", log, flags=re.MULTILINE) != ["27"]:
            raise RuntimeError("test log does not prove 27 tests")
        launcher = (root / "evidence" / "Invoke-AstraStage2ControlIdentityBinding.ps1").read_text(encoding="utf-8")
        for required in (BINDER_HEAD, BINDER_TREE, LAW_COMMIT_SHA1, LAW_BLOB_SHA1, SCAFFOLD_HEAD_SHA1, STAGE1_JOIN_HEAD_SHA1,
                         "b392d2cb7aaa73475b93028221523c47f49f66a2", "b87cf3aa2186937b0d0362a684d7d30f234543e3",
                         "63de1ec1902ed143fe62250b6ddb14cb65f06e1a", "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND"):
            if required not in launcher:
                raise RuntimeError(f"launcher missing frozen coordinate {required}")
        for forbidden in ("model.generate(", "/v1/chat/completions", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "reset --hard", "checkout -f"):
            if forbidden.lower() in launcher.lower():
                raise RuntimeError(f"launcher contains forbidden operation {forbidden}")
        if "[string]$Mode = 'Prepare'" not in launcher or "Bind is refused" not in launcher:
            raise RuntimeError("launcher does not default to non-executing prepare/refusal boundary")

    attacks: list[dict[str, Any]] = []
    base = binding_template()
    mutation = copy.deepcopy(base); mutation["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _refusal("unknown binding-root field", lambda: validate_binding_config(mutation), attacks)
    mutation = copy.deepcopy(base); mutation["law"]["blob_sha1"] = "0" * 40
    _refusal("law blob substitution", lambda: validate_binding_config(mutation), attacks)
    mutation = copy.deepcopy(base); mutation["controls"][0]["source_repository"] = "attacker/repo"
    _refusal("source repository substitution", lambda: validate_binding_config(mutation), attacks)
    mutation = copy.deepcopy(base); mutation["controls"][0]["checkpoint_revision_sha1"] = "1" * 40
    _refusal("checkpoint revision substitution", lambda: validate_binding_config(mutation), attacks)
    mutation = copy.deepcopy(base); mutation["controls"].reverse()
    _refusal("control ordering substitution", lambda: validate_binding_config(mutation), attacks)
    mutation = copy.deepcopy(base); mutation["controls"][0]["hardware"]["selected_device_indices"] = []
    _refusal("missing selected hardware", lambda: validate_binding_config(mutation), attacks)
    mutation = copy.deepcopy(base); mutation["controls"][0]["effort_mapping"]["high"] = copy.deepcopy(mutation["controls"][0]["effort_mapping"]["low"])
    _refusal("aliased effort mappings", lambda: validate_binding_config(mutation), attacks)
    failed = [x for x in attacks if not x["passed"]]

    receipt: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-release-audit@1",
        "target": {
            "release_head": RELEASE_HEAD, "release_tree": RELEASE_TREE,
            "binder_head": BINDER_HEAD, "binder_tree": BINDER_TREE,
            "qualification_run": RELEASE_RUN,
            "evidence_artifact": EVIDENCE_ARTIFACT_ID,
            "publication_artifact": PUBLICATION_ARTIFACT_ID,
        },
        "audit": {"head_sha1": audit_head, "tree_sha1": audit_tree, "release_paths": sorted(release_paths), "audit_paths": sorted(audit_paths)},
        "artifacts": {"evidence_members": evidence_members, "publication_members": publication_members},
        "rederived": {"tests": 27, "binder_tests": 20, "release_tests": 7, "control_roles": 3, "generator_cases": 108,
                      "expected_empirical_observations": 648, "actual_control_identities": "UNBOUND"},
        "attacks": attacks,
        "attack_count": len(attacks), "refused_count": len(attacks) - len(failed), "failed_count": len(failed),
        "disposition": "PASS_PROVIDER_FREE_RELEASE_ONLY" if not failed else "CHANGES_REQUESTED_BEFORE_LOCAL_BINDING",
        "authority": {"provider_or_model_calls": 0, "empirical_subject_execution": False, "numeric_stage2_freeze": "NOT_ISSUED",
                      "live_provider_dispatch": "PROHIBITED", "merge_authority": "NONE"},
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--publication-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    receipt = execute(args.repo_root.resolve(), args.evidence_zip.resolve(), args.publication_zip.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 1 if receipt["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
