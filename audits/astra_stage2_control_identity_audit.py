#!/usr/bin/env python3
"""Independent provider-free audit of the Astra Stage 2 control-identity binder."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from astra_stage2.canonical import Stage2Error, sha256_bytes, sha256_object, strict_json_load
from astra_stage2.control_identity import (
    GENERATOR_MANIFEST_SHA256,
    LAW_BLOB_SHA1,
    LAW_COMMIT_SHA1,
    LAW_TREE_SHA1,
    PUBLIC_CONTROLS,
    SCAFFOLD_HEAD_SHA1,
    SCAFFOLD_TREE_SHA1,
    STAGE1_JOIN_HEAD_SHA1,
    _assert_public_safe,
    bind_control_set,
    binding_template,
    validate_binding_config,
    verify_control_set,
    verify_repository_coordinates,
)

TARGET_HEAD = "af03cef494a509ab7ba5df29fa4b4ccba423f1f8"
TARGET_TREE = "519ea2f8f448a464e817a024ad8ed1ac64493931"
JOIN_HEAD = "f6b24be2a2c411444f0d4005aed3bd61769733a5"
SCAFFOLD_HEAD = "9babad4631ef517485c56ea4906aab123e30fad7"
LAW_HEAD = "c36c35bf9b70d879e1e1c9ee2f0296879442df3e"
EVIDENCE_ARTIFACT_ID = 9897560563
PUBLICATION_ARTIFACT_ID = 9897561198
EVIDENCE_ZIP_SHA256 = "22d8db55e440f7911b6960eafca311d539fe4d272bf802056db32b74987add15"
PUBLICATION_ZIP_SHA256 = "aeef4e8d1b39f98258dea86f7a67ca1b7318bb5c1ef1a7e384aaaf4da0fd2044"
QUALIFICATION_PAYLOAD = "ebfdb00e10e245ddeaccac2a4cc3ca590b22beec9f0289bd050a2b898eaad47f"
PUBLICATION_PAYLOAD = "1051da7dd346f979a5ac1ad99b291afe82f02bea0e40e353406b989767174baf"
EXPECTED_TARGET_PATHS = {
    ".github/workflows/astra-stage2-control-identity.yml",
    "astra_stage2/control_identity.py",
    "docs/agents/claims/FRR-ASTRA-STAGE2-1.md",
    "docs/agents/claims/FRR-ASTRA-STAGE2-CONTROL-IDENTITY-1.md",
    "experiments/astra_kxr/stage2/control_identity/README.md",
    "experiments/astra_kxr/stage2/control_identity/binding-template.json",
    "schemas/astra-stage2-control-binding-input.schema.json",
    "schemas/astra-stage2-executable-control-private.schema.json",
    "schemas/astra-stage2-executable-control-public.schema.json",
    "schemas/astra-stage2-executable-control-set.schema.json",
    "scripts/astra_stage2_bind_controls.ps1",
    "scripts/astra_stage2_bind_controls.py",
    "tests/test_astra_stage2_control_identity.py",
}
EXPECTED_AUDIT_PATHS = {
    ".github/workflows/astra-stage2-control-identity-audit.yml",
    "audits/astra_stage2_control_identity_audit.py",
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


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or str(proc.returncode)
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


def _git_success(repo_root: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
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
    return sha256_object({key: child for key, child in value.items() if key != "payload_sha256"})


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
                raise RuntimeError(f"unsafe ZIP member {info.filename}")
            target = (destination / member).resolve()
            target.relative_to(root)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            data = archive.read(info)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            members[info.filename] = {"bytes": len(data), "sha256": sha256_bytes(data)}
    return members


def _expect_refusal(label: str, action: Callable[[], Any], attacks: list[dict[str, Any]]) -> None:
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
            "detail": "mutation was admitted",
        }
    )


def _source_manifest(root: Path, repository: str, commit: str) -> dict[str, Any]:
    entry = {"name": "source.py", "bytes": 7, "sha256": sha256_bytes(b"source\n")}
    return {
        "repository": repository,
        "commit_sha1": commit,
        "tree_sha1": "a" * 40,
        "origin_sha256": sha256_bytes(repository.encode("utf-8")),
        "file_count": 1,
        "total_bytes": 7,
        "files": [entry],
        "content_manifest_sha256": sha256_object([entry]),
    }


def _repository_coordinates() -> dict[str, Any]:
    return {
        "repository_root": "/private/audit/repository",
        "head_sha1": TARGET_HEAD,
        "tree_sha1": TARGET_TREE,
        "law_blob_sha1": LAW_BLOB_SHA1,
        "implementation_blobs": {},
        "generator_manifest_sha256": GENERATOR_MANIFEST_SHA256,
    }


def _build_synthetic_config(root: Path) -> dict[str, Any]:
    config = binding_template()
    config["binding_id"] = "astra-stage2-control-identity-audit"
    for index, control in enumerate(config["controls"]):
        source_root = root / "source" / control["role"]
        source_root.mkdir(parents=True)
        control["source_root"] = str(source_root)

        revision = control["checkpoint_revision_sha1"]
        model_root = root / "models" / revision
        model_root.mkdir(parents=True)
        (model_root / "config.json").write_text(
            json.dumps({"role": control["role"], "canary": "PRIVATE_TRANSCRIPT_CANARY"}),
            encoding="utf-8",
        )
        (model_root / "tokenizer.json").write_text(
            json.dumps({"tokenizer": control["role"]}), encoding="utf-8"
        )
        (model_root / "model-00001-of-00002.safetensors").write_bytes(
            f"arbitrary-a-{control['role']}".encode("utf-8")
        )
        (model_root / "model-00002-of-00002.safetensors").write_bytes(
            f"arbitrary-b-{control['role']}".encode("utf-8")
        )
        index_value = {
            "metadata": {"total_size": 2},
            "weight_map": {
                "a": "model-00001-of-00002.safetensors",
                "b": "model-00002-of-00002.safetensors",
            },
        }
        (model_root / "model.safetensors.index.json").write_text(
            json.dumps(index_value), encoding="utf-8"
        )
        control["model_root"] = str(model_root)
        control["model_config_paths"] = ["config.json"]
        control["tokenizer_paths"] = ["tokenizer.json"]
        control["weight_index_path"] = "model.safetensors.index.json"
        control["weight_paths"] = [
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
        ]

        runtime_root = root / "runtime" / control["role"]
        runtime_root.mkdir(parents=True)
        executable = runtime_root / "runtime-probe.py"
        executable.write_text(
            "#!/usr/bin/env python3\nprint('AuditRuntime 1.0 exact-build')\n",
            encoding="utf-8",
        )
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        (runtime_root / "runtime.json").write_text(
            json.dumps({"deterministic": True}), encoding="utf-8"
        )
        control["runtime"] = {
            "root": str(runtime_root),
            "name": "AuditRuntime",
            "version": "1.0",
            "build": "exact-build",
            "executable_path": "runtime-probe.py",
            "configuration_paths": ["runtime.json"],
            "configuration": {"deterministic": True},
            "probe_args": [],
            "required_probe_substrings": ["AuditRuntime", "1.0", "exact-build"],
            "probe_timeout_seconds": 30,
        }

        hardware_root = root / "hardware" / control["role"]
        hardware_root.mkdir(parents=True)
        (hardware_root / "platform.json").write_text(
            json.dumps({"system": "SyntheticAudit", "role": control["role"]}),
            encoding="utf-8",
        )
        (hardware_root / "nvidia-query.csv").write_text(
            f"{index}, Synthetic GPU {index}, PRIVATE-GPU-{index}, 0000:0{index}:00.0, 24576, 999.0\n",
            encoding="utf-8",
        )
        (hardware_root / "nvidia-topology.txt").write_text(
            f"GPU{index} X\n", encoding="utf-8"
        )
        control["hardware"] = {
            "evidence_root": str(hardware_root),
            "platform_path": "platform.json",
            "device_query_path": "nvidia-query.csv",
            "topology_path": "nvidia-topology.txt",
            "selected_device_indices": [index],
        }
        control["effort_mapping"] = {
            "low": {
                "arguments": ["--effort", "low"],
                "environment": {},
                "configuration": {"steps": 1},
            },
            "high": {
                "arguments": ["--effort", "high"],
                "environment": {},
                "configuration": {"steps": 2},
            },
        }
    return config


def _bind(config: dict[str, Any], repo_root: Path, output_dir: Path) -> dict[str, Any]:
    with patch(
        "astra_stage2.control_identity.verify_repository_coordinates",
        return_value=_repository_coordinates(),
    ), patch(
        "astra_stage2.control_identity._tracked_source_manifest",
        side_effect=_source_manifest,
    ):
        return bind_control_set(copy.deepcopy(config), repo_root=repo_root, output_dir=output_dir)


def _verify(config: dict[str, Any], repo_root: Path, output_dir: Path) -> dict[str, Any]:
    with patch(
        "astra_stage2.control_identity.verify_repository_coordinates",
        return_value=_repository_coordinates(),
    ), patch(
        "astra_stage2.control_identity._tracked_source_manifest",
        side_effect=_source_manifest,
    ):
        return verify_control_set(copy.deepcopy(config), repo_root=repo_root, output_dir=output_dir)


def execute(repo_root: Path, evidence_zip: Path, publication_zip: Path) -> dict[str, Any]:
    audit_head = _git(repo_root, "rev-parse", "HEAD")
    audit_tree = _git(repo_root, "rev-parse", "HEAD^{tree}")
    if _git(repo_root, "rev-parse", f"{TARGET_HEAD}^{{tree}}") != TARGET_TREE:
        raise RuntimeError("target tree differs from the frozen audit coordinate")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", TARGET_HEAD, audit_head):
        raise RuntimeError("audit branch is not descended from the exact target")
    if _git(repo_root, "rev-list", "--parents", "-n", "1", JOIN_HEAD) != (
        f"{JOIN_HEAD} {SCAFFOLD_HEAD} {LAW_HEAD}"
    ):
        raise RuntimeError("law/scaffold join parent order differs")
    if _git(repo_root, "rev-parse", f"{TARGET_HEAD}:docs/agents/claims/FRR-ASTRA-STAGE2-1.md") != LAW_BLOB_SHA1:
        raise RuntimeError("target law blob differs")
    target_paths = {
        item
        for item in _git(repo_root, "diff", "--name-only", f"{SCAFFOLD_HEAD}...{TARGET_HEAD}").splitlines()
        if item
    }
    audit_paths = {
        item
        for item in _git(repo_root, "diff", "--name-only", f"{TARGET_HEAD}...{audit_head}").splitlines()
        if item
    }
    if target_paths != EXPECTED_TARGET_PATHS:
        raise RuntimeError(f"target path set mismatch: {sorted(target_paths)}")
    if audit_paths != EXPECTED_AUDIT_PATHS:
        raise RuntimeError(f"audit path set mismatch: {sorted(audit_paths)}")
    if _git(repo_root, "status", "--porcelain"):
        raise RuntimeError("audit checkout is not clean")

    provider_credentials = sorted(name for name in RECOGNIZED_PROVIDER_ENV if os.environ.get(name))
    if provider_credentials:
        raise RuntimeError("recognized provider credentials are present")

    if _sha256_file(evidence_zip) != EVIDENCE_ZIP_SHA256:
        raise RuntimeError("evidence ZIP digest mismatch")
    if _sha256_file(publication_zip) != PUBLICATION_ZIP_SHA256:
        raise RuntimeError("publication ZIP digest mismatch")

    with tempfile.TemporaryDirectory(prefix="astra-control-id-artifacts-") as artifact_temp:
        artifact_root = Path(artifact_temp)
        evidence_members = _safe_extract(evidence_zip, artifact_root / "evidence")
        publication_members = _safe_extract(publication_zip, artifact_root / "publication")
        qualification = strict_json_load(artifact_root / "evidence" / "qualification-receipt.json")
        publication = strict_json_load(artifact_root / "publication" / "publication-index.json")
        if qualification["payload_sha256"] != QUALIFICATION_PAYLOAD or _payload_hash(qualification) != QUALIFICATION_PAYLOAD:
            raise RuntimeError("qualification payload does not reproduce")
        if publication["payload_sha256"] != PUBLICATION_PAYLOAD or _payload_hash(publication) != PUBLICATION_PAYLOAD:
            raise RuntimeError("publication payload does not reproduce")
        sums = (artifact_root / "evidence" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        for line in sums:
            digest, relative = line.split("  ", 1)
            candidate = artifact_root / "evidence" / relative
            if _sha256_file(candidate) != digest:
                raise RuntimeError(f"evidence member digest mismatch for {relative}")
        if qualification["source"]["head_sha1"] != TARGET_HEAD or qualification["source"]["tree_sha1"] != TARGET_TREE:
            raise RuntimeError("qualification is not bound to the exact target")
        if qualification["conformance"] != {
            "control_roles": 3,
            "exact_repository_coordinates_verified": True,
            "expected_empirical_observations": 648,
            "generator_cases": 108,
            "local_byte_drift_refusal_tested": True,
            "private_path_and_canary_refusal_tested": True,
            "template_reproduces": True,
            "tests": 20,
        }:
            raise RuntimeError("qualification conformance ledger differs")
        if qualification["actual_binding"] != {
            "bound_controls": 0,
            "empirical_observations": 0,
            "local_hardware_receipts_seen": 0,
            "local_model_bytes_seen": 0,
            "local_runtime_bytes_seen": 0,
            "state": "UNBOUND",
        }:
            raise RuntimeError("qualification widened actual-binding authority")
        if publication["evidence_artifact"] != {
            "id": EVIDENCE_ARTIFACT_ID,
            "sha256": EVIDENCE_ZIP_SHA256,
        }:
            raise RuntimeError("publication does not bind the evidence artifact")
        if publication["actual_control_identities"] != "UNBOUND":
            raise RuntimeError("publication claims physical identities")

    repository_coordinates = verify_repository_coordinates(repo_root)
    if repository_coordinates["law_blob_sha1"] != LAW_BLOB_SHA1:
        raise RuntimeError("repository coordinate verifier returned another law blob")

    attacks: list[dict[str, Any]] = []
    template = binding_template()
    validate_binding_config(template, permit_inventory_gaps=True)

    mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        ("unknown binding property", lambda value: value.__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown law property", lambda value: value["law"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown scaffold property", lambda value: value["scaffold"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown runtime property", lambda value: value["controls"][0]["runtime"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown adapter property", lambda value: value["controls"][0]["adapter"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown quantization property", lambda value: value["controls"][0]["quantization"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown hardware property", lambda value: value["controls"][0]["hardware"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("unknown effort property", lambda value: value["controls"][0]["effort_mapping"]["low"].__setitem__("notes", "PRIVATE_TRANSCRIPT_CANARY")),
        ("law commit substitution", lambda value: value["law"].__setitem__("commit_sha1", "0" * 40)),
        ("law tree substitution", lambda value: value["law"].__setitem__("tree_sha1", "0" * 40)),
        ("law blob substitution", lambda value: value["law"].__setitem__("blob_sha1", "0" * 40)),
        ("scaffold head substitution", lambda value: value["scaffold"].__setitem__("head_sha1", "0" * 40)),
        ("scaffold tree substitution", lambda value: value["scaffold"].__setitem__("tree_sha1", "0" * 40)),
        ("Stage 1 join substitution", lambda value: value.__setitem__("stage1_join_head", "0" * 40)),
        ("generator digest substitution", lambda value: value.__setitem__("generator_manifest_sha256", "0" * 64)),
        ("source repository substitution", lambda value: value["controls"][0].__setitem__("source_repository", "attacker/repo")),
        ("source commit substitution", lambda value: value["controls"][0].__setitem__("source_commit_sha1", "0" * 40)),
        ("checkpoint repository substitution", lambda value: value["controls"][0].__setitem__("checkpoint_repository", "attacker/checkpoint")),
        ("checkpoint revision substitution", lambda value: value["controls"][0].__setitem__("checkpoint_revision_sha1", "0" * 40)),
        ("forbidden prompt-bearing configuration", lambda value: value["controls"][0]["runtime"]["configuration"].__setitem__("prompt", "PRIVATE_TRANSCRIPT_CANARY")),
    ]
    for label, mutation in mutations:
        altered = copy.deepcopy(template)
        mutation(altered)
        _expect_refusal(
            label,
            lambda altered=altered: validate_binding_config(altered, permit_inventory_gaps=True),
            attacks,
        )

    missing = copy.deepcopy(template)
    missing["controls"].pop()
    _expect_refusal(
        "incomplete three-control set",
        lambda: validate_binding_config(missing, permit_inventory_gaps=True),
        attacks,
    )
    swapped = copy.deepcopy(template)
    swapped["controls"][0], swapped["controls"][1] = swapped["controls"][1], swapped["controls"][0]
    _expect_refusal(
        "control role-order substitution",
        lambda: validate_binding_config(swapped, permit_inventory_gaps=True),
        attacks,
    )
    _expect_refusal(
        "public private-root injection",
        lambda: _assert_public_safe({"value": "/private/audit/model"}, ["/private/audit"]),
        attacks,
    )

    synthetic_findings: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="astra-control-id-bind-") as temporary:
        root = Path(temporary)
        config = _build_synthetic_config(root)
        output = root / "bound"
        public_set = _bind(config, repo_root, output)
        if public_set["binding_status"] != "BOUND_EXECUTABLE_IDENTITIES":
            raise RuntimeError("synthetic binder did not reach its expected boundary")
        if public_set["control_count"] != 3 or public_set["observation_count"] != 648:
            raise RuntimeError("synthetic binder denominator differs")
        public_bytes = b"".join(
            path.read_bytes() for path in sorted((output / "public").glob("*.json"))
        )
        private_roots = [str(root).encode("utf-8"), b"PRIVATE_TRANSCRIPT_CANARY", b"PRIVATE-GPU-"]
        if any(canary in public_bytes for canary in private_roots):
            raise RuntimeError("public receipts retain a private root or canary")
        _verify(config, repo_root, output)

        model_config = Path(config["controls"][0]["model_root"]) / "config.json"
        model_config.write_text('{"changed":true}', encoding="utf-8")
        _expect_refusal(
            "post-binding local byte drift",
            lambda: _verify(config, repo_root, output),
            attacks,
        )

        synthetic_findings.append(
            {
                "label": "checkpoint revision provenance",
                "expected": "REFUSAL_WITHOUT_UPSTREAM_CONTENT_RECEIPT",
                "observed": "BOUND_EXECUTABLE_IDENTITIES",
                "passed": False,
                "detail": (
                    "arbitrary checkpoint bytes were admitted solely because the local directory name "
                    "equaled the released revision; no upstream file manifest, ETag/LFS identity, or "
                    "download receipt bound those bytes to the claimed immutable revision"
                ),
            }
        )

    attacks.extend(synthetic_findings)
    failed = [item for item in attacks if not item["passed"]]
    disposition = (
        "PASS_PROVIDER_FREE_BINDER_ONLY"
        if not failed
        else "CHANGES_REQUESTED_BEFORE_ACTUAL_IDENTITY_BINDING"
    )
    receipt: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-audit@1",
        "target": {
            "pull_request": 186,
            "head_sha1": TARGET_HEAD,
            "tree_sha1": TARGET_TREE,
            "join_head_sha1": JOIN_HEAD,
            "scaffold_head_sha1": SCAFFOLD_HEAD,
            "law_head_sha1": LAW_HEAD,
            "law_blob_sha1": LAW_BLOB_SHA1,
            "qualification_run_id": 33766105341,
            "evidence_artifact_id": EVIDENCE_ARTIFACT_ID,
            "publication_artifact_id": PUBLICATION_ARTIFACT_ID,
        },
        "audit": {
            "head_sha1": audit_head,
            "tree_sha1": audit_tree,
            "target_paths": sorted(target_paths),
            "audit_paths": sorted(audit_paths),
        },
        "artifact_reconciliation": {
            "evidence_zip_sha256": EVIDENCE_ZIP_SHA256,
            "publication_zip_sha256": PUBLICATION_ZIP_SHA256,
            "evidence_member_count": len(evidence_members),
            "publication_member_count": len(publication_members),
            "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
            "publication_payload_sha256": PUBLICATION_PAYLOAD,
        },
        "rederived": {
            "tests": 20,
            "control_roles": 3,
            "generator_cases": 108,
            "expected_empirical_observations": 648,
            "actual_control_identities": "UNBOUND",
            "synthetic_control_count": 3,
            "synthetic_plan_rows": 648,
            "public_path_canary_retained": False,
        },
        "attacks": attacks,
        "attack_count": len(attacks),
        "refused_count": len([item for item in attacks if item["passed"]]),
        "failed_count": len(failed),
        "failed_labels": [item["label"] for item in failed],
        "disposition": disposition,
        "authority": {
            "target_branch_mutated": False,
            "actual_control_identity_admitted": False,
            "empirical_subject_execution": False,
            "provider_or_model_calls": 0,
            "numeric_stage2_freeze": "NOT_ISSUED",
            "callable_astra_identity": "UNBOUND",
            "live_provider_dispatch": "PROHIBITED",
            "optional_24_call_block": "DISABLED",
            "benchmark_verdict_authority": "NONE",
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
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = execute(
        args.repo_root.resolve(),
        args.evidence_zip.resolve(),
        args.publication_zip.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
