#!/usr/bin/env python3
"""Independent audit of the final Astra Stage 2 named-wrapper release."""
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
PARENT_HEAD = "606b61fe56af318a459b7910331082499e432cfb"
PARENT_TREE = "e1e4e7938114f74c67d22f7b9ac33ce82992ec7c"
RELEASE_HEAD = "b3534c9703723ac35343af0209edc34c7587173c"
RELEASE_TREE = "15f64f02f5dfc6b1e5e59634205dc7d157d9c125"
RELEASE_RUN = 33808501099
EVIDENCE_ID = 9913884841
PUBLICATION_ID = 9913885509
EVIDENCE_SHA = "b204099127a49c91445ae206aa462ea18cbb8e666ad0662a487a23701d364949"
PUBLICATION_SHA = "ee526047e3b06617ac74c3a862d68c8d79f644aa387538faa7de25a978dd8afd"
QUALIFICATION_SHA = "66f7628751cdfbdaff55909016a18416badee4b798d422178195a8855359661f"
PUBLICATION_PAYLOAD = "df64729a7d22a8e37955c82c0b71cdc8c99af61a88e573d0ac794b673c2908fc"
WINDOWS_RELEASE_RECEIPT = "35e90165c3cdb10d95ecabcd63f4ba2ac85d4a68849b2413d3ba3f2c99561f73"
LAUNCHER_SHA = "3ff10be5f30971c14139b13320d9758da2ea54839152b14fa2e8ac558d509fbb"
PREDECESSOR_SHA = "36497dd0720fc58114bb5c49723fbe0fc486ffa71b7ee1562d4594a41375ebc7"
TEMPLATE_SHA = "0292bf17538352f2c27799254bf951418fa517c1ff81f26223c736ea5e89900d"

RELEASE_PATHS = {
    ".github/workflows/astra-stage2-control-identity-release.yml",
    ".github/workflows/astra-stage2-control-identity.yml",
    "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
    "tests/test_astra_stage2_control_identity.py",
    "tests/test_astra_stage2_control_identity_release.py",
}
DELTA_PATHS = {
    "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
    "tests/test_astra_stage2_control_identity_release.py",
}
AUDIT_PATHS = {
    ".github/workflows/astra-stage2-control-identity-named-wrapper-audit.yml",
    "audits/astra_stage2_control_identity_named_wrapper_release_audit.py",
}
EVIDENCE_MEMBERS = {
    "Invoke-AstraStage2ControlIdentityBinding.ps1", "README.md", "SHA256SUMS",
    "astra_stage2_bind_controls.ps1", "astra_stage2_bind_controls.py",
    "binding-template.json", "predecessor-control-identity-workflow.yml",
    "qualification-receipt.json", "release-paths.z",
    "test-control-identity-linux.log",
}
PROVIDER_ENV = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "MISTRAL_API_KEY", "COHERE_API_KEY", "XAI_API_KEY", "GROQ_API_KEY",
    "TOGETHER_API_KEY", "FIREWORKS_API_KEY",
}


def must(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def git(root: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False,
    )
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    ).returncode == 0


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def payload(value: dict[str, Any]) -> str:
    return sha256_object({k: v for k, v in value.items() if k != "payload_sha256"})


def extract(path: Path, root: Path) -> set[str]:
    root.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    with zipfile.ZipFile(path) as z:
        must(z.testzip() is None, f"CRC failure in {path.name}")
        for info in z.infolist():
            member = Path(info.filename)
            must(not member.is_absolute() and ".." not in member.parts, "unsafe ZIP member")
            target = (root / member).resolve()
            target.relative_to(root.resolve())
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
            names.add(info.filename)
    return names


def verify_sums(root: Path) -> None:
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split(maxsplit=1)
        target = root / name.removeprefix("./")
        must(target.is_file() and sha(target) == expected, f"SHA256SUMS mismatch: {name}")


