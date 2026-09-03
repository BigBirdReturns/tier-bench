#!/usr/bin/env python3
"""Independent cross-platform audit of the repaired Astra Stage 2 control-identity release."""

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
from astra_stage2.control_identity import binding_template, validate_binding_config

BINDER_HEAD = "af03cef494a509ab7ba5df29fa4b4ccba423f1f8"
BINDER_TREE = "519ea2f8f448a464e817a024ad8ed1ac64493931"
RELEASE_HEAD = "148484098fae50923e4df6ed013963480734be7f"
RELEASE_TREE = "d0c2a9e49b5249018e6003d40f17e06f19b43835"
RELEASE_RUN = 33789124430
EVIDENCE_ARTIFACT_ID = 9906614765
PUBLICATION_ARTIFACT_ID = 9906615592
EVIDENCE_ZIP_SHA256 = "4f9a6f65fa949cc277a98a2b164bf709ab1f6117ac5b0a703bfb9ecc5d0eb752"
PUBLICATION_ZIP_SHA256 = "2bb8101e643208eb4bfe4b1e85c5ec14c27ae4c2d0679404378c9249aee431fb"
QUALIFICATION_PAYLOAD = "56cbb64b15f7a692fc27d051d4d35bcd3db2ccf1b8f9879240f8ee0d8acf02ba"
PUBLICATION_PAYLOAD = "c28b423775e954919f226ad9dff56dfc80a4cee288b29571493a9efb88ad10dd"
WINDOWS_RECEIPT_SHA256 = "80b37e9b4b4bf0f3d8e5e120a28af4236c6c4c8c5a487506cc4f159daf784991"

RELEASE_PATHS = {
    ".github/workflows/astra-stage2-control-identity-release.yml",
    "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
    "tests/test_astra_stage2_control_identity.py",
    "tests/test_astra_stage2_control_identity_release.py",
}
AUDIT_PATHS = {
    ".github/workflows/astra-stage2-control-identity-windows-release-audit.yml",
    "audits/astra_stage2_control_identity_windows_release_audit.py",
}
RECOGNIZED_PROVIDER_ENV = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
}


