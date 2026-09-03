#!/usr/bin/env python3
"""Independent audit of the final Astra control-identity successor scope."""

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
SCOPE_PARENT_HEAD = "125fdc367920960421d1e080900f1806637277f4"
SCOPE_PARENT_TREE = "ccab08e1192346f9c386b0f41ffaab77bac73194"
RELEASE_HEAD = "46840d9ce0e3732b84cd4ad40e828c42326bcc05"
RELEASE_TREE = "ea4e5ececd37bf440af5c01bfe416cd5df8304a5"
RELEASE_RUN = 33800919918
EVIDENCE_ARTIFACT_ID = 9911030201
PUBLICATION_ARTIFACT_ID = 9911030700
EVIDENCE_ZIP_SHA256 = "5ef88d820bc866c1df02015b6b1725fb09f447a450126ada0dfe8eb7896f7a1f"
PUBLICATION_ZIP_SHA256 = "c184cc19b3e783bba518ddf05d30236e58fd46ac9a6539aec0ae49a73f59f7bb"
QUALIFICATION_PAYLOAD = "bcea66bdaea9fe0b349fc17d738a921e643431c42b7bd4bfec939788bdf4243b"
PUBLICATION_PAYLOAD = "cfa59f1c9813354900f7715ee978fb642b15e9856e1c5fef1b3cbdb74f0e437c"
RELEASE_WINDOWS_RECEIPT_SHA256 = (
    "bdc2587ef54aa6713735db3ef1f8aafe0a8b5b60b3b9ee74d0df7a6bb418c35a"
)
LAUNCHER_SHA256 = "3081af6b3ff3a9026cc5171065c75e6f8d23f1819804a79a88f00b53bd3436e2"
PREDECESSOR_WORKFLOW_SHA256 = (
    "36497dd0720fc58114bb5c49723fbe0fc486ffa71b7ee1562d4594a41375ebc7"
)
BINDER_TEMPLATE_SHA256 = (
    "0292bf17538352f2c27799254bf951418fa517c1ff81f26223c736ea5e89900d"
)