def assert_scope(text: str) -> None:
    must(
        "  pull_request:\n    branches:\n      - joint/astra-stage2-calibration-impl-20260902\n    paths:\n" in text,
        "predecessor PR-base scope absent",
    )
    must(
        "  push:\n    branches:\n      - joint/astra-stage2-control-identities-20260903\n" in text,
        "predecessor push lane absent",
    )


def assert_launcher(text: str) -> None:
    block = text.split("function Invoke-PinnedBinder {", 1)[1].split(
        "function Get-LauncherCoordinates", 1
    )[0]
    for marker in (
        "[Parameter(Mandatory = $true)][hashtable]$Parameters",
        "& $Wrapper @Parameters", "$env:PYTHONPATH = $expectedRoot",
        "Push-Location -LiteralPath $expectedRoot", "Remove-Item Env:PYTHONPATH",
    ):
        must(marker in block, f"named-wrapper marker absent: {marker}")
    must("@Arguments" not in block and "[string[]]$Arguments" not in block,
         "positional wrapper boundary remains")
    must(not re.search(r"Invoke-PinnedBinder[^\n]*-Arguments", text),
         "positional wrapper call remains")
    must(text.count("-Parameters @{") >= 7, "named-wrapper denominator below seven")
    for command in ("template", "probe-hardware", "inventory", "validate-config", "bind", "verify"):
        must(f"Command = '{command}'" in text, f"named command absent: {command}")
    for marker in (
        "preflight-binder-import-smoke", "non-binder-cwd",
        "binder_import_smoke = 'PASS'", "binder_execution_cwd = 'PINNED_BINDER_ROOT'",
        "binder_pythonpath = 'PINNED_BINDER_ROOT'",
        "binder_caller_cwd = 'DELIBERATELY_NON_BINDER'",
        "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND",
        "actual_executable_control_identities = 'UNBOUND'",
    ):
        must(marker in text, f"launcher authority marker absent: {marker}")


def refusal(label: str, action: Callable[[], Any], rows: list[dict[str, Any]]) -> None:
    try:
        action()
    except Stage2Error as exc:
        rows.append({"label": label, "passed": True, "detail": str(exc)})
    else:
        rows.append({"label": label, "passed": False, "detail": "ACCEPTED"})


def validate_windows(value: dict[str, Any]) -> None:
    expected = {
        "schema": "tier-bench/astra-stage2-control-identity-named-wrapper-windows-audit@1",
        "release_head_sha1": RELEASE_HEAD, "release_tree_sha1": RELEASE_TREE,
        "runner": "windows-2025", "tests": 27, "passed": 26, "skipped": 1,
        "failed": 0, "errors": 0, "powershell_parse": "PASS",
        "launcher_preflight": "PASS",
        "preflight_schema": "tier-bench/astra-stage2-control-identity-preflight@2",
        "preflight_release_head_sha1": RELEASE_HEAD,
        "preflight_release_tree_sha1": RELEASE_TREE,
        "binder_import_smoke": "PASS", "binder_execution_cwd": "PINNED_BINDER_ROOT",
        "binder_pythonpath": "PINNED_BINDER_ROOT",
        "binder_caller_cwd": "DELIBERATELY_NON_BINDER",
        "named_wrapper_parameters": "PASS",
        "predecessor_workflow_successor_scope": "PASS",
        "preflight_downloads": 0, "model_calls": 0, "provider_calls": 0,
        "actual_executable_control_identities": "UNBOUND",
        "binder_template_sha256": TEMPLATE_SHA,
    }
    for key, expected_value in expected.items():
        must(value.get(key) == expected_value, f"Windows receipt mismatch: {key}")
    for key in ("test_log_sha256", "preflight_receipt_sha256"):
        must(bool(re.fullmatch(r"[0-9a-f]{64}", str(value.get(key, "")))), f"Windows receipt lacks {key}")