def _git(repo_root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or str(process.returncode)
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return process.stdout.strip()


def _git_success(repo_root: Path, *arguments: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        check=False,
    ).returncode == 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_hash(value: dict[str, Any]) -> str:
    return sha256_object(
        {key: child for key, child in value.items() if key != "payload_sha256"}
    )


def _safe_extract(path: Path, destination: Path) -> dict[str, dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    members: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"CRC failure in {path.name}: {bad}")
        infos = archive.infolist()
        if not infos:
            raise RuntimeError(f"{path.name} is empty")
        root = destination.resolve()
        for info in infos:
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
            members[info.filename] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    return members


def _expect_refusal(
    label: str,
    action: Callable[[], Any],
    attacks: list[dict[str, Any]],
) -> None:
    try:
        action()
    except Stage2Error as exc:
        attacks.append(
            {
                "label": label,
                "expected": "REFUSAL",
                "observed": "REFUSAL",
                "passed": True,
                "detail": str(exc),
            }
        )
        return
    attacks.append(
        {
            "label": label,
            "expected": "REFUSAL",
            "observed": "ACCEPTED",
            "passed": False,
        }
    )


def execute(
    repo_root: Path,
    evidence_zip: Path,
    publication_zip: Path,
    windows_audit_receipt: Path,
) -> dict[str, Any]:
    audit_head = _git(repo_root, "rev-parse", "HEAD")
    audit_tree = _git(repo_root, "rev-parse", "HEAD^{tree}")

    if _git(repo_root, "rev-parse", f"{BINDER_HEAD}^{{tree}}") != BINDER_TREE:
        raise RuntimeError("binder tree differs from frozen audit coordinate")
    if _git(repo_root, "rev-parse", f"{RELEASE_HEAD}^{{tree}}") != RELEASE_TREE:
        raise RuntimeError("release tree differs from frozen audit coordinate")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", BINDER_HEAD, RELEASE_HEAD):
        raise RuntimeError("release is not descended from exact binder")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", RELEASE_HEAD, audit_head):
        raise RuntimeError("audit is not descended from exact release")

    release_paths = {
        item
        for item in _git(repo_root, "diff", "--name-only", f"{BINDER_HEAD}...{RELEASE_HEAD}").splitlines()
        if item
    }
    audit_paths = {
        item
        for item in _git(repo_root, "diff", "--name-only", f"{RELEASE_HEAD}...{audit_head}").splitlines()
        if item
    }
    if release_paths != RELEASE_PATHS:
        raise RuntimeError(f"release path set mismatch: {sorted(release_paths)}")
    if audit_paths != AUDIT_PATHS:
        raise RuntimeError(f"audit path set mismatch: {sorted(audit_paths)}")
    if _git(repo_root, "status", "--porcelain"):
        raise RuntimeError("audit checkout is not clean")

    provider_credentials = sorted(
        name for name in RECOGNIZED_PROVIDER_ENV if os.environ.get(name)
    )
    if provider_credentials:
        raise RuntimeError("recognized provider credentials are present")

    if _sha256_file(evidence_zip) != EVIDENCE_ZIP_SHA256:
        raise RuntimeError("release evidence ZIP digest mismatch")
    if _sha256_file(publication_zip) != PUBLICATION_ZIP_SHA256:
        raise RuntimeError("release publication ZIP digest mismatch")

    windows_receipt = strict_json_load(windows_audit_receipt)
    if windows_receipt != {
        "schema": "tier-bench/astra-stage2-control-identity-windows-audit@1",
        "release_head_sha1": RELEASE_HEAD,
        "release_tree_sha1": RELEASE_TREE,
        "runner": "windows-2025",
        "tests": 27,
        "passed": 26,
        "skipped": 1,
        "failed": 0,
        "errors": 0,
        "powershell_parse": "PASS",
        "launcher_preflight": "PASS",
        "preflight_downloads": 0,
        "model_calls": 0,
        "provider_calls": 0,
        "actual_executable_control_identities": "UNBOUND",
    }:
        raise RuntimeError("independent Windows audit receipt differs")

    with tempfile.TemporaryDirectory(prefix="astra-control-windows-release-audit-") as temp:
        artifact_root = Path(temp)
        evidence_members = _safe_extract(evidence_zip, artifact_root / "evidence")
        publication_members = _safe_extract(publication_zip, artifact_root / "publication")
        qualification = strict_json_load(
            artifact_root / "evidence" / "qualification-receipt.json"
        )
        publication = strict_json_load(
            artifact_root / "publication" / "publication-index.json"
        )

        if qualification.get("payload_sha256") != QUALIFICATION_PAYLOAD:
            raise RuntimeError("qualification payload coordinate mismatch")
        if _payload_hash(qualification) != QUALIFICATION_PAYLOAD:
            raise RuntimeError("qualification payload does not rederive")
        if publication.get("payload_sha256") != PUBLICATION_PAYLOAD:
            raise RuntimeError("publication payload coordinate mismatch")
        if _payload_hash(publication) != PUBLICATION_PAYLOAD:
            raise RuntimeError("publication payload does not rederive")

        if qualification.get("source", {}).get("head_sha1") != RELEASE_HEAD:
            raise RuntimeError("qualification source head mismatch")
        if qualification.get("source", {}).get("tree_sha1") != RELEASE_TREE:
            raise RuntimeError("qualification source tree mismatch")
        if qualification.get("conformance") != {
            "binder_tests": 20,
            "control_roles": 3,
            "cross_platform_runtime_fixture": True,
            "expected_empirical_observations": 648,
            "generator_cases": 108,
            "linux_skipped": 0,
            "linux_tests": 27,
            "powershell_parse_linux": True,
            "powershell_parse_windows": True,
            "release_tests": 7,
            "repository_root_discovery_tested": True,
            "tests": 27,
            "windows_preflight_executed": True,
            "windows_receipt_sha256": WINDOWS_RECEIPT_SHA256,
            "windows_skipped": 1,
            "windows_tests": 27,
        }:
            raise RuntimeError("qualification conformance ledger differs")

        if qualification.get("actual_binding") != {
            "bound_controls": 0,
            "empirical_observations": 0,
            "local_hardware_receipts_seen": 0,
            "local_model_bytes_seen": 0,
            "local_runtime_bytes_seen": 0,
            "state": "UNBOUND",
        }:
            raise RuntimeError("qualification widened actual binding authority")

        if publication.get("workflow_run_id") != RELEASE_RUN:
            raise RuntimeError("publication run mismatch")
        if publication.get("source_head_sha1") != RELEASE_HEAD:
            raise RuntimeError("publication source head mismatch")
        if publication.get("source_tree_sha1") != RELEASE_TREE:
            raise RuntimeError("publication source tree mismatch")
        if publication.get("qualification_payload_sha256") != QUALIFICATION_PAYLOAD:
            raise RuntimeError("publication qualification binding mismatch")
        if publication.get("windows_receipt_sha256") != WINDOWS_RECEIPT_SHA256:
            raise RuntimeError("publication Windows receipt binding mismatch")
        if publication.get("actual_control_identities") != "UNBOUND":
            raise RuntimeError("publication widened actual identity authority")
        if publication.get("provider_or_model_calls") != 0:
            raise RuntimeError("publication widened provider/model-call authority")

        linux_log = (
            artifact_root / "evidence" / "test-control-identity-linux.log"
        ).read_text(encoding="utf-8")
        if re.findall(
            r"^Ran\s+(\d+)\s+tests?\s+in\s+",
            linux_log,
            flags=re.MULTILINE,
        ) != ["27"]:
            raise RuntimeError("retained Linux log does not prove 27 tests")
        if not re.search(r"(?m)^OK$", linux_log):
            raise RuntimeError("retained Linux log is not clean")

        launcher = (
            artifact_root
            / "evidence"
            / "Invoke-AstraStage2ControlIdentityBinding.ps1"
        ).read_text(encoding="utf-8")
        for required in (
            "${Repository}: expected",
            "Resolve-TierBenchRepositoryRoot",
            r"D:\Projects\Measurement\Tier-Bench\main",
            "[ValidateSet('Preflight', 'Prepare', 'Bind', 'Verify')]",
            "state = 'PREFLIGHT_PASS'",
            "actual_executable_control_identities = 'UNBOUND'",
            "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND",
            "non-authoritative template",
        ):
            if required not in launcher:
                raise RuntimeError(f"retained launcher missing repair marker: {required}")
        for forbidden in (
            '"$Repository: expected',
            "reset --hard",
            "checkout -f",
            "model.generate(",
            "/v1/chat/completions",
        ):
            if forbidden.lower() in launcher.lower():
                raise RuntimeError(f"retained launcher contains forbidden token: {forbidden}")

    attacks: list[dict[str, Any]] = []
    base = binding_template()

    mutated = copy.deepcopy(base)
    mutated["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _expect_refusal(
        "unknown binding-root property",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    mutated = copy.deepcopy(base)
    mutated["law"]["blob_sha1"] = "0" * 40
    _expect_refusal(
        "law blob substitution",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    mutated = copy.deepcopy(base)
    mutated["controls"][0]["source_repository"] = "attacker/repo"
    _expect_refusal(
        "source repository substitution",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    mutated = copy.deepcopy(base)
    mutated["controls"][0]["checkpoint_revision_sha1"] = "1" * 40
    _expect_refusal(
        "checkpoint revision substitution",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    mutated = copy.deepcopy(base)
    mutated["controls"].reverse()
    _expect_refusal(
        "control ordering substitution",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    mutated = copy.deepcopy(base)
    mutated["controls"][0]["hardware"]["selected_device_indices"] = []
    _expect_refusal(
        "missing selected hardware",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    mutated = copy.deepcopy(base)
    mutated["controls"][0]["effort_mapping"]["high"] = copy.deepcopy(
        mutated["controls"][0]["effort_mapping"]["low"]
    )
    _expect_refusal(
        "aliased effort mappings",
        lambda: validate_binding_config(mutated),
        attacks,
    )

    failed = [attack for attack in attacks if not attack["passed"]]
    receipt: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-windows-release-audit@1",
        "target": {
            "pull_request": 187,
            "binder_head_sha1": BINDER_HEAD,
            "binder_tree_sha1": BINDER_TREE,
            "release_head_sha1": RELEASE_HEAD,
            "release_tree_sha1": RELEASE_TREE,
            "qualification_run": RELEASE_RUN,
            "evidence_artifact": EVIDENCE_ARTIFACT_ID,
            "publication_artifact": PUBLICATION_ARTIFACT_ID,
            "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
            "publication_payload_sha256": PUBLICATION_PAYLOAD,
            "windows_conformance_receipt_sha256": WINDOWS_RECEIPT_SHA256,
        },
        "audit": {
            "head_sha1": audit_head,
            "tree_sha1": audit_tree,
            "release_paths": sorted(release_paths),
            "audit_paths": sorted(audit_paths),
        },
        "artifacts": {
            "evidence_zip_sha256": EVIDENCE_ZIP_SHA256,
            "publication_zip_sha256": PUBLICATION_ZIP_SHA256,
            "evidence_member_count": len(evidence_members),
            "publication_member_count": len(publication_members),
        },
        "rederived": {
            "tests_linux": 27,
            "tests_windows": 27,
            "windows_passed": 26,
            "windows_skipped": 1,
            "windows_failed": 0,
            "windows_errors": 0,
            "windows_powershell_parse": "PASS",
            "windows_launcher_preflight": "PASS",
            "control_roles": 3,
            "generator_cases": 108,
            "expected_empirical_observations": 648,
            "actual_executable_control_identities": "UNBOUND",
        },
        "attacks": attacks,
        "attack_count": len(attacks),
        "refused_count": len(attacks) - len(failed),
        "failed_count": len(failed),
        "failed_labels": [attack["label"] for attack in failed],
        "disposition": (
            "PASS_CROSS_PLATFORM_PROVIDER_FREE_RELEASE_ONLY"
            if not failed
            else "CHANGES_REQUESTED_BEFORE_LOCAL_PREPARE"
        ),
        "authority": {
            "actual_executable_control_identities": "UNBOUND",
            "provider_or_model_calls": 0,
            "empirical_subject_execution": False,
            "empirical_calibration": "NOT_RUN",
            "numeric_stage2_freeze": "NOT_ISSUED",
            "live_provider_dispatch": "PROHIBITED",
            "merge_authority": "NONE",
        },
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--publication-zip", type=Path, required=True)
    parser.add_argument("--windows-audit-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    receipt = execute(
        args.repo_root.resolve(),
        args.evidence_zip.resolve(),
        args.publication_zip.resolve(),
        args.windows_audit_receipt.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 1 if receipt["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