RELEASE_PATHS = {
    ".github/workflows/astra-stage2-control-identity-release.yml",
    ".github/workflows/astra-stage2-control-identity.yml",
    "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
    "tests/test_astra_stage2_control_identity.py",
    "tests/test_astra_stage2_control_identity_release.py",
}
SCOPE_DELTA_PATHS = {
    ".github/workflows/astra-stage2-control-identity-release.yml",
    ".github/workflows/astra-stage2-control-identity.yml",
}
AUDIT_PATHS = {
    ".github/workflows/astra-stage2-control-identity-successor-scope-audit.yml",
    "audits/astra_stage2_control_identity_successor_scope_audit.py",
}
EXPECTED_EVIDENCE_MEMBERS = {
    "Invoke-AstraStage2ControlIdentityBinding.ps1",
    "README.md",
    "SHA256SUMS",
    "astra_stage2_bind_controls.ps1",
    "astra_stage2_bind_controls.py",
    "binding-template.json",
    "predecessor-control-identity-workflow.yml",
    "qualification-receipt.json",
    "release-paths.z",
    "test-control-identity-linux.log",
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
HEX64 = re.compile(r"[0-9a-f]{64}")


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


def _verify_sha256s(root: Path) -> None:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise RuntimeError("release evidence SHA256SUMS is absent")
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError("release evidence SHA256SUMS is empty")
    for line in lines:
        expected, name = line.split(maxsplit=1)
        name = name.strip()
        if name.startswith("./"):
            name = name[2:]
        target = (root / name).resolve()
        target.relative_to(root.resolve())
        if not target.is_file():
            raise RuntimeError(f"SHA256SUMS member is absent: {name}")
        observed = _sha256_file(target)
        if observed != expected:
            raise RuntimeError(f"SHA256SUMS mismatch for {name}")


def _assert_predecessor_scope(text: str) -> None:
    required_pull_request_scope = (
        "  pull_request:\n"
        "    branches:\n"
        "      - joint/astra-stage2-calibration-impl-20260902\n"
        "    paths:\n"
    )
    required_push_scope = (
        "  push:\n"
        "    branches:\n"
        "      - joint/astra-stage2-control-identities-20260903\n"
    )
    if required_pull_request_scope not in text:
        raise RuntimeError("predecessor workflow lacks its exact PR-base scope")
    if required_push_scope not in text:
        raise RuntimeError("predecessor workflow lost its exact candidate push lane")


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


def _validate_windows_receipt(value: dict[str, Any]) -> None:
    expected_scalars = {
        "schema": (
            "tier-bench/"
            "astra-stage2-control-identity-successor-scope-windows-audit@1"
        ),
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
        "preflight_schema": "tier-bench/astra-stage2-control-identity-preflight@2",
        "binder_command_import_probe": "PASS",
        "binder_command": "template",
        "caller_is_non_repository": True,
        "predecessor_workflow_successor_scope": "PASS",
        "preflight_downloads": 0,
        "model_calls": 0,
        "provider_calls": 0,
        "actual_executable_control_identities": "UNBOUND",
    }
    for key, expected in expected_scalars.items():
        if value.get(key) != expected:
            raise RuntimeError(
                f"independent Windows audit receipt field differs: {key}"
            )
    for key in ("preflight_receipt_sha256", "binder_template_probe_sha256"):
        observed = value.get(key)
        if not isinstance(observed, str) or HEX64.fullmatch(observed) is None:
            raise RuntimeError(f"independent Windows audit receipt lacks {key}")
    if value["binder_template_probe_sha256"] != BINDER_TEMPLATE_SHA256:
        raise RuntimeError("independent Windows binder-template probe differs")


def execute(
    repo_root: Path,
    evidence_zip: Path,
    publication_zip: Path,
    windows_audit_receipt: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    audit_head = _git(repo_root, "rev-parse", "HEAD")
    audit_tree = _git(repo_root, "rev-parse", "HEAD^{tree}")

    if _git(repo_root, "rev-parse", f"{BINDER_HEAD}^{{tree}}") != BINDER_TREE:
        raise RuntimeError("binder tree differs from frozen audit coordinate")
    if _git(repo_root, "rev-parse", f"{SCOPE_PARENT_HEAD}^{{tree}}") != SCOPE_PARENT_TREE:
        raise RuntimeError("scope parent tree differs from frozen coordinate")
    if _git(repo_root, "rev-parse", f"{RELEASE_HEAD}^{{tree}}") != RELEASE_TREE:
        raise RuntimeError("release tree differs from frozen audit coordinate")
    if _git(repo_root, "rev-parse", f"{RELEASE_HEAD}^") != SCOPE_PARENT_HEAD:
        raise RuntimeError("final release parent differs from qualified import release")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", BINDER_HEAD, RELEASE_HEAD):
        raise RuntimeError("release is not descended from exact binder")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", RELEASE_HEAD, audit_head):
        raise RuntimeError("audit is not descended from exact release")

    release_paths = {
        item
        for item in _git(
            repo_root,
            "diff",
            "--name-only",
            f"{BINDER_HEAD}...{RELEASE_HEAD}",
        ).splitlines()
        if item
    }
    scope_delta_paths = {
        item
        for item in _git(
            repo_root,
            "diff",
            "--name-only",
            f"{SCOPE_PARENT_HEAD}...{RELEASE_HEAD}",
        ).splitlines()
        if item
    }
    audit_paths = {
        item
        for item in _git(
            repo_root,
            "diff",
            "--name-only",
            f"{RELEASE_HEAD}...{audit_head}",
        ).splitlines()
        if item
    }
    if release_paths != RELEASE_PATHS:
        raise RuntimeError(f"release path set mismatch: {sorted(release_paths)}")
    if scope_delta_paths != SCOPE_DELTA_PATHS:
        raise RuntimeError(
            f"successor scope delta mismatch: {sorted(scope_delta_paths)}"
        )
    if audit_paths != AUDIT_PATHS:
        raise RuntimeError(f"audit path set mismatch: {sorted(audit_paths)}")
    if _git(repo_root, "status", "--porcelain"):
        raise RuntimeError("audit checkout is not clean")

    live_predecessor_path = (
        repo_root / ".github" / "workflows" / "astra-stage2-control-identity.yml"
    )
    live_predecessor = live_predecessor_path.read_text(encoding="utf-8")
    _assert_predecessor_scope(live_predecessor)
    if _sha256_file(live_predecessor_path) != PREDECESSOR_WORKFLOW_SHA256:
        raise RuntimeError("live predecessor workflow digest differs")

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
    _validate_windows_receipt(windows_receipt)
    windows_receipt_sha256 = _sha256_file(windows_audit_receipt)

    with tempfile.TemporaryDirectory(
        prefix="astra-control-successor-scope-audit-"
    ) as temp:
        artifact_root = Path(temp)
        evidence_root = artifact_root / "evidence"
        publication_root = artifact_root / "publication"
        evidence_members = _safe_extract(evidence_zip, evidence_root)
        publication_members = _safe_extract(publication_zip, publication_root)

        if set(evidence_members) != EXPECTED_EVIDENCE_MEMBERS:
            raise RuntimeError(
                "release evidence member set mismatch: "
                + repr(sorted(evidence_members))
            )
        if set(publication_members) != {"publication-index.json"}:
            raise RuntimeError("release publication member set mismatch")
        _verify_sha256s(evidence_root)

        qualification = strict_json_load(
            evidence_root / "qualification-receipt.json"
        )
        publication = strict_json_load(
            publication_root / "publication-index.json"
        )

        if qualification.get("payload_sha256") != QUALIFICATION_PAYLOAD:
            raise RuntimeError("qualification payload coordinate mismatch")
        if _payload_hash(qualification) != QUALIFICATION_PAYLOAD:
            raise RuntimeError("qualification payload does not rederive")
        if publication.get("payload_sha256") != PUBLICATION_PAYLOAD:
            raise RuntimeError("publication payload coordinate mismatch")
        if _payload_hash(publication) != PUBLICATION_PAYLOAD:
            raise RuntimeError("publication payload does not rederive")

        if qualification.get("schema") != (
            "tier-bench/astra-stage2-control-identity-release-qualification@2"
        ):
            raise RuntimeError("qualification schema mismatch")
        if qualification.get("classification") != (
            "CROSS_PLATFORM_PROVIDER_FREE_CONTROL_IDENTITY_RELEASE_"
            "QUALIFIED_ACTUAL_IDENTITIES_UNBOUND"
        ):
            raise RuntimeError("qualification classification mismatch")
        if qualification.get("run_id") != RELEASE_RUN:
            raise RuntimeError("qualification run mismatch")

        expected_source = {
            "binder_head_sha1": BINDER_HEAD,
            "binder_tree_sha1": BINDER_TREE,
            "branch": "release/astra-stage2-control-identity-v1-20260903",
            "head_sha1": RELEASE_HEAD,
            "law_blob_sha1": "77abe4e177fc61e4f52f56ea64494b113f9662fc",
            "law_commit_sha1": "c36c35bf9b70d879e1e1c9ee2f0296879442df3e",
            "scaffold_head_sha1": "9babad4631ef517485c56ea4906aab123e30fad7",
            "stage1_join_head_sha1": "60bca963d63edca267106bc5c7725c2cc1df8dd7",
            "tree_sha1": RELEASE_TREE,
        }
        if qualification.get("source") != expected_source:
            raise RuntimeError("qualification source ledger differs")

        expected_conformance = {
            "binder_tests": 20,
            "control_roles": 3,
            "cross_platform_runtime_fixture": True,
            "expected_empirical_observations": 648,
            "generator_cases": 108,
            "linux_skipped": 0,
            "linux_tests": 27,
            "powershell_parse_linux": True,
            "powershell_parse_windows": True,
            "predecessor_workflow_successor_scope": True,
            "release_tests": 7,
            "repository_root_discovery_tested": True,
            "tests": 27,
            "windows_preflight_executed": True,
            "windows_receipt_sha256": RELEASE_WINDOWS_RECEIPT_SHA256,
            "windows_skipped": 1,
            "windows_tests": 27,
        }
        if qualification.get("conformance") != expected_conformance:
            raise RuntimeError("qualification conformance ledger differs")

        expected_actual_binding = {
            "bound_controls": 0,
            "empirical_observations": 0,
            "local_hardware_receipts_seen": 0,
            "local_model_bytes_seen": 0,
            "local_runtime_bytes_seen": 0,
            "state": "UNBOUND",
        }
        if qualification.get("actual_binding") != expected_actual_binding:
            raise RuntimeError("qualification widened actual binding authority")

        expected_authority = {
            "benchmark_verdict_authority": "NONE",
            "callable_astra_identity": "UNBOUND",
            "empirical_subject_execution": False,
            "live_provider_dispatch": "PROHIBITED",
            "merge_authority": "NONE",
            "numeric_stage2_freeze": "NOT_ISSUED",
            "optional_24_call_block": "DISABLED",
            "provider_or_model_calls": 0,
        }
        if qualification.get("authority") != expected_authority:
            raise RuntimeError("qualification authority ledger differs")

        launcher_entry = qualification.get("files", {}).get(
            "Invoke-AstraStage2ControlIdentityBinding.ps1"
        )
        if launcher_entry != {"bytes": 19676, "sha256": LAUNCHER_SHA256}:
            raise RuntimeError("qualification launcher identity differs")
        predecessor_entry = qualification.get("files", {}).get(
            "predecessor-control-identity-workflow.yml"
        )
        if predecessor_entry != {
            "bytes": 17406,
            "sha256": PREDECESSOR_WORKFLOW_SHA256,
        }:
            raise RuntimeError("qualification predecessor workflow identity differs")

        if publication.get("schema") != (
            "tier-bench/astra-stage2-control-identity-release-publication@2"
        ):
            raise RuntimeError("publication schema mismatch")
        if publication.get("workflow_run_id") != RELEASE_RUN:
            raise RuntimeError("publication run mismatch")
        if publication.get("source_head_sha1") != RELEASE_HEAD:
            raise RuntimeError("publication source head mismatch")
        if publication.get("source_tree_sha1") != RELEASE_TREE:
            raise RuntimeError("publication source tree mismatch")
        if publication.get("qualification_payload_sha256") != QUALIFICATION_PAYLOAD:
            raise RuntimeError("publication qualification binding mismatch")
        if publication.get("windows_receipt_sha256") != RELEASE_WINDOWS_RECEIPT_SHA256:
            raise RuntimeError("publication Windows receipt binding mismatch")
        if publication.get("evidence_artifact") != {
            "id": EVIDENCE_ARTIFACT_ID,
            "sha256": EVIDENCE_ZIP_SHA256,
        }:
            raise RuntimeError("publication evidence-artifact binding mismatch")
        if publication.get("predecessor_workflow_successor_scope") is not True:
            raise RuntimeError("publication omits predecessor workflow scope")
        if publication.get("actual_control_identities") != "UNBOUND":
            raise RuntimeError("publication widened actual identity authority")
        if publication.get("provider_or_model_calls") != 0:
            raise RuntimeError("publication widened provider/model-call authority")
        if publication.get("empirical_calibration") != "NOT_RUN":
            raise RuntimeError("publication widened empirical authority")
        if publication.get("numeric_stage2_freeze") != "NOT_ISSUED":
            raise RuntimeError("publication widened numeric-freeze authority")

        retained_paths = {
            item.decode("utf-8")
            for item in (evidence_root / "release-paths.z").read_bytes().split(b"\0")
            if item
        }
        if retained_paths != RELEASE_PATHS:
            raise RuntimeError("retained release path set differs")

        linux_log = (
            evidence_root / "test-control-identity-linux.log"
        ).read_text(encoding="utf-8")
        if re.findall(
            r"^Ran\s+(\d+)\s+tests?\s+in\s+",
            linux_log,
            flags=re.MULTILINE,
        ) != ["27"]:
            raise RuntimeError("retained Linux log does not prove 27 tests")
        if not re.search(r"(?m)^OK$", linux_log):
            raise RuntimeError("retained Linux log is not clean")

        retained_predecessor_path = (
            evidence_root / "predecessor-control-identity-workflow.yml"
        )
        retained_predecessor = retained_predecessor_path.read_text(encoding="utf-8")
        _assert_predecessor_scope(retained_predecessor)
        if retained_predecessor_path.read_bytes() != live_predecessor_path.read_bytes():
            raise RuntimeError("retained predecessor workflow differs from release bytes")

        launcher_path = (
            evidence_root / "Invoke-AstraStage2ControlIdentityBinding.ps1"
        )
        launcher = launcher_path.read_text(encoding="utf-8")
        if _sha256_file(launcher_path) != LAUNCHER_SHA256:
            raise RuntimeError("retained launcher digest differs")
        live_launcher = (
            repo_root / "scripts" / "Invoke-AstraStage2ControlIdentityBinding.ps1"
        )
        if _sha256_file(live_launcher) != LAUNCHER_SHA256:
            raise RuntimeError("audit-branch launcher differs from release artifact")

        required_launcher_markers = (
            "${Repository}: expected",
            "function Invoke-BinderCommand",
            "[hashtable]$Parameters",
            "Push-Location -LiteralPath $BinderRoot",
            "$env:PYTHONPATH = $BinderRoot",
            "& $Wrapper @Parameters",
            "Command = 'template'",
            "Command = 'probe-hardware'",
            "Command = 'inventory'",
            "Command = 'validate-config'",
            "Command = 'bind'",
            "Command = 'verify'",
            "binder_command_import_probe = 'PASS'",
            "binder_template_probe_sha256",
            "astra-stage2-control-identity-preflight@2",
            "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND",
            "actual_executable_control_identities = 'UNBOUND'",
            "non-authoritative template",
        )
        for required in required_launcher_markers:
            if required not in launcher:
                raise RuntimeError(
                    f"retained launcher missing import-boundary marker: {required}"
                )
        for forbidden in (
            '"$Repository: expected',
            "& $wrapper -Command",
            "reset --hard",
            "checkout -f",
            "model.generate(",
            "/v1/chat/completions",
        ):
            if forbidden.lower() in launcher.lower():
                raise RuntimeError(
                    f"retained launcher contains forbidden token: {forbidden}"
                )

        release_workflow = (
            repo_root
            / ".github"
            / "workflows"
            / "astra-stage2-control-identity-release.yml"
        ).read_text(encoding="utf-8")
        for marker in (
            '".github/workflows/astra-stage2-control-identity.yml"',
            "predecessor-control-identity-workflow.yml",
            '"predecessor_workflow_successor_scope": True',
        ):
            if marker not in release_workflow:
                raise RuntimeError(
                    f"release workflow omits successor-scope evidence: {marker}"
                )

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
        "schema": (
            "tier-bench/"
            "astra-stage2-control-identity-successor-scope-audit@1"
        ),
        "target": {
            "pull_request": 187,
            "binder_head_sha1": BINDER_HEAD,
            "binder_tree_sha1": BINDER_TREE,
            "scope_parent_head_sha1": SCOPE_PARENT_HEAD,
            "scope_parent_tree_sha1": SCOPE_PARENT_TREE,
            "release_head_sha1": RELEASE_HEAD,
            "release_tree_sha1": RELEASE_TREE,
            "release_run": RELEASE_RUN,
            "evidence_artifact_id": EVIDENCE_ARTIFACT_ID,
            "publication_artifact_id": PUBLICATION_ARTIFACT_ID,
        },
        "audit": {
            "head_sha1": audit_head,
            "tree_sha1": audit_tree,
            "audit_paths": sorted(AUDIT_PATHS),
            "release_paths": sorted(RELEASE_PATHS),
            "scope_delta_paths": sorted(SCOPE_DELTA_PATHS),
        },
        "artifacts": {
            "release_evidence_zip_sha256": EVIDENCE_ZIP_SHA256,
            "release_publication_zip_sha256": PUBLICATION_ZIP_SHA256,
            "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
            "publication_payload_sha256": PUBLICATION_PAYLOAD,
            "release_windows_receipt_sha256": RELEASE_WINDOWS_RECEIPT_SHA256,
            "independent_windows_receipt_sha256": windows_receipt_sha256,
            "independent_preflight_receipt_sha256": windows_receipt[
                "preflight_receipt_sha256"
            ],
            "independent_binder_template_probe_sha256": windows_receipt[
                "binder_template_probe_sha256"
            ],
            "predecessor_workflow_sha256": PREDECESSOR_WORKFLOW_SHA256,
        },
        "rederived": {
            "tests_linux": 27,
            "tests_windows": windows_receipt["tests"],
            "windows_passed": windows_receipt["passed"],
            "windows_skipped": windows_receipt["skipped"],
            "windows_failed": windows_receipt["failed"],
            "windows_errors": windows_receipt["errors"],
            "powershell_parse": windows_receipt["powershell_parse"],
            "preflight_schema": windows_receipt["preflight_schema"],
            "binder_command_import_probe": windows_receipt[
                "binder_command_import_probe"
            ],
            "binder_command": windows_receipt["binder_command"],
            "caller_is_non_repository": windows_receipt[
                "caller_is_non_repository"
            ],
            "predecessor_workflow_successor_scope": True,
            "control_roles": 3,
            "generator_cases": 108,
            "expected_empirical_observations": 648,
            "actual_executable_control_identities": "UNBOUND",
        },
        "authority": {
            "provider_or_model_calls": 0,
            "empirical_subject_execution": False,
            "empirical_calibration": "NOT_RUN",
            "numeric_stage2_freeze": "NOT_ISSUED",
            "callable_astra_identity": "UNBOUND",
            "live_provider_dispatch": "PROHIBITED",
            "optional_24_call_block": "DISABLED",
            "benchmark_verdict_authority": "NONE",
            "merge_authority": "NONE",
        },
        "attacks": attacks,
        "attack_count": len(attacks),
        "refused_count": sum(1 for attack in attacks if attack["passed"]),
        "failed_count": len(failed),
        "disposition": (
            "PASS_SUCCESSOR_SCOPE_AND_BINDER_IMPORT_PROVIDER_FREE_RELEASE_ONLY"
            if not failed
            else "FAIL"
        ),
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--evidence-zip", required=True, type=Path)
    parser.add_argument("--publication-zip", required=True, type=Path)
    parser.add_argument("--windows-audit-receipt", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args()

    result = execute(
        arguments.repo_root,
        arguments.evidence_zip,
        arguments.publication_zip,
        arguments.windows_audit_receipt,
    )
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
