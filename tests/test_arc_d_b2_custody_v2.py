#!/usr/bin/env python3
"""Content-blind and synthetic tests for ARC-D B2 custody-v2 tooling."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import export_arc_d_b2_packets as exporter  # noqa: E402
import validate_arc_d_b2_custody_v2 as validator  # noqa: E402
import verify_arc_d_b2_audit_auth as audit_auth  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value) -> bytes:
    data = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


@contextmanager
def _repo_scratch():
    root = ROOT / ".test-tmp" / f"custody-v2-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _preflight():
    def lane(venue: str, seed: str):
        digest = _sha(seed.encode())
        return {
            "opaque_venue_id": venue,
            "sentinel_path_sha256": _sha(f"{seed}/path".encode()),
            "sentinel_sha256": digest,
            "sentinel_bytes": len(seed),
            "object_id": seed[0] * 40,
            "tree_id": seed[-1] * 40,
            "write_receipt_sha256": _sha(f"{seed}/write".encode()),
            "readback_sha256": digest,
            "immutable_objects": True,
            "result": "PASS",
        }

    return {
        "schema": "tier-bench/arc-d-b2-custody-preflight-receipt@2",
        "protocol_id": validator.PROTOCOL_ID,
        "preflight_id": "arc-d-b2-v2-preflight-test",
        "executed_at": "2026-07-13T18:00:00Z",
        "content_used": "NON_GRADER_SENTINELS_ONLY",
        "lanes": {
            "grade_a": lane("private-grade-a-venue", "a1"),
            "grade_b": lane("private-grade-b-venue", "b2"),
        },
        "result": "PASS",
    }


def _profile(preflight_bytes: bytes):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    validator_sha = _sha((ROOT / "scripts/validate_arc_d_b2_custody_v2.py").read_bytes().replace(b"\r\n", b"\n"))
    authenticator_sha = _sha((ROOT / "scripts/verify_arc_d_b2_audit_auth.py").read_bytes().replace(b"\r\n", b"\n"))
    return {
        "schema": "tier-bench/arc-d-b2-custody-profile@2",
        "protocol_id": validator.PROTOCOL_ID,
        "amendment_sha256": validator.AMENDMENT_SHA256,
        "state": "PROPOSED_FOR_SEPARATE_ACTIVATION",
        "lanes": {
            "grade_a": {
                "venue_type": "private_git",
                "opaque_venue_id": "private-grade-a-venue",
                "immutable_objects": True,
                "separate_write_boundary": True,
                "expected_surface": "chatgpt.projectless",
            },
            "grade_b": {
                "venue_type": "private_git",
                "opaque_venue_id": "private-grade-b-venue",
                "immutable_objects": True,
                "separate_write_boundary": True,
                "expected_surface": "claude.projectless",
            },
        },
        "roles": {
            "custodian_id": "operator:BigBirdReturns",
            "verifier_id": "github-actions:arc-d-b2-verifier",
            "coordinator_id": "sol:019f5c7f",
            "verifier_lineage": "other",
            "verifier_lineage_conflicts": {"grade_a": False, "grade_b": False},
            "custodian_is_verifier": False,
            "coordinator_is_verifier": False,
            "verifier_is_not_rubric_author": True,
            "verifier_is_not_grading_instrument": True,
            "verifier_is_administration_only": True,
            "verifier_has_raw_read_access": True,
        },
        "retention": {
            "rule": "retain every immutable attempt object for the project lifetime",
            "recovery_copy": "independent encrypted recovery copy",
            "access_log": "append-only custodian access log",
            "export_procedure": "content-blind export by exact Git object identity",
        },
        "audit": {
            "authentication": "github_actions_oidc",
            "authentication_repository": "BigBirdReturns/tier-bench",
            "authentication_identity": "https://github.com/BigBirdReturns/tier-bench/.github/workflows/arc-d-b2-audit.yml@refs/heads/main",
            "validator_path": "scripts/validate_arc_d_b2_custody_v2.py",
            "validator_commit": head,
            "validator_sha256": validator_sha,
            "authentication_verifier_path": "scripts/verify_arc_d_b2_audit_auth.py",
            "authentication_verifier_sha256": authenticator_sha,
        },
        "preflight": {
            "receipt_sha256": _sha(preflight_bytes),
            "result": "PASS",
            "content_used": "NON_GRADER_SENTINELS_ONLY",
        },
    }


def _activation(profile_rel: str, profile_bytes: bytes, preflight_rel: str, preflight_bytes: bytes):
    components = {}
    for key, rel in validator.COMPONENT_PATHS.items():
        data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
        components[key] = {"path": rel, "git_blob_sha256": _sha(data)}
    return {
        "schema": "tier-bench/arc-d-b2-custody-activation-receipt@2",
        "protocol_id": validator.PROTOCOL_ID,
        "state": "PROPOSED_FOR_DEFAULT_BRANCH_ACTIVATION",
        "authority": {
            "amendment_path": validator.AMENDMENT_PATH,
            "amendment_sha256": validator.AMENDMENT_SHA256,
            "amendment_adoption_commit": validator.AMENDMENT_ADOPTION_COMMIT,
        },
        "custody_profile": {"path": profile_rel, "sha256": _sha(profile_bytes)},
        "preflight": {
            "path": preflight_rel,
            "sha256": _sha(preflight_bytes),
            "result": "PASS",
            "content_used": "NON_GRADER_SENTINELS_ONLY",
        },
        "components": components,
        "activation_rule": {
            "default_branch": "main",
            "event": "MAINTAINER_MERGE_OF_THIS_RECEIPT_AND_BOUND_COMPONENTS",
            "dispatch_before_event": False,
            "active_state": "ACTIVE_FOR_FRESH_V2_GRADING",
        },
    }


def _preregistration(commit: str):
    charter = json.loads((ROOT / "data/oss-replay/arc_d_buffalo_pilot_v2/harvest_charter.json").read_text())
    rows = {row["item_id"]: row for row in charter["sealed_evidence"]["responses"]}
    return {
        "schema": "tier-bench/arc-d-b2-attempt-preregistration@2",
        "protocol_id": validator.PROTOCOL_ID,
        "attempt_id": "arc-d-b2-v2-test",
        "amendment_sha256": validator.AMENDMENT_SHA256,
        "custody_profile_sha256": "1" * 64,
        "activation_commit": commit,
        "source_commit": commit,
        "maximum_dispatches_per_lane_item": 1,
        "items": {
            item: {
                "packet_sha256": _sha(f"packet/{item}".encode()),
                "prompt_sha256": rows[item]["prompt_sha256"],
                "response_sha256": rows[item]["response_sha256"],
                "same_packet_required_in_both_lanes": True,
            }
            for item in validator.ITEMS
        },
        "state": "PREREGISTERED_BEFORE_DISPATCH",
    }


def _dispatch(
    prereg_bytes: bytes,
    prereg: dict,
    outcome: str,
    state: str,
    *,
    revision: int,
    previous_sha256: str,
    previous_commit: str,
):
    cell = {"dispatch_index": 1, "outcome": outcome, "event_commitment_sha256": "2" * 64}
    lane = {item: copy.deepcopy(cell) for item in validator.ITEMS}
    return {
        "schema": "tier-bench/arc-d-b2-dispatch-ledger@2",
        "protocol_id": validator.PROTOCOL_ID,
        "attempt_id": prereg["attempt_id"],
        "preregistration_manifest_sha256": _sha(prereg_bytes),
        "preregistration_commit": "3" * 40,
        "preregistration_path": "attempt/preregistration.json",
        "ledger_path": "attempt/dispatch-ledger.json",
        "revision": revision,
        "previous_ledger_sha256": previous_sha256,
        "previous_ledger_commit": previous_commit,
        "cells": {"grade_a": copy.deepcopy(lane), "grade_b": copy.deepcopy(lane)},
        "state": state,
    }


def test_component_set_is_complete_and_static_admission_stays_green():
    assert validator.component_errors() == []


def test_profile_requires_real_role_and_venue_inequality():
    preflight = _preflight()
    preflight_bytes = (json.dumps(preflight, indent=2) + "\n").encode()
    profile = _profile(preflight_bytes)
    assert validator.validate_profile(profile, preflight_bytes) == []

    equal_role = copy.deepcopy(profile)
    equal_role["roles"]["verifier_id"] = equal_role["roles"]["custodian_id"]
    assert any("identities are equal" in e for e in validator.validate_profile(equal_role, preflight_bytes))

    equal_venue = copy.deepcopy(profile)
    equal_venue["lanes"]["grade_b"]["opaque_venue_id"] = equal_venue["lanes"]["grade_a"]["opaque_venue_id"]
    assert any("same venue" in e for e in validator.validate_profile(equal_venue, preflight_bytes))


def test_activation_binds_every_exact_component_and_preflight():
    with _repo_scratch() as scratch:
        preflight = _preflight()
        preflight_rel = (scratch / "preflight.json").relative_to(ROOT).as_posix()
        preflight_bytes = _write_json(scratch / "preflight.json", preflight)
        profile = _profile(preflight_bytes)
        profile_rel = (scratch / "profile.json").relative_to(ROOT).as_posix()
        profile_bytes = _write_json(scratch / "profile.json", profile)
        activation = _activation(profile_rel, profile_bytes, preflight_rel, preflight_bytes)
        errors, state = validator.validate_activation(activation, component_ref=None)
        assert errors == []
        assert state == "COMPONENTS_VALID_PENDING_DEFAULT_BRANCH_MERGE"

        drift = copy.deepcopy(activation)
        drift["components"]["custody_validator"]["git_blob_sha256"] = "0" * 64
        errors, _ = validator.validate_activation(drift, component_ref=None)
        assert any("Git blob hash mismatch" in error for error in errors)


def test_preregistration_and_dispatch_state_machine_fail_closed():
    with tempfile.TemporaryDirectory() as td:
        repo, activation = _init_public_repo(Path(td))
        prereg = _preregistration(activation)
        prereg_bytes, prereg_commit = _commit_json(
            repo, "attempt/preregistration.json", prereg, "preregister")
        assert validator.validate_preregistration(prereg, repo=repo) == []

        initial = _dispatch(
            prereg_bytes, prereg, "NOT_DISPATCHED", "IN_PROGRESS_APPEND_ONLY",
            revision=0, previous_sha256=validator.ZERO_SHA256,
            previous_commit=validator.ZERO_GITSHA)
        initial["preregistration_commit"] = prereg_commit
        initial_bytes, initial_commit = _commit_json(
            repo, initial["ledger_path"], initial, "dispatch revision zero")

        complete = _dispatch(
            prereg_bytes, prereg, "COMPLETED", "SEALED_COMPLETE",
            revision=1, previous_sha256=_sha(initial_bytes), previous_commit=initial_commit)
        complete["preregistration_commit"] = prereg_commit
        complete_bytes, complete_commit = _commit_json(
            repo, complete["ledger_path"], complete, "seal dispatch")

        assert validator.validate_dispatch(
            initial, prereg, prereg_bytes,
            ledger_bytes=initial_bytes, repository=repo,
            ledger_commit=initial_commit, canonical_commit=complete_commit) == []
        assert validator.validate_dispatch(
            complete, prereg, prereg_bytes,
            ledger_bytes=complete_bytes, repository=repo,
            ledger_commit=complete_commit, canonical_commit=complete_commit,
            previous_ledger=initial, previous_ledger_bytes=initial_bytes) == []

        decorative = copy.deepcopy(complete)
        decorative["previous_ledger_commit"] = "a" * 40
        errors = validator.validate_dispatch(
            decorative, prereg, prereg_bytes,
            ledger_bytes=complete_bytes, repository=repo,
            ledger_commit=complete_commit, canonical_commit=complete_commit,
            previous_ledger=initial, previous_ledger_bytes=initial_bytes)
        assert any("previous-ledger binding" in e or "ancestry" in e for e in errors)

        omitted = copy.deepcopy(complete)
        omitted["state"] = "SEALED_PARTIAL_UNPAIRED"
        omitted["cells"]["grade_a"][validator.ITEMS[0]]["outcome"] = "NOT_DISPATCHED"
        omitted_errors = validator.validate_dispatch(
            omitted, prereg, prereg_bytes,
            ledger_bytes=complete_bytes, repository=repo,
            ledger_commit=complete_commit, canonical_commit=complete_commit,
            previous_ledger=initial, previous_ledger_bytes=initial_bytes)
        assert any("may not omit" in e for e in omitted_errors)


def test_dispatch_canonical_history_voids_competing_successor_contents():
    with tempfile.TemporaryDirectory() as td:
        repo, activation = _init_public_repo(Path(td))
        prereg = _preregistration(activation)
        prereg_bytes, prereg_commit = _commit_json(
            repo, "attempt/preregistration.json", prereg, "preregister")
        initial = _dispatch(
            prereg_bytes, prereg, "NOT_DISPATCHED", "IN_PROGRESS_APPEND_ONLY",
            revision=0, previous_sha256=validator.ZERO_SHA256,
            previous_commit=validator.ZERO_GITSHA)
        initial["preregistration_commit"] = prereg_commit
        initial_bytes, initial_commit = _commit_json(
            repo, initial["ledger_path"], initial, "revision zero")
        completed = _dispatch(
            prereg_bytes, prereg, "COMPLETED", "SEALED_COMPLETE",
            revision=1, previous_sha256=_sha(initial_bytes), previous_commit=initial_commit)
        completed["preregistration_commit"] = prereg_commit
        completed_bytes, completed_commit = _commit_json(
            repo, completed["ledger_path"], completed, "first revision-one child")
        refused = copy.deepcopy(completed)
        refused["state"] = "SEALED_PARTIAL_UNPAIRED"
        refused["cells"]["grade_a"][validator.ITEMS[0]]["outcome"] = "REFUSED"
        refused_bytes, refused_commit = _commit_json(
            repo, refused["ledger_path"], refused, "competing revision-one child")
        for ledger, ledger_bytes, ledger_commit in (
            (completed, completed_bytes, completed_commit),
            (refused, refused_bytes, refused_commit),
        ):
            errors = validator.validate_dispatch(
                ledger, prereg, prereg_bytes,
                ledger_bytes=ledger_bytes, repository=repo,
                ledger_commit=ledger_commit, canonical_commit=refused_commit,
                previous_ledger=initial, previous_ledger_bytes=initial_bytes)
            assert any("competing canonical successor" in e for e in errors)


def test_authentication_helpers_fail_closed_and_pin_identity():
    with tempfile.TemporaryDirectory() as td:
        artifact = Path(td) / "audit.json"
        bundle = Path(td) / "bundle.jsonl"
        artifact.write_text("{}")
        bundle.write_text("{}")

        calls = []

        def oidc_runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="[{}]", stderr="")

        identity = "https://github.com/BigBirdReturns/tier-bench/.github/workflows/arc-d-b2-audit.yml@refs/heads/main"
        assert audit_auth.verify_github_actions_oidc(
            artifact, bundle, "BigBirdReturns/tier-bench", identity, "a" * 40, runner=oidc_runner,
        ) == []
        assert "--cert-identity" in calls[0] and "--source-digest" in calls[0]
        assert "--deny-self-hosted-runners" in calls[0]

        def failed_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="bad")

        assert audit_auth.verify_github_actions_oidc(
            artifact, bundle, "BigBirdReturns/tier-bench", identity, "a" * 40, runner=failed_runner,
        )

        fingerprint = "A" * 40

        def signed_runner(command, **kwargs):
            if "verify-commit" in command:
                return subprocess.CompletedProcess(
                    command, 0, stdout="", stderr=f"[GNUPG:] VALIDSIG {fingerprint} 2026 0 4 0 1 10 00 00")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        assert audit_auth.verify_signed_commit(
            Path(td), "b" * 40, fingerprint, runner=signed_runner) == []
        assert audit_auth.verify_signed_commit(
            Path(td), "b" * 40, "C" * 40, runner=signed_runner)


def test_official_authority_queries_pinned_github_main_not_origin():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0,
            stdout=("a" * 40 + "\trefs/heads/main\n").encode("ascii"),
            stderr=b"",
        )

    assert validator.canonical_main_commit(runner=runner) == "a" * 40
    assert calls == [[
        "git", "ls-remote", "--exit-code",
        "https://github.com/BigBirdReturns/tier-bench.git",
        "refs/heads/main",
    ]]


def _git(repo: Path, *args: str):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit_json(repo: Path, rel: str, value, message: str) -> tuple[bytes, str]:
    data = _write_json(repo / rel, value)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", message)
    return data, _git_output(repo, "rev-parse", "HEAD")


def _init_public_repo(root: Path) -> tuple[Path, str]:
    repo = root / "public"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "coordinator@example.invalid")
    _git(repo, "config", "user.name", "Coordinator Fixture")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "activation seed")
    return repo, _git_output(repo, "rev-parse", "HEAD")


def _synthetic_private_bundle(root: Path, custody_profile_sha256: str = "1" * 64):
    repo = root / "private"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "verifier@example.invalid")
    _git(repo, "config", "user.name", "Custody Fixture")
    bundle = repo / "bundles" / "grade_a" / validator.ITEMS[0]
    packet = bundle / "packet"
    export_receipt = bundle / "packet-export-receipt.json"
    exported = exporter.export_packet(validator.ITEMS[0], packet, export_receipt, require_default_branch=False)
    export_data = json.loads(export_receipt.read_text())
    export_data["official_dispatch_permitted"] = True
    _write_json(export_receipt, export_data)

    payload = {
        "schema": "tier-bench/arc-d-b2-grade-payload@1",
        "item_id": validator.ITEMS[0],
        "attestations": {
            "peer_grade_seen_before_seal": False,
            "repository_context_seen": False,
            "other_response_seen": False,
        },
        "atomic_findings": [],
        "response_disposition": "B2_NO_EXTRACTABLE_CANDIDATE",
    }
    raw_path = bundle / "raw-grade.json"
    raw_bytes = _write_json(raw_path, payload)
    payload_path = bundle / "grade-payload.json"
    payload_bytes = _write_json(payload_path, payload)
    session_id = "synthetic-private-session"
    session_path = bundle / "session-evidence.json"
    session_bytes = _write_json(session_path, {"synthetic": True})
    packet_manifest = json.loads((packet / "PACKET.json").read_text())
    grade_receipt = {
        "schema": "tier-bench/arc-d-b2-grade-receipt@1",
        "protocol_id": validator.PROTOCOL_ID,
        "charter_sha256": validator.PARENT_CHARTER_SHA256,
        "packet_sha256": _sha((packet / "PACKET.json").read_bytes()),
        "item_id": validator.ITEMS[0],
        "prompt_sha256": packet_manifest["prompt_sha256"],
        "response_sha256": packet_manifest["response_sha256"],
        "grader": {
            "grade_id": "grade_a",
            "provider_lineage": "openai",
            "model": "gpt-5.6-sol",
            "effort": "high",
            "surface": "chatgpt.projectless",
            "session_id": session_id,
            "started_at": "2026-07-13T18:01:00Z",
            "sealed_at": "2026-07-13T18:02:00Z",
        },
        "exposure": {
            "peer_grade_seen_before_seal": False,
            "repository_context_seen": False,
            "other_response_seen": False,
        },
        "raw_grade_sha256": _sha(raw_bytes),
        "atomic_findings": [],
        "response_disposition": "B2_NO_EXTRACTABLE_CANDIDATE",
        "validator_result": "PASS",
    }
    grade_receipt_path = bundle / "grade-receipt.json"
    grade_receipt_bytes = _write_json(grade_receipt_path, grade_receipt)
    paths = {
        "packet_manifest": (packet / "PACKET.json").relative_to(repo).as_posix(),
        "export_receipt": export_receipt.relative_to(repo).as_posix(),
        "raw_grade": raw_path.relative_to(repo).as_posix(),
        "grade_payload": payload_path.relative_to(repo).as_posix(),
        "grade_receipt": grade_receipt_path.relative_to(repo).as_posix(),
        "session_evidence": session_path.relative_to(repo).as_posix(),
    }
    artifact_bytes = {
        paths["packet_manifest"]: (packet / "PACKET.json").read_bytes(),
        paths["export_receipt"]: export_receipt.read_bytes(),
        paths["raw_grade"]: raw_bytes,
        paths["grade_payload"]: payload_bytes,
        paths["grade_receipt"]: grade_receipt_bytes,
        paths["session_evidence"]: session_bytes,
    }
    manifest = {
        "schema": "tier-bench/arc-d-b2-private-bundle-manifest@2",
        "protocol_id": validator.PROTOCOL_ID,
        "attempt_id": "arc-d-b2-v2-synthetic",
        "lane": "grade_a",
        "item_id": validator.ITEMS[0],
        "parent_charter_sha256": validator.PARENT_CHARTER_SHA256,
        "amendment_sha256": validator.AMENDMENT_SHA256,
        "custody_profile_sha256": custody_profile_sha256,
        "activation_commit": "2" * 40,
        "preregistration_manifest_sha256": "3" * 64,
        "preregistration_commit": "4" * 40,
        "dispatch_ledger_sha256": "5" * 64,
        "dispatch_ledger_commit": "6" * 40,
        "packet_sha256": _sha((packet / "PACKET.json").read_bytes()),
        "prompt_sha256": packet_manifest["prompt_sha256"],
        "response_sha256": packet_manifest["response_sha256"],
        "response_bytes": packet_manifest["response_bytes"],
        "dispatch_index": 1,
        "instrument": {
            "provider_lineage": "openai",
            "model": "gpt-5.6-sol",
            "effort": "high",
            "surface": "chatgpt.projectless",
            "session_id_sha256": _sha(session_id.encode()),
        },
        "chronology": {
            "dispatched_at": "2026-07-13T18:00:00Z",
            "started_at": "2026-07-13T18:01:00Z",
            "sealed_at": "2026-07-13T18:02:00Z",
        },
        "exposure": {
            "peer_grade_seen_before_seal": False,
            "prior_grade_seen": False,
            "repository_context_seen": False,
            "other_response_seen": False,
        },
        "paths": paths,
        "artifacts": [
            {"path": path, "sha256": _sha(data), "bytes": len(data)}
            for path, data in artifact_bytes.items()
        ],
        "bundle_state": "PRIVATE_SEALED",
    }
    manifest_path = bundle / "manifest.json"
    manifest_bytes = _write_json(manifest_path, manifest)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "synthetic private bundle")
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    parent = manifest_path.parent.relative_to(repo).as_posix()
    public = {
        "schema": "tier-bench/arc-d-b2-public-admission-receipt@2",
        "protocol_id": validator.PROTOCOL_ID,
        "attempt_id": manifest["attempt_id"],
        "lane": manifest["lane"],
        "item_id": manifest["item_id"],
        "parent_charter_sha256": manifest["parent_charter_sha256"],
        "amendment_sha256": manifest["amendment_sha256"],
        "custody_profile_sha256": manifest["custody_profile_sha256"],
        "activation_commit": manifest["activation_commit"],
        "preregistration_manifest_sha256": manifest["preregistration_manifest_sha256"],
        "preregistration_commit": manifest["preregistration_commit"],
        "dispatch_ledger_sha256": manifest["dispatch_ledger_sha256"],
        "dispatch_ledger_commit": manifest["dispatch_ledger_commit"],
        "packet_sha256": manifest["packet_sha256"],
        "prompt_sha256": manifest["prompt_sha256"],
        "response_sha256": manifest["response_sha256"],
        "private_bundle": {
            "opaque_venue_id": "private-grade-a-venue",
            "object_id": commit,
            "tree_id": tree,
            "bundle_path_sha256": _sha(parent.encode()),
            "manifest_sha256": _sha(manifest_bytes),
            "manifest_bytes": len(manifest_bytes),
            "raw_grade_sha256": _sha(raw_bytes),
            "payload_sha256": _sha(payload_bytes),
            "grade_receipt_sha256": _sha(grade_receipt_bytes),
            "session_evidence_sha256": _sha(session_bytes),
            "session_id_sha256": _sha(session_id.encode()),
        },
        "instrument": {
            "provider_lineage": "openai",
            "model": "gpt-5.6-sol",
            "effort": "high",
            "surface": "chatgpt.projectless",
        },
        "chronology": {
            "dispatched_at": "2026-07-13T18:00:00Z",
            "sealed_at": "2026-07-13T18:02:00Z",
        },
        "audit": {
            "verifier_id": "github-actions:arc-d-b2-verifier",
            "audit_receipt_sha256": "7" * 64,
            "validator_sha256": "8" * 64,
            "authentication": "github_actions_oidc",
            "authentication_evidence_sha256": "9" * 64,
            "result": "PASS",
            "raw_bytes_accessed": True,
        },
        "state": "PROPOSED_FOR_ATOMIC_ADMISSION",
    }
    return repo, commit, manifest_path.relative_to(repo).as_posix(), public, raw_path


def test_private_validator_reads_exact_git_objects_and_derives_public_commitments():
    with tempfile.TemporaryDirectory() as td:
        repo, commit, manifest_path, public, raw_path = _synthetic_private_bundle(Path(td))
        errors, _ = validator.validate_private_bundle(repo, commit, manifest_path, public_receipt=public)
        assert errors == []

        # Working-tree mutation cannot alter the audited historical object.
        raw_path.write_text("tampered working tree")
        errors, _ = validator.validate_private_bundle(repo, commit, manifest_path, public_receipt=public)
        assert errors == []

        wrong_object = copy.deepcopy(public)
        wrong_object["private_bundle"]["object_id"] = "0" * 40
        errors, _ = validator.validate_private_bundle(repo, commit, manifest_path, public_receipt=wrong_object)
        assert any("object_id" in error for error in errors)


def test_audit_receipt_binds_designation_private_object_and_public_receipt():
    with tempfile.TemporaryDirectory() as td:
        preflight = _preflight()
        preflight_bytes = (json.dumps(preflight, indent=2) + "\n").encode()
        profile = _profile(preflight_bytes)
        profile_bytes = (json.dumps(profile, indent=2) + "\n").encode()
        repo, commit, manifest_path, public, _ = _synthetic_private_bundle(
            Path(td), _sha(profile_bytes))
        private_errors, manifest = validator.validate_private_bundle(
            repo, commit, manifest_path, public_receipt=public)
        assert private_errors == [] and manifest is not None
        manifest_bytes = validator.git_bytes(repo, commit, manifest_path)
        tree = validator.git_tree(repo, commit)
        audit = {
            "schema": "tier-bench/arc-d-b2-audit-receipt@2",
            "protocol_id": validator.PROTOCOL_ID,
            "attempt_id": manifest["attempt_id"],
            "lane": manifest["lane"],
            "item_id": manifest["item_id"],
            "custody_profile_sha256": _sha(profile_bytes),
            "activation_commit": manifest["activation_commit"],
            "preregistration_manifest_sha256": manifest["preregistration_manifest_sha256"],
            "dispatch_ledger_sha256": manifest["dispatch_ledger_sha256"],
            "private_object": {
                "opaque_venue_id": profile["lanes"]["grade_a"]["opaque_venue_id"],
                "commit_id": commit,
                "tree_id": tree,
                "manifest_path_sha256": _sha(manifest_path.encode()),
                "manifest_sha256": _sha(manifest_bytes),
            },
            "validator": {
                "path": profile["audit"]["validator_path"],
                "commit": profile["audit"]["validator_commit"],
                "sha256": profile["audit"]["validator_sha256"],
            },
            "verifier_id": profile["roles"]["verifier_id"],
            "authentication": {
                "method": profile["audit"]["authentication"],
                "identity": profile["audit"]["authentication_identity"],
                "subject_commit": profile["audit"]["validator_commit"],
                "subject_path": "audits/grade-a-attrs.json",
                "evidence_path_sha256": _sha(b"bundle.jsonl"),
                "evidence_sha256": "9" * 64,
                "verified_at": "2026-07-13T18:03:00Z",
            },
            "raw_bytes_accessed": True,
            "error_commitment_sha256": validator.EMPTY_SHA256,
            "audited_at": "2026-07-13T18:03:00Z",
            "result": "PASS",
        }
        audit_bytes = (json.dumps(audit, indent=2) + "\n").encode()
        public["audit"] = {
            "verifier_id": audit["verifier_id"],
            "audit_receipt_sha256": _sha(audit_bytes),
            "validator_sha256": audit["validator"]["sha256"],
            "authentication": audit["authentication"]["method"],
            "authentication_evidence_sha256": audit["authentication"]["evidence_sha256"],
            "result": "PASS",
            "raw_bytes_accessed": True,
        }
        assert validator.validate_audit_receipt(
            audit,
            profile,
            manifest,
            profile_bytes=profile_bytes,
            private_commit=commit,
            private_tree=tree,
            private_manifest_path=manifest_path,
            private_manifest_bytes=manifest_bytes,
            authentication_verified=True,
        ) == []
        assert validator.validate_public_audit_binding(public, audit, audit_bytes) == []
        errors = validator.validate_audit_receipt(
            audit,
            profile,
            manifest,
            profile_bytes=profile_bytes,
            private_commit=commit,
            private_tree=tree,
            private_manifest_path=manifest_path,
            private_manifest_bytes=manifest_bytes,
            authentication_verified=False,
        )
        assert any("not cryptographically verified" in error for error in errors)


def test_audit_cli_passes_exact_profile_bytes_to_binding_validation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        audit_path = root / "audit.json"
        profile_path = root / "profile.json"
        public_path = root / "public.json"
        evidence_path = root / "evidence.json"
        profile_bytes = _write_json(profile_path, {"profile": "exact-bytes"})
        _write_json(audit_path, {})
        _write_json(public_path, {})
        evidence_path.write_bytes(b"evidence")

        captured = {}
        replacements = {
            "validate_private_bundle": lambda *args, **kwargs: ([], {}),
            "verify_audit_authentication": lambda *args, **kwargs: [],
            "git_tree": lambda *args, **kwargs: "a" * 40,
            "git_bytes": lambda *args, **kwargs: b"{}\n",
            "validate_public_audit_binding": lambda *args, **kwargs: [],
        }

        def fake_validate_audit(*args, **kwargs):
            captured["profile_bytes"] = kwargs["profile_bytes"]
            return []

        replacements["validate_audit_receipt"] = fake_validate_audit
        originals = {name: getattr(validator, name) for name in replacements}
        original_argv = sys.argv
        try:
            for name, replacement in replacements.items():
                setattr(validator, name, replacement)
            sys.argv = [
                "validate_arc_d_b2_custody_v2.py", "audit", str(audit_path),
                "--profile", str(profile_path),
                "--authentication-evidence", str(evidence_path),
                "--private-repository", str(root),
                "--private-commit", "b" * 40,
                "--private-manifest-path", "bundle/MANIFEST.json",
                "--public-receipt", str(public_path),
            ]
            assert validator.main() == 0
        finally:
            sys.argv = original_argv
            for name, original in originals.items():
                setattr(validator, name, original)
        assert captured["profile_bytes"] == profile_bytes


def test_public_receipt_never_accepts_content_bearing_fields():
    with tempfile.TemporaryDirectory() as td:
        _, _, _, public, _ = _synthetic_private_bundle(Path(td))
        assert validator.validate_public_receipt_shape(public) == []
        leaked = copy.deepcopy(public)
        leaked["audit"]["raw_grade"] = "forbidden"
        errors = validator.validate_public_receipt_shape(leaked)
        assert any("content-bearing" in error for error in errors)


def test_batch_validator_requires_exact_six_cell_bindings_and_chronology():
    with tempfile.TemporaryDirectory() as td:
        _, _, _, base, _ = _synthetic_private_bundle(Path(td))
        repo, activation = _init_public_repo(Path(td))
        preregistration = _preregistration(activation)
        preregistration["attempt_id"] = base["attempt_id"]
        preregistration["custody_profile_sha256"] = base["custody_profile_sha256"]
        preregistration_bytes, preregistration_commit = _commit_json(
            repo, "attempt/preregistration.json", preregistration, "preregister batch")
        initial = _dispatch(
            preregistration_bytes, preregistration,
            "NOT_DISPATCHED", "IN_PROGRESS_APPEND_ONLY",
            revision=0, previous_sha256=validator.ZERO_SHA256,
            previous_commit=validator.ZERO_GITSHA)
        initial["preregistration_commit"] = preregistration_commit
        initial_bytes, initial_commit = _commit_json(
            repo, initial["ledger_path"], initial, "batch revision zero")
        complete = _dispatch(
            preregistration_bytes, preregistration,
            "COMPLETED", "SEALED_COMPLETE",
            revision=1, previous_sha256=_sha(initial_bytes), previous_commit=initial_commit)
        complete["preregistration_commit"] = preregistration_commit
        complete_bytes, complete_commit = _commit_json(
            repo, complete["ledger_path"], complete, "batch sealed complete")

        receipt_root = Path(td) / "receipts-root"
        grid = {lane: {} for lane in validator.LANES}
        for lane in validator.LANES:
            for item in validator.ITEMS:
                receipt = copy.deepcopy(base)
                receipt.update({
                    "attempt_id": preregistration["attempt_id"],
                    "activation_commit": activation,
                    "preregistration_manifest_sha256": _sha(preregistration_bytes),
                    "preregistration_commit": preregistration_commit,
                    "dispatch_ledger_sha256": _sha(complete_bytes),
                    "dispatch_ledger_commit": complete_commit,
                    "packet_sha256": preregistration["items"][item]["packet_sha256"],
                    "prompt_sha256": preregistration["items"][item]["prompt_sha256"],
                    "response_sha256": preregistration["items"][item]["response_sha256"],
                })
                receipt["lane"] = lane
                receipt["item_id"] = item
                if lane == "grade_b":
                    receipt["instrument"] = {
                        "provider_lineage": "anthropic",
                        "model": "fable-5",
                        "effort": "high",
                        "surface": "claude.projectless",
                    }
                rel = f"receipts/{lane}/{item}.json"
                data = _write_json(receipt_root / rel, receipt)
                grid[lane][item] = {"path": rel, "sha256": _sha(data)}
        batch = {
            "schema": "tier-bench/arc-d-b2-batch-admission-receipt@2",
            "protocol_id": validator.PROTOCOL_ID,
            "attempt_id": preregistration["attempt_id"],
            "amendment_sha256": base["amendment_sha256"],
            "custody_profile_sha256": base["custody_profile_sha256"],
            "activation_commit": activation,
            "preregistration_manifest_sha256": _sha(preregistration_bytes),
            "preregistration_commit": preregistration_commit,
            "preregistration_path": "attempt/preregistration.json",
            "dispatch_ledger_sha256": _sha(complete_bytes),
            "dispatch_ledger_commit": complete_commit,
            "dispatch_ledger_path": complete["ledger_path"],
            "required_receipt_count": 6,
            "receipts": grid,
            "seal": {
                "last_private_sealed_at": "2026-07-13T18:05:00Z",
                "first_public_disclosure_at": "2026-07-13T18:06:00Z",
                "all_private_before_public": True,
            },
            "attempt_failures": 0,
            "state": "PROPOSED_FOR_ATOMIC_ADMISSION",
        }
        args = (
            batch, receipt_root, preregistration, preregistration_bytes,
            complete, complete_bytes,
        )
        kwargs = {"repository": repo, "canonical_commit": complete_commit}
        assert validator.validate_batch(*args, **kwargs) == []

        shopped_rel = grid["grade_b"][validator.ITEMS[0]]["path"]
        shopped_path = receipt_root / shopped_rel
        shopped = json.loads(shopped_path.read_text())
        shopped["packet_sha256"] = "a" * 64
        shopped_bytes = _write_json(shopped_path, shopped)
        batch["receipts"]["grade_b"][validator.ITEMS[0]]["sha256"] = _sha(shopped_bytes)
        shopped_errors = validator.validate_batch(*args, **kwargs)
        assert any("packet_sha256 differs from preregistration" in e for e in shopped_errors)

        _write_json(shopped_path, {
            **shopped,
            "packet_sha256": preregistration["items"][validator.ITEMS[0]]["packet_sha256"],
        })
        restored_bytes = shopped_path.read_bytes()
        batch["receipts"]["grade_b"][validator.ITEMS[0]]["sha256"] = _sha(restored_bytes)
        reversed_time = copy.deepcopy(batch)
        reversed_time["seal"]["first_public_disclosure_at"] = "2026-07-13T18:04:00Z"
        reversed_args = (reversed_time,) + args[1:]
        assert any("did not follow" in error for error in validator.validate_batch(*reversed_args, **kwargs))


def _run_standalone() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