def execute(repo: Path, release: Path, evidence_zip: Path, publication_zip: Path,
            windows_receipt_path: Path) -> dict[str, Any]:
    repo, release = repo.resolve(), release.resolve()
    audit_head, audit_tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    must(git(repo, "rev-parse", f"{BINDER_HEAD}^{{tree}}") == BINDER_TREE, "binder tree drift")
    must(git(repo, "rev-parse", f"{PARENT_HEAD}^{{tree}}") == PARENT_TREE, "parent tree drift")
    must(git(repo, "rev-parse", f"{RELEASE_HEAD}^{{tree}}") == RELEASE_TREE, "release tree drift")
    must(git(repo, "rev-parse", f"{RELEASE_HEAD}^") == PARENT_HEAD, "release parent drift")
    must(git_ok(repo, "merge-base", "--is-ancestor", BINDER_HEAD, RELEASE_HEAD), "release ancestry failure")
    must(git_ok(repo, "merge-base", "--is-ancestor", RELEASE_HEAD, audit_head), "audit ancestry failure")
    must(git(release, "rev-parse", "HEAD") == RELEASE_HEAD, "release worktree head drift")
    must(git(release, "rev-parse", "HEAD^{tree}") == RELEASE_TREE, "release worktree tree drift")
    must(not git(release, "status", "--porcelain"), "release worktree dirty")
    must(not git(repo, "status", "--porcelain"), "audit checkout dirty")

    pathset = lambda a, b: {x for x in git(repo, "diff", "--name-only", f"{a}...{b}").splitlines() if x}
    must(pathset(BINDER_HEAD, RELEASE_HEAD) == RELEASE_PATHS, "release path denominator drift")
    must(pathset(PARENT_HEAD, RELEASE_HEAD) == DELTA_PATHS, "named-wrapper delta drift")
    must(pathset(RELEASE_HEAD, audit_head) == AUDIT_PATHS, "audit path denominator drift")
    must(not [k for k in PROVIDER_ENV if os.environ.get(k)], "provider credentials present")

    launcher_path = release / "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1"
    predecessor_path = release / ".github/workflows/astra-stage2-control-identity.yml"
    must(launcher_path.stat().st_size == 27332 and sha(launcher_path) == LAUNCHER_SHA,
         "launcher identity drift")
    must(predecessor_path.stat().st_size == 17406 and sha(predecessor_path) == PREDECESSOR_SHA,
         "predecessor workflow identity drift")
    assert_launcher(launcher_path.read_text(encoding="utf-8"))
    assert_scope(predecessor_path.read_text(encoding="utf-8"))

    release_workflow = (release / ".github/workflows/astra-stage2-control-identity-release.yml").read_text(encoding="utf-8")
    for marker in ('".github/workflows/astra-stage2-control-identity.yml"',
                   "predecessor-control-identity-workflow.yml",
                   '"predecessor_workflow_successor_scope": True'):
        must(marker in release_workflow, f"release workflow evidence absent: {marker}")

    release_test = (release / "tests/test_astra_stage2_control_identity_release.py").read_text(encoding="utf-8")
    for marker in ("test_26_preflight_proves_named_wrapper_import_from_non_binder_cwd",
                   "[Parameter(Mandatory = $true)][hashtable]$Parameters",
                   "& $Wrapper @Parameters",
                   "test_27_bind_refuses_unbound_runtime_and_uses_named_wrapper_parameters"):
        must(marker in release_test, f"release test control absent: {marker}")

    must(sha(evidence_zip) == EVIDENCE_SHA, "release evidence ZIP drift")
    must(sha(publication_zip) == PUBLICATION_SHA, "release publication ZIP drift")
    windows = strict_json_load(windows_receipt_path)
    validate_windows(windows)

    with tempfile.TemporaryDirectory(prefix="astra-named-wrapper-audit-") as temp:
        eroot, proot = Path(temp) / "evidence", Path(temp) / "publication"
        must(extract(evidence_zip, eroot) == EVIDENCE_MEMBERS, "release evidence member drift")
        must(extract(publication_zip, proot) == {"publication-index.json"}, "publication member drift")
        verify_sums(eroot)
        q = strict_json_load(eroot / "qualification-receipt.json")
        p = strict_json_load(proot / "publication-index.json")
        must(q.get("payload_sha256") == QUALIFICATION_SHA == payload(q), "qualification payload drift")
        must(p.get("payload_sha256") == PUBLICATION_PAYLOAD == payload(p), "publication payload drift")
        must(q.get("run_id") == RELEASE_RUN, "qualification run drift")
        must(q.get("source", {}).get("head_sha1") == RELEASE_HEAD and
             q.get("source", {}).get("tree_sha1") == RELEASE_TREE, "qualification source drift")
        c = q.get("conformance", {})
        must(c.get("tests") == c.get("windows_tests") == c.get("linux_tests") == 27,
             "qualification test denominator drift")
        must(c.get("windows_receipt_sha256") == WINDOWS_RELEASE_RECEIPT and
             c.get("predecessor_workflow_successor_scope") is True, "qualification scope drift")
        must(q.get("actual_binding", {}).get("state") == "UNBOUND" and
             q.get("authority", {}).get("provider_or_model_calls") == 0, "qualification authority drift")
        files = q.get("files", {})
        must(files.get("Invoke-AstraStage2ControlIdentityBinding.ps1") ==
             {"bytes": 27332, "sha256": LAUNCHER_SHA}, "retained launcher ledger drift")
        must(files.get("predecessor-control-identity-workflow.yml") ==
             {"bytes": 17406, "sha256": PREDECESSOR_SHA}, "retained workflow ledger drift")
        must(files.get("binding-template.json") ==
             {"bytes": 6605, "sha256": TEMPLATE_SHA}, "retained template ledger drift")
        must((eroot / "Invoke-AstraStage2ControlIdentityBinding.ps1").read_bytes() == launcher_path.read_bytes(),
             "retained launcher byte drift")
        must((eroot / "predecessor-control-identity-workflow.yml").read_bytes() == predecessor_path.read_bytes(),
             "retained workflow byte drift")
        retained_paths = {x.decode() for x in (eroot / "release-paths.z").read_bytes().split(b"\0") if x}
        must(retained_paths == RELEASE_PATHS, "retained release path drift")
        must(re.search(r"(?m)^Ran 27 tests in ", (eroot / "test-control-identity-linux.log").read_text()),
             "retained Linux test denominator absent")
        must(p.get("workflow_run_id") == RELEASE_RUN and p.get("source_head_sha1") == RELEASE_HEAD and
             p.get("source_tree_sha1") == RELEASE_TREE, "publication coordinate drift")
        must(p.get("qualification_payload_sha256") == QUALIFICATION_SHA and
             p.get("windows_receipt_sha256") == WINDOWS_RELEASE_RECEIPT, "publication binding drift")
        must(p.get("evidence_artifact") == {"id": EVIDENCE_ID, "sha256": EVIDENCE_SHA},
             "publication artifact binding drift")
        must(p.get("predecessor_workflow_successor_scope") is True and
             p.get("actual_control_identities") == "UNBOUND" and
             p.get("provider_or_model_calls") == 0 and p.get("merge_authority") == "NONE",
             "publication authority drift")

    attacks: list[dict[str, Any]] = []
    base = binding_template()
    cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        ("unknown binding-root property", lambda x: x.__setitem__("notes", "PRIVATE_CANARY")),
        ("law blob substitution", lambda x: x["law"].__setitem__("blob_sha1", "0" * 40)),
        ("source repository substitution", lambda x: x["controls"][0].__setitem__("source_repository", "attacker/repo")),
        ("checkpoint revision substitution", lambda x: x["controls"][0].__setitem__("checkpoint_revision_sha1", "1" * 40)),
        ("control ordering substitution", lambda x: x["controls"].reverse()),
        ("missing selected hardware", lambda x: x["controls"][0]["hardware"].__setitem__("selected_device_indices", [])),
        ("aliased effort mappings", lambda x: x["controls"][0]["effort_mapping"].__setitem__(
            "high", copy.deepcopy(x["controls"][0]["effort_mapping"]["low"]))),
    ]
    for label, mutate in cases:
        candidate = copy.deepcopy(base)
        mutate(candidate)
        refusal(label, lambda candidate=candidate: validate_binding_config(candidate), attacks)
    failed = [x for x in attacks if not x["passed"]]

    receipt: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-named-wrapper-release-audit@1",
        "target": {
            "pull_request": 187, "binder_head_sha1": BINDER_HEAD,
            "named_wrapper_parent_head_sha1": PARENT_HEAD,
            "release_head_sha1": RELEASE_HEAD, "release_tree_sha1": RELEASE_TREE,
            "release_run": RELEASE_RUN, "evidence_artifact_id": EVIDENCE_ID,
            "publication_artifact_id": PUBLICATION_ID,
        },
        "audit": {
            "head_sha1": audit_head, "tree_sha1": audit_tree,
            "audit_paths": sorted(AUDIT_PATHS), "release_paths": sorted(RELEASE_PATHS),
            "named_wrapper_delta_paths": sorted(DELTA_PATHS),
        },
        "artifacts": {
            "release_evidence_zip_sha256": EVIDENCE_SHA,
            "release_publication_zip_sha256": PUBLICATION_SHA,
            "qualification_payload_sha256": QUALIFICATION_SHA,
            "publication_payload_sha256": PUBLICATION_PAYLOAD,
            "release_windows_receipt_sha256": WINDOWS_RELEASE_RECEIPT,
            "independent_windows_receipt_sha256": sha(windows_receipt_path),
            "independent_preflight_receipt_sha256": windows["preflight_receipt_sha256"],
            "independent_binder_template_sha256": windows["binder_template_sha256"],
            "launcher_sha256": LAUNCHER_SHA, "predecessor_workflow_sha256": PREDECESSOR_SHA,
        },
        "rederived": {
            "tests_linux": 27, "tests_windows": windows["tests"],
            "windows_passed": windows["passed"], "windows_skipped": windows["skipped"],
            "windows_failed": windows["failed"], "windows_errors": windows["errors"],
            "powershell_parse": windows["powershell_parse"],
            "preflight_schema": windows["preflight_schema"],
            "preflight_release_head_sha1": windows["preflight_release_head_sha1"],
            "preflight_release_tree_sha1": windows["preflight_release_tree_sha1"],
            "binder_import_smoke": windows["binder_import_smoke"],
            "binder_execution_cwd": windows["binder_execution_cwd"],
            "binder_pythonpath": windows["binder_pythonpath"],
            "binder_caller_cwd": windows["binder_caller_cwd"],
            "named_wrapper_parameters": windows["named_wrapper_parameters"],
            "predecessor_workflow_successor_scope": True,
            "control_roles": 3, "generator_cases": 108,
            "expected_empirical_observations": 648,
            "actual_executable_control_identities": "UNBOUND",
        },
        "authority": {
            "provider_or_model_calls": 0, "empirical_subject_execution": False,
            "empirical_calibration": "NOT_RUN", "numeric_stage2_freeze": "NOT_ISSUED",
            "callable_astra_identity": "UNBOUND", "live_provider_dispatch": "PROHIBITED",
            "optional_24_call_block": "DISABLED", "benchmark_verdict_authority": "NONE",
            "merge_authority": "NONE",
        },
        "attacks": attacks, "attack_count": len(attacks),
        "refused_count": sum(1 for x in attacks if x["passed"]),
        "failed_count": len(failed),
        "disposition": "PASS_NAMED_WRAPPER_BINDER_IMPORT_PROVIDER_FREE_RELEASE_ONLY" if not failed else "FAIL",
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--evidence-zip", required=True, type=Path)
    parser.add_argument("--publication-zip", required=True, type=Path)
    parser.add_argument("--windows-audit-receipt", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    value = execute(args.repo_root, args.release_root, args.evidence_zip,
                    args.publication_zip, args.windows_audit_receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, sort_keys=True, indent=2))
    return 0 if value["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
