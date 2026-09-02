#!/usr/bin/env python3
"""Validate ARC-D B2 custody-v2 components and exact private Git objects.

The public modes in this tool validate commitment shape only. They never emit
``ADMITTED`` and never interpret unavailable private bytes. Semantic private
validation requires an exact immutable Git commit plus authenticated audit
evidence from the separately designated verifier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import validate_arc_d_b2_admission_v2 as admission
import validate_arc_d_b2_packet as packet_validator
import verify_arc_d_b2_audit_auth as audit_auth


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "arc_d_buffalo_pilot_v2"
PARENT_CHARTER_SHA256 = "44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e"
AMENDMENT_PATH = "data/oss-replay/arc_d_buffalo_pilot_v2/harvest_charter_v2.json"
AMENDMENT_SHA256 = "5c6cec7469732d0a614b5b45ef2ef5c7aa495c0ff6f31e53657da2f28b1740c9"
AMENDMENT_ADOPTION_COMMIT = "e7201e1debd38a86839e0661d7c3b5f6cf21d94f"
CANONICAL_REPOSITORY_URL = "https://github.com/BigBirdReturns/tier-bench.git"
CANONICAL_MAIN_REF = "refs/heads/main"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ZERO_SHA256 = "0" * 64
ZERO_GITSHA = "0" * 40

LANES = ("grade_a", "grade_b")
ITEMS = (
    "attrs_1567_setattr_mro",
    "httpx_3614_base_url_query",
    "httpx_3221_ipv6_no_proxy",
)
EXPECTED_INSTRUMENT = {
    "grade_a": ("openai", "gpt-5.6-sol", "high"),
    "grade_b": ("anthropic", "fable-5", "high"),
}

SCHEMA_PATHS = {
    "profile": "schemas/arc_d_b2_custody_profile.schema.json",
    "preflight": "schemas/arc_d_b2_custody_preflight_receipt.schema.json",
    "activation": "schemas/arc_d_b2_custody_activation_receipt.schema.json",
    "preregistration": "schemas/arc_d_b2_attempt_preregistration.schema.json",
    "dispatch": "schemas/arc_d_b2_dispatch_ledger.schema.json",
    "private_bundle": "schemas/arc_d_b2_private_bundle_manifest.schema.json",
    "audit": "schemas/arc_d_b2_audit_receipt.schema.json",
    "public": "schemas/arc_d_b2_public_admission_receipt.schema.json",
    "batch": "schemas/arc_d_b2_batch_admission_receipt.schema.json",
    "payload": "schemas/arc_d_b2_grade_payload.schema.json",
    "grade_receipt": "schemas/arc_d_b2_grade_receipt.schema.json",
}
COMPONENT_PATHS = {
    "custody_profile_schema": SCHEMA_PATHS["profile"],
    "custody_preflight_schema": SCHEMA_PATHS["preflight"],
    "custody_activation_schema": SCHEMA_PATHS["activation"],
    "attempt_preregistration_schema": SCHEMA_PATHS["preregistration"],
    "dispatch_ledger_schema": SCHEMA_PATHS["dispatch"],
    "private_bundle_schema": SCHEMA_PATHS["private_bundle"],
    "audit_receipt_schema": SCHEMA_PATHS["audit"],
    "public_receipt_schema": SCHEMA_PATHS["public"],
    "batch_receipt_schema": SCHEMA_PATHS["batch"],
    "grade_payload_schema": SCHEMA_PATHS["payload"],
    "grade_receipt_schema": SCHEMA_PATHS["grade_receipt"],
    "packet_validator": "scripts/validate_arc_d_b2_packet.py",
    "custody_validator": "scripts/validate_arc_d_b2_custody_v2.py",
    "audit_authenticator": "scripts/verify_arc_d_b2_audit_auth.py",
}
PUBLIC_FORBIDDEN_KEYS = admission.PUBLIC_FORBIDDEN_KEYS | {
    "private_path", "credential", "token", "raw_response", "session_evidence",
}


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON object key")
        out[key] = value
    return out


def loads(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"), object_pairs_hook=_strict_pairs)


def load(path: Path) -> Any:
    return loads(path.read_bytes())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def _schema(name: str) -> dict[str, Any]:
    return load(ROOT / SCHEMA_PATHS[name])


def _safe_rel(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("path must be normalized and relative")
    return path


def _root_path(value: str) -> Path:
    rel = _safe_rel(value)
    path = (ROOT / Path(*rel.parts)).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError("path escapes repository")
    return path


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("date-time lacks timezone")
    return parsed


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )


def canonical_main_commit(*, runner=subprocess.run) -> str:
    """Resolve main from the pinned GitHub repository, never a local remote."""
    environment = dict(os.environ)
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CEILING_DIRECTORIES": str(ROOT.parent),
    })
    proc = runner(
        ["git", "ls-remote", "--exit-code", CANONICAL_REPOSITORY_URL, CANONICAL_MAIN_REF],
        check=False,
        capture_output=True,
        cwd=ROOT.parent,
        env=environment,
    )
    if proc.returncode != 0:
        raise RuntimeError("canonical GitHub main is unavailable")
    fields = proc.stdout.decode("ascii").strip().split()
    if len(fields) != 2 or fields[1] != CANONICAL_MAIN_REF or re.fullmatch(r"[0-9a-f]{40}", fields[0]) is None:
        raise ValueError("canonical GitHub main response is malformed")
    return fields[0]


def _commit_blob_errors(repo: Path, commit: str, rel: str, expected: bytes, label: str) -> list[str]:
    try:
        actual = git_bytes(repo, commit, rel)
    except Exception:
        return [f"{label}: committed bytes are unavailable"]
    if actual != expected:
        return [f"{label}: commit does not contain the exact declared bytes"]
    return []


def _ancestor_errors(repo: Path, ancestor: str, descendant: str, label: str) -> list[str]:
    if re.fullmatch(r"[0-9a-f]{40}", ancestor or "") is None or re.fullmatch(r"[0-9a-f]{40}", descendant or "") is None:
        return [f"{label}: commit identity is malformed"]
    if _git(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode != 0:
        return [f"{label}: required Git ancestry is absent"]
    return []


def _successor_hashes_on_canonical_main(
    repo: Path,
    canonical_commit: str,
    parent_commit: str,
    ledger_path: str,
    ledger: dict[str, Any],
) -> set[str]:
    """Return distinct canonical successor contents for one declared parent."""
    proc = _git(repo, "rev-list", canonical_commit, f"^{parent_commit}", "--", ledger_path)
    if proc.returncode != 0:
        raise RuntimeError("canonical ledger history is unavailable")
    hashes: set[str] = set()
    for raw_commit in proc.stdout.decode("ascii").splitlines():
        commit = raw_commit.strip()
        try:
            data = git_bytes(repo, commit, ledger_path)
            candidate = loads(data)
        except Exception:
            continue
        if (
            candidate.get("attempt_id") == ledger.get("attempt_id")
            and candidate.get("revision") == ledger.get("revision")
            and candidate.get("previous_ledger_commit") == ledger.get("previous_ledger_commit")
            and candidate.get("previous_ledger_sha256") == ledger.get("previous_ledger_sha256")
        ):
            hashes.add(sha256(data))
    return hashes


def git_bytes(repo: Path, commit: str, rel: str) -> bytes:
    _safe_rel(rel)
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("exact private commit must be full 40-hex")
    proc = _git(repo, "cat-file", "blob", f"{commit}:{rel}")
    if proc.returncode != 0:
        raise FileNotFoundError(rel)
    return proc.stdout


def git_tree(repo: Path, commit: str) -> str:
    proc = _git(repo, "rev-parse", f"{commit}^{{tree}}")
    if proc.returncode != 0:
        raise ValueError("private commit is unavailable")
    tree = proc.stdout.decode("ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ValueError("private tree identity is malformed")
    return tree


def git_blob_at_public_ref(rel: str, ref: str | None) -> bytes:
    _safe_rel(rel)
    if ref is None:
        return _root_path(rel).read_bytes().replace(b"\r\n", b"\n")
    proc = _git(ROOT, "cat-file", "blob", f"{ref}:{rel}")
    if proc.returncode != 0:
        raise FileNotFoundError(rel)
    return proc.stdout


def component_errors() -> list[str]:
    errors = list(admission.validate_static())
    for name, rel in SCHEMA_PATHS.items():
        try:
            schema = load(ROOT / rel)
        except Exception as exc:
            errors.append(f"{name} schema is unreadable: {type(exc).__name__}")
            continue
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            errors.append(f"{name} schema root is not fail closed")
    for rel in COMPONENT_PATHS.values():
        if not (ROOT / rel).is_file():
            errors.append(f"activation component missing: {rel}")
    return errors


def validate_preflight(preflight: dict[str, Any], profile: dict[str, Any] | None = None) -> list[str]:
    errors = admission.schema_errors(preflight, _schema("preflight"), label="preflight")
    lanes = preflight.get("lanes", {})
    if isinstance(lanes, dict) and all(lane in lanes for lane in LANES):
        ids = [lanes[lane].get("opaque_venue_id") for lane in LANES]
        if ids[0] == ids[1]:
            errors.append("preflight: grade lanes use the same venue")
        for lane in LANES:
            row = lanes[lane]
            if row.get("readback_sha256") != row.get("sentinel_sha256"):
                errors.append(f"preflight.{lane}: readback differs from written sentinel")
            if profile is not None:
                expected = profile.get("lanes", {}).get(lane, {}).get("opaque_venue_id")
                if row.get("opaque_venue_id") != expected:
                    errors.append(f"preflight.{lane}: venue differs from custody profile")
    return errors


def validate_profile(profile: dict[str, Any], preflight_bytes: bytes) -> list[str]:
    errors = admission.schema_errors(profile, _schema("profile"), label="profile")
    if profile.get("amendment_sha256") != AMENDMENT_SHA256:
        errors.append("profile: amendment hash differs from adopted authority")
    try:
        preflight = loads(preflight_bytes)
    except Exception as exc:
        return errors + [f"preflight is malformed or duplicate-keyed: {type(exc).__name__}"]
    roles = profile.get("roles", {})
    if roles.get("custodian_id") == roles.get("verifier_id"):
        errors.append("profile.roles: custodian and verifier identities are equal")
    if roles.get("coordinator_id") == roles.get("verifier_id"):
        errors.append("profile.roles: coordinator and verifier identities are equal")
    lanes = profile.get("lanes", {})
    if lanes.get("grade_a", {}).get("opaque_venue_id") == lanes.get("grade_b", {}).get("opaque_venue_id"):
        errors.append("profile.lanes: grade lanes use the same venue")
    declared_preflight = profile.get("preflight", {})
    if declared_preflight.get("receipt_sha256") != sha256(preflight_bytes):
        errors.append("profile.preflight: receipt hash mismatch")
    if declared_preflight.get("result") != preflight.get("result"):
        errors.append("profile.preflight: result mismatch")
    if declared_preflight.get("content_used") != preflight.get("content_used"):
        errors.append("profile.preflight: content boundary mismatch")
    errors.extend(validate_preflight(preflight, profile))
    return errors


def validate_activation(
    receipt: dict[str, Any],
    *,
    component_ref: str | None = None,
    official: bool = False,
    canonical_commit: str | None = None,
) -> tuple[list[str], str]:
    errors = admission.schema_errors(receipt, _schema("activation"), label="activation")
    authority = receipt.get("authority", {})
    try:
        adopted = git_bytes(ROOT, AMENDMENT_ADOPTION_COMMIT, AMENDMENT_PATH)
        if sha256(adopted) != AMENDMENT_SHA256:
            errors.append("activation.authority: adopted amendment blob hash mismatch")
    except Exception:
        errors.append("activation.authority: adopted amendment blob unavailable")
    if authority.get("amendment_sha256") != AMENDMENT_SHA256:
        errors.append("activation.authority: amendment hash mismatch")

    try:
        profile_path = _root_path(receipt["custody_profile"]["path"])
        profile_bytes = profile_path.read_bytes()
        preflight_path = _root_path(receipt["preflight"]["path"])
        preflight_bytes = preflight_path.read_bytes()
        profile = loads(profile_bytes)
        preflight = loads(preflight_bytes)
    except Exception as exc:
        return errors + [f"activation inputs unavailable or malformed: {type(exc).__name__}"], "PENDING_CUSTODY"
    if receipt["custody_profile"].get("sha256") != sha256(profile_bytes):
        errors.append("activation.custody_profile: hash mismatch")
    if receipt["preflight"].get("sha256") != sha256(preflight_bytes):
        errors.append("activation.preflight: hash mismatch")
    if receipt["preflight"].get("result") != preflight.get("result"):
        errors.append("activation.preflight: result mismatch")
    if receipt["preflight"].get("content_used") != preflight.get("content_used"):
        errors.append("activation.preflight: content boundary mismatch")
    errors.extend(validate_profile(profile, preflight_bytes))

    components = receipt.get("components", {})
    if set(components) != set(COMPONENT_PATHS):
        errors.append("activation.components: exact component key set mismatch")
    for key, expected_path in COMPONENT_PATHS.items():
        row = components.get(key, {})
        if row.get("path") != expected_path:
            errors.append(f"activation.components.{key}: path mismatch")
            continue
        try:
            actual = sha256(git_blob_at_public_ref(expected_path, component_ref))
        except Exception:
            errors.append(f"activation.components.{key}: bound blob unavailable")
            continue
        if row.get("git_blob_sha256") != actual:
            errors.append(f"activation.components.{key}: Git blob hash mismatch")

    profile_audit = profile.get("audit", {})
    custody_hash = components.get("custody_validator", {}).get("git_blob_sha256")
    auth_hash = components.get("audit_authenticator", {}).get("git_blob_sha256")
    if profile_audit.get("validator_sha256") != custody_hash:
        errors.append("activation: custody profile validator hash differs from bound component")
    if profile_audit.get("authentication_verifier_sha256") != auth_hash:
        errors.append("activation: custody profile authenticator hash differs from bound component")
    validator_commit = profile_audit.get("validator_commit", "")
    if component_ref is not None and re.fullmatch(r"[0-9a-f]{40}", validator_commit):
        try:
            if sha256(git_blob_at_public_ref(COMPONENT_PATHS["custody_validator"], validator_commit)) != profile_audit.get("validator_sha256"):
                errors.append("activation: profile validator commit does not contain the declared validator")
            if sha256(git_blob_at_public_ref(COMPONENT_PATHS["audit_authenticator"], validator_commit)) != profile_audit.get("authentication_verifier_sha256"):
                errors.append("activation: profile validator commit does not contain the declared authenticator")
            ancestor = _git(ROOT, "merge-base", "--is-ancestor", validator_commit, component_ref)
            if ancestor.returncode != 0:
                errors.append("activation: profile validator commit is not an ancestor of the activation components")
        except Exception:
            errors.append("activation: profile validator commit is unavailable")

    state = "COMPONENTS_VALID_PENDING_DEFAULT_BRANCH_MERGE"
    if official:
        head = _git(ROOT, "rev-parse", "HEAD")
        branch = _git(ROOT, "branch", "--show-current")
        try:
            trusted_main = canonical_commit or canonical_main_commit()
        except Exception as exc:
            errors.append(f"activation official mode cannot resolve pinned GitHub authority: {type(exc).__name__}")
            trusted_main = ""
        if head.returncode or branch.returncode:
            errors.append("activation official mode cannot resolve Git authority")
        elif head.stdout.decode("ascii").strip() != trusted_main or branch.stdout.decode().strip() != "main":
            errors.append("activation official mode requires the exact pinned GitHub main commit")
        elif component_ref != "HEAD":
            errors.append("activation official mode requires HEAD-bound components")
        else:
            state = "ACTIVE_FOR_FRESH_V2_GRADING"
    return errors, state


def validate_preregistration(value: dict[str, Any], *, repo: Path = ROOT) -> list[str]:
    errors = admission.schema_errors(value, _schema("preregistration"), label="preregistration")
    if value.get("amendment_sha256") != AMENDMENT_SHA256:
        errors.append("preregistration: amendment hash differs from adopted authority")
    charter = load(ROOT / "data/oss-replay/arc_d_buffalo_pilot_v2/harvest_charter.json")
    rows = {row["item_id"]: row for row in charter["sealed_evidence"]["responses"]}
    for item in ITEMS:
        row = value.get("items", {}).get(item, {})
        parent = rows.get(item, {})
        for key in ("prompt_sha256", "response_sha256"):
            if row.get(key) != parent.get(key):
                errors.append(f"preregistration.items.{item}: {key} differs from ratified response")
    activation_commit = value.get("activation_commit", "")
    source_commit = value.get("source_commit", "")
    if re.fullmatch(r"[0-9a-f]{40}", activation_commit) and re.fullmatch(r"[0-9a-f]{40}", source_commit):
        proc = _git(repo, "merge-base", "--is-ancestor", activation_commit, source_commit)
        if proc.returncode != 0:
            errors.append("preregistration: source commit is not at or after activation")
    return errors


def validate_dispatch(
    ledger: dict[str, Any],
    preregistration: dict[str, Any],
    preregistration_bytes: bytes,
    *,
    ledger_bytes: bytes,
    repository: Path,
    ledger_commit: str,
    canonical_commit: str,
    previous_ledger: dict[str, Any] | None = None,
    previous_ledger_bytes: bytes | None = None,
) -> list[str]:
    errors = admission.schema_errors(ledger, _schema("dispatch"), label="dispatch")
    errors.extend(validate_preregistration(preregistration, repo=repository))
    if ledger.get("attempt_id") != preregistration.get("attempt_id"):
        errors.append("dispatch: attempt differs from preregistration")
    if ledger.get("preregistration_manifest_sha256") != sha256(preregistration_bytes):
        errors.append("dispatch: preregistration hash mismatch")
    preregistration_commit = ledger.get("preregistration_commit", "")
    preregistration_path = ledger.get("preregistration_path", "")
    ledger_path = ledger.get("ledger_path", "")
    errors.extend(_commit_blob_errors(
        repository, preregistration_commit, preregistration_path,
        preregistration_bytes, "dispatch preregistration binding"))
    errors.extend(_commit_blob_errors(
        repository, ledger_commit, ledger_path, ledger_bytes,
        "dispatch current-ledger binding"))
    errors.extend(_ancestor_errors(
        repository, preregistration_commit, ledger_commit,
        "dispatch preregistration-to-ledger"))
    errors.extend(_ancestor_errors(
        repository, preregistration.get("source_commit", ""), ledger_commit,
        "dispatch packet-source-to-ledger"))
    errors.extend(_ancestor_errors(
        repository, ledger_commit, canonical_commit,
        "dispatch ledger-to-canonical-main"))
    outcomes = [ledger.get("cells", {}).get(lane, {}).get(item, {}).get("outcome")
                for lane in LANES for item in ITEMS]
    state = ledger.get("state")
    revision = ledger.get("revision")
    if isinstance(revision, int) and revision > 6:
        errors.append("dispatch: revision exceeds the six-cell attempt bound")
    if revision == 0:
        if ledger.get("previous_ledger_sha256") != ZERO_SHA256 or ledger.get("previous_ledger_commit") != ZERO_GITSHA:
            errors.append("dispatch: revision zero must use zero previous-ledger bindings")
        if state != "IN_PROGRESS_APPEND_ONLY" or any(outcome != "NOT_DISPATCHED" for outcome in outcomes):
            errors.append("dispatch: revision zero must be an undispatched in-progress grid")
    elif isinstance(revision, int) and revision > 0:
        if previous_ledger is None or previous_ledger_bytes is None:
            errors.append("dispatch: revision requires the previous ledger bytes")
        else:
            if ledger.get("previous_ledger_sha256") != sha256(previous_ledger_bytes):
                errors.append("dispatch: previous ledger hash mismatch")
            previous_commit = ledger.get("previous_ledger_commit", "")
            if previous_ledger.get("ledger_path") != ledger_path:
                errors.append("dispatch: ledger path changed across revisions")
            if previous_ledger.get("preregistration_path") != preregistration_path:
                errors.append("dispatch: preregistration path changed across revisions")
            errors.extend(_commit_blob_errors(
                repository, previous_commit, ledger_path, previous_ledger_bytes,
                "dispatch previous-ledger binding"))
            errors.extend(_ancestor_errors(
                repository, previous_commit, ledger_commit,
                "dispatch previous-to-current ledger"))
            if previous_ledger.get("attempt_id") != ledger.get("attempt_id"):
                errors.append("dispatch: previous ledger attempt mismatch")
            if previous_ledger.get("revision") != revision - 1:
                errors.append("dispatch: revision is not monotonic")
            if previous_ledger.get("state") != "IN_PROGRESS_APPEND_ONLY":
                errors.append("dispatch: sealed ledger is terminal and cannot be revised")
            changed = 0
            for lane in LANES:
                for item in ITEMS:
                    before = previous_ledger.get("cells", {}).get(lane, {}).get(item, {})
                    after = ledger.get("cells", {}).get(lane, {}).get(item, {})
                    if before != after:
                        changed += 1
                    if before.get("outcome") != "NOT_DISPATCHED" and before != after:
                        errors.append(f"dispatch: terminal cell was rewritten: {lane}/{item}")
            if changed == 0:
                errors.append("dispatch: append-only revision changes no cell")
    try:
        successor_hashes = _successor_hashes_on_canonical_main(
            repository,
            canonical_commit,
            preregistration_commit if revision == 0 else ledger.get("previous_ledger_commit", ""),
            ledger_path,
            ledger,
        )
    except Exception as exc:
        errors.append(f"dispatch: canonical successor history unavailable: {type(exc).__name__}")
    else:
        if sha256(ledger_bytes) not in successor_hashes:
            errors.append("dispatch: ledger is not the canonical successor content")
        if len(successor_hashes) > 1:
            errors.append("dispatch: competing canonical successor contents void the attempt")
    if state == "SEALED_COMPLETE" and any(outcome != "COMPLETED" for outcome in outcomes):
        errors.append("dispatch: SEALED_COMPLETE requires six completed cells")
    if state == "SEALED_PARTIAL_UNPAIRED":
        if any(outcome == "NOT_DISPATCHED" for outcome in outcomes):
            errors.append("dispatch: sealed attempt may not omit a dispatch outcome")
        if all(outcome == "COMPLETED" for outcome in outcomes):
            errors.append("dispatch: partial attempt must contain a failure outcome")
    return errors


def validate_public_receipt_shape(value: dict[str, Any]) -> list[str]:
    errors = admission.schema_errors(value, _schema("public"), label="public_receipt")
    exposed = PUBLIC_FORBIDDEN_KEYS.intersection(_walk_keys(value))
    if exposed:
        errors.append("public_receipt: content-bearing or secret field exposed")
    lane = value.get("lane")
    instrument = value.get("instrument", {})
    if lane in EXPECTED_INSTRUMENT:
        expected = EXPECTED_INSTRUMENT[lane]
        actual = (instrument.get("provider_lineage"), instrument.get("model"), instrument.get("effort"))
        if actual != expected:
            errors.append("public_receipt: instrument does not match lane")
    return errors


def _payload_semantics(payload: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    findings = payload.get("atomic_findings", [])
    if payload.get("response_disposition") == "B2_CANDIDATE_RESIDUE":
        if not any(row.get("disposition") == "B2_CANDIDATE_RESIDUE" for row in findings if isinstance(row, dict)):
            errors.append(f"{label}: candidate disposition lacks candidate finding")
    return errors


def _packet_git_errors(repo: Path, commit: str, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    paths = manifest.get("paths", {})
    packet_rel = paths.get("packet_manifest", "")
    export_rel = paths.get("export_receipt", "")
    try:
        packet_bytes = git_bytes(repo, commit, packet_rel)
        packet = loads(packet_bytes)
        export = loads(git_bytes(repo, commit, export_rel))
        packet_base = _safe_rel(packet_rel).parent
    except Exception as exc:
        return [f"private packet artifacts unavailable or malformed: {type(exc).__name__}"]
    if sha256(packet_bytes) != manifest.get("packet_sha256"):
        errors.append("private packet manifest hash mismatch")
    if packet.get("schema") != "tier-bench/arc-d-b2-packet@1":
        errors.append("private packet schema mismatch")
    listed = {row.get("path"): row for row in packet.get("files", []) if isinstance(row, dict)}
    expected = packet_validator.EXPECTED_NAMES - {"PACKET.json"}
    if set(listed) != expected:
        errors.append("private packet file allowlist mismatch")
    for name in expected:
        row = listed.get(name, {})
        rel = (packet_base / name).as_posix()
        try:
            content = git_bytes(repo, commit, rel)
        except Exception:
            errors.append(f"private packet listed file missing: {name}")
            continue
        if len(content) != row.get("bytes") or sha256(content) != row.get("sha256"):
            errors.append(f"private packet listed file binding mismatch: {name}")
    if export.get("packet_sha256") != sha256(packet_bytes):
        errors.append("private export receipt packet hash mismatch")
    if export.get("official_dispatch_permitted") is not True:
        errors.append("private export receipt was not authorized after activation")
    if export.get("response_text_displayed_to_driver") is not False:
        errors.append("private export receipt lacks response-blind attestation")
    for key in ("item_id", "prompt_sha256", "response_sha256"):
        if packet.get(key) != manifest.get(key) or export.get(key) != manifest.get(key):
            errors.append(f"private packet/export binding mismatch: {key}")
    try:
        charter = git_bytes(repo, commit, (packet_base / "CHARTER.json").as_posix())
        if sha256(charter) != PARENT_CHARTER_SHA256:
            errors.append("private packet charter differs from ratified bytes")
    except Exception:
        errors.append("private packet charter unavailable")
    return errors


def validate_private_bundle(
    repository: Path,
    commit: str,
    manifest_path: str,
    *,
    public_receipt: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    try:
        manifest_bytes = git_bytes(repository, commit, manifest_path)
        manifest = loads(manifest_bytes)
        tree = git_tree(repository, commit)
    except Exception as exc:
        return [f"private manifest unavailable or malformed: {type(exc).__name__}"], None
    errors.extend(admission.schema_errors(manifest, _schema("private_bundle"), label="private_manifest"))
    if manifest.get("bundle_state") != "PRIVATE_SEALED":
        errors.append("private_manifest: bundle is not privately sealed")
    artifacts = manifest.get("artifacts", [])
    artifact_rows = {row.get("path"): row for row in artifacts if isinstance(row, dict)}
    if len(artifact_rows) != len(artifacts):
        errors.append("private_manifest: duplicate artifact paths")
    required_paths = set(manifest.get("paths", {}).values())
    if not required_paths.issubset(artifact_rows):
        errors.append("private_manifest: required path missing from artifact bindings")
    manifest_parent = _safe_rel(manifest_path).parent
    for path, row in artifact_rows.items():
        try:
            rel = _safe_rel(path)
            if manifest_parent not in (rel, *rel.parents):
                errors.append("private_manifest: artifact escapes bundle directory")
            content = git_bytes(repository, commit, path)
        except Exception:
            errors.append("private_manifest: bound artifact unavailable")
            continue
        if len(content) != row.get("bytes") or sha256(content) != row.get("sha256"):
            errors.append("private_manifest: artifact hash/size mismatch")
    errors.extend(_packet_git_errors(repository, commit, manifest))

    paths = manifest.get("paths", {})
    try:
        raw_bytes = git_bytes(repository, commit, paths["raw_grade"])
        stripped = raw_bytes.strip()
        if not stripped.startswith(b"{") or not stripped.endswith(b"}"):
            errors.append("private raw grade is not one bare JSON object")
        raw_payload = loads(stripped)
        payload_bytes = git_bytes(repository, commit, paths["grade_payload"])
        payload = loads(payload_bytes)
        grade_receipt_bytes = git_bytes(repository, commit, paths["grade_receipt"])
        grade_receipt = loads(grade_receipt_bytes)
    except Exception as exc:
        return errors + [f"private grade artifacts malformed: {type(exc).__name__}"], manifest
    if raw_payload != payload:
        errors.append("private parsed payload differs from raw grade object")
    errors.extend(admission.schema_errors(payload, _schema("payload"), label="grade_payload"))
    errors.extend(_payload_semantics(payload, "grade_payload"))
    errors.extend(admission.schema_errors(grade_receipt, _schema("grade_receipt"), label="grade_receipt"))
    errors.extend(_payload_semantics(grade_receipt, "grade_receipt"))
    if grade_receipt.get("atomic_findings") != payload.get("atomic_findings") or grade_receipt.get("response_disposition") != payload.get("response_disposition"):
        errors.append("private grade receipt differs from parsed payload")
    if grade_receipt.get("raw_grade_sha256") != sha256(raw_bytes):
        errors.append("private grade receipt raw carrier hash mismatch")
    for key in ("item_id", "packet_sha256", "prompt_sha256", "response_sha256"):
        if grade_receipt.get(key) != manifest.get(key):
            errors.append(f"private grade receipt/manifest mismatch: {key}")
    lane = manifest.get("lane")
    grader = grade_receipt.get("grader", {})
    instrument = manifest.get("instrument", {})
    if lane in EXPECTED_INSTRUMENT:
        expected = EXPECTED_INSTRUMENT[lane]
        actual = (grader.get("provider_lineage"), grader.get("model"), grader.get("effort"))
        if actual != expected or grader.get("grade_id") != lane:
            errors.append("private grade receipt instrument does not match lane")
        manifest_actual = (instrument.get("provider_lineage"), instrument.get("model"), instrument.get("effort"))
        if manifest_actual != expected:
            errors.append("private manifest instrument does not match lane")
    if sha256(str(grader.get("session_id", "")).encode("utf-8")) != instrument.get("session_id_sha256"):
        errors.append("private session identity hash mismatch")
    try:
        chronology = manifest["chronology"]
        if not (_datetime(chronology["dispatched_at"]) <= _datetime(chronology["started_at"]) <= _datetime(chronology["sealed_at"])):
            errors.append("private chronology is not monotonic")
    except Exception:
        errors.append("private chronology is invalid")

    if public_receipt is not None:
        errors.extend(validate_public_receipt_shape(public_receipt))
        for key in (
            "attempt_id", "lane", "item_id", "parent_charter_sha256", "amendment_sha256",
            "custody_profile_sha256", "activation_commit", "preregistration_manifest_sha256",
            "preregistration_commit", "dispatch_ledger_sha256", "dispatch_ledger_commit",
            "packet_sha256", "prompt_sha256", "response_sha256",
        ):
            if public_receipt.get(key) != manifest.get(key):
                errors.append(f"private-to-public binding mismatch: {key}")
        private = public_receipt.get("private_bundle", {})
        expected_private = {
            "object_id": commit,
            "tree_id": tree,
            "bundle_path_sha256": sha256(manifest_parent.as_posix().encode("utf-8")),
            "manifest_sha256": sha256(manifest_bytes),
            "manifest_bytes": len(manifest_bytes),
            "raw_grade_sha256": sha256(raw_bytes),
            "payload_sha256": sha256(payload_bytes),
            "grade_receipt_sha256": sha256(grade_receipt_bytes),
            "session_evidence_sha256": artifact_rows.get(paths.get("session_evidence"), {}).get("sha256"),
            "session_id_sha256": instrument.get("session_id_sha256"),
        }
        for key, expected in expected_private.items():
            if private.get(key) != expected:
                errors.append(f"private-to-public derived commitment mismatch: {key}")
    return errors, manifest


def validate_audit_receipt(
    value: dict[str, Any],
    profile: dict[str, Any],
    private_manifest: dict[str, Any],
    *,
    profile_bytes: bytes,
    private_commit: str,
    private_tree: str,
    private_manifest_path: str,
    private_manifest_bytes: bytes,
    authentication_verified: bool,
) -> list[str]:
    errors = admission.schema_errors(value, _schema("audit"), label="audit")
    profile_hash = sha256(profile_bytes)
    if private_manifest.get("custody_profile_sha256") != profile_hash or value.get("custody_profile_sha256") != profile_hash:
        errors.append("audit: custody profile hash mismatch")
    if value.get("verifier_id") != profile.get("roles", {}).get("verifier_id"):
        errors.append("audit: verifier differs from custody designation")
    auth = value.get("authentication", {})
    profile_auth = profile.get("audit", {})
    if auth.get("method") != profile_auth.get("authentication") or auth.get("identity") != profile_auth.get("authentication_identity"):
        errors.append("audit: authenticated identity differs from custody profile")
    if not authentication_verified:
        errors.append("audit: authentication evidence was not cryptographically verified")
    private_object = value.get("private_object", {})
    lane = private_manifest.get("lane")
    expected_venue = profile.get("lanes", {}).get(lane, {}).get("opaque_venue_id")
    expected_private = {
        "opaque_venue_id": expected_venue,
        "commit_id": private_commit,
        "tree_id": private_tree,
        "manifest_path_sha256": sha256(private_manifest_path.encode("utf-8")),
        "manifest_sha256": sha256(private_manifest_bytes),
    }
    for key, expected in expected_private.items():
        if private_object.get(key) != expected:
            errors.append(f"audit private object mismatch: {key}")
    profile_validator = profile.get("audit", {})
    audit_validator = value.get("validator", {})
    for key in ("path", "sha256"):
        profile_key = "validator_path" if key == "path" else "validator_sha256"
        if audit_validator.get(key) != profile_validator.get(profile_key):
            errors.append(f"audit validator differs from profile: {key}")
    if audit_validator.get("commit") != profile_validator.get("validator_commit"):
        errors.append("audit validator differs from profile: commit")
    for key in (
        "attempt_id", "lane", "item_id", "custody_profile_sha256", "activation_commit",
        "preregistration_manifest_sha256", "dispatch_ledger_sha256",
    ):
        if value.get(key) != private_manifest.get(key):
            errors.append(f"audit/private manifest mismatch: {key}")
    if value.get("result") == "PASS":
        if value.get("raw_bytes_accessed") is not True:
            errors.append("audit PASS requires raw private read access")
        if value.get("error_commitment_sha256") != EMPTY_SHA256:
            errors.append("audit PASS requires the empty error commitment")
    return errors


def validate_public_audit_binding(
    public_receipt: dict[str, Any],
    audit_receipt: dict[str, Any],
    audit_receipt_bytes: bytes,
) -> list[str]:
    errors: list[str] = []
    public_audit = public_receipt.get("audit", {})
    if public_audit.get("audit_receipt_sha256") != sha256(audit_receipt_bytes):
        errors.append("public receipt does not bind the exact audit receipt")
    if public_audit.get("verifier_id") != audit_receipt.get("verifier_id"):
        errors.append("public receipt verifier differs from audit receipt")
    if public_audit.get("authentication") != audit_receipt.get("authentication", {}).get("method"):
        errors.append("public receipt authentication method differs from audit receipt")
    if public_audit.get("authentication_evidence_sha256") != audit_receipt.get("authentication", {}).get("evidence_sha256"):
        errors.append("public receipt authentication evidence differs from audit receipt")
    if public_audit.get("validator_sha256") != audit_receipt.get("validator", {}).get("sha256"):
        errors.append("public receipt validator differs from audit receipt")
    if public_audit.get("result") != audit_receipt.get("result"):
        errors.append("public receipt audit result differs from audit receipt")
    if public_audit.get("raw_bytes_accessed") != audit_receipt.get("raw_bytes_accessed"):
        errors.append("public receipt raw-read attestation differs from audit receipt")
    public_private = public_receipt.get("private_bundle", {})
    audit_private = audit_receipt.get("private_object", {})
    for public_key, audit_key in (
        ("opaque_venue_id", "opaque_venue_id"),
        ("object_id", "commit_id"),
        ("tree_id", "tree_id"),
        ("manifest_sha256", "manifest_sha256"),
    ):
        if public_private.get(public_key) != audit_private.get(audit_key):
            errors.append(f"public receipt private object differs from audit receipt: {public_key}")
    return errors


def verify_audit_authentication(
    profile: dict[str, Any],
    audit_receipt: dict[str, Any],
    audit_receipt_path: Path,
    evidence_path: Path,
    *,
    signed_repository: Path | None = None,
) -> list[str]:
    auth = audit_receipt.get("authentication", {})
    if not evidence_path.is_file() or evidence_path.is_symlink():
        return ["audit authentication evidence is unavailable"]
    if auth.get("evidence_sha256") != file_sha256(evidence_path):
        return ["audit authentication evidence hash mismatch"]
    if auth.get("evidence_path_sha256") != sha256(evidence_path.name.encode("utf-8")):
        return ["audit authentication evidence path commitment mismatch"]
    profile_auth = profile.get("audit", {})
    if auth.get("method") == "github_actions_oidc":
        return audit_auth.verify_github_actions_oidc(
            audit_receipt_path,
            evidence_path,
            profile_auth.get("authentication_repository", ""),
            profile_auth.get("authentication_identity", ""),
            auth.get("subject_commit"),
        )
    if auth.get("method") == "signed_commit":
        if signed_repository is None:
            return ["signed audit verification requires the audit repository"]
        try:
            committed_audit = git_bytes(
                signed_repository,
                auth.get("subject_commit", ""),
                auth.get("subject_path", ""),
            )
        except Exception:
            return ["signed audit commit does not contain the declared audit receipt"]
        if committed_audit != audit_receipt_path.read_bytes():
            return ["signed audit commit subject bytes differ from the audit receipt"]
        return audit_auth.verify_signed_commit(
            signed_repository,
            auth.get("subject_commit", ""),
            profile_auth.get("authentication_identity", ""),
        )
    return ["unsupported audit authentication method"]


def validate_dispatch_chain(
    ledger: dict[str, Any],
    ledger_bytes: bytes,
    preregistration: dict[str, Any],
    preregistration_bytes: bytes,
    *,
    repository: Path,
    ledger_commit: str,
    canonical_commit: str,
) -> list[str]:
    errors: list[str] = []
    current = ledger
    current_bytes = ledger_bytes
    current_commit = ledger_commit
    seen: set[str] = set()
    while True:
        if current_commit in seen:
            return errors + ["dispatch chain: commit cycle detected"]
        seen.add(current_commit)
        revision = current.get("revision")
        if revision == 0:
            errors.extend(validate_dispatch(
                current, preregistration, preregistration_bytes,
                ledger_bytes=current_bytes,
                repository=repository,
                ledger_commit=current_commit,
                canonical_commit=canonical_commit,
            ))
            return errors
        if not isinstance(revision, int) or revision < 1 or revision > 6:
            return errors + ["dispatch chain: revision is outside the six-cell bound"]
        previous_commit = current.get("previous_ledger_commit", "")
        ledger_path = current.get("ledger_path", "")
        try:
            previous_bytes = git_bytes(repository, previous_commit, ledger_path)
            previous = loads(previous_bytes)
        except Exception as exc:
            return errors + [f"dispatch chain: previous ledger unavailable: {type(exc).__name__}"]
        errors.extend(validate_dispatch(
            current, preregistration, preregistration_bytes,
            ledger_bytes=current_bytes,
            repository=repository,
            ledger_commit=current_commit,
            canonical_commit=canonical_commit,
            previous_ledger=previous,
            previous_ledger_bytes=previous_bytes,
        ))
        current = previous
        current_bytes = previous_bytes
        current_commit = previous_commit


def validate_batch(
    value: dict[str, Any],
    receipt_root: Path,
    preregistration: dict[str, Any],
    preregistration_bytes: bytes,
    dispatch_ledger: dict[str, Any],
    dispatch_ledger_bytes: bytes,
    *,
    repository: Path,
    canonical_commit: str,
) -> list[str]:
    errors = admission.schema_errors(value, _schema("batch"), label="batch")
    if value.get("amendment_sha256") != AMENDMENT_SHA256:
        errors.append("batch: amendment hash differs from adopted authority")
    common = (
        "attempt_id", "amendment_sha256", "custody_profile_sha256", "activation_commit",
        "preregistration_manifest_sha256", "preregistration_commit",
        "dispatch_ledger_sha256", "dispatch_ledger_commit",
    )
    if value.get("preregistration_manifest_sha256") != sha256(preregistration_bytes):
        errors.append("batch: preregistration hash mismatch")
    if value.get("dispatch_ledger_sha256") != sha256(dispatch_ledger_bytes):
        errors.append("batch: dispatch ledger hash mismatch")
    if value.get("preregistration_path") != dispatch_ledger.get("preregistration_path"):
        errors.append("batch: preregistration path differs from dispatch ledger")
    if value.get("dispatch_ledger_path") != dispatch_ledger.get("ledger_path"):
        errors.append("batch: dispatch ledger path mismatch")
    if value.get("preregistration_commit") != dispatch_ledger.get("preregistration_commit"):
        errors.append("batch: preregistration commit differs from dispatch ledger")
    if value.get("attempt_id") != preregistration.get("attempt_id") or value.get("attempt_id") != dispatch_ledger.get("attempt_id"):
        errors.append("batch: attempt identity differs across preregistration or dispatch")
    if dispatch_ledger.get("state") != "SEALED_COMPLETE":
        errors.append("batch: final dispatch ledger is not SEALED_COMPLETE")
    errors.extend(validate_dispatch_chain(
        dispatch_ledger,
        dispatch_ledger_bytes,
        preregistration,
        preregistration_bytes,
        repository=repository,
        ledger_commit=value.get("dispatch_ledger_commit", ""),
        canonical_commit=canonical_commit,
    ))
    seen: set[str] = set()
    packet_by_lane: dict[str, dict[str, str]] = {lane: {} for lane in LANES}
    for lane in LANES:
        for item in ITEMS:
            row = value.get("receipts", {}).get(lane, {}).get(item, {})
            rel = row.get("path", "")
            if rel in seen:
                errors.append("batch: duplicate public receipt path")
            seen.add(rel)
            try:
                safe = _safe_rel(rel)
                path = (receipt_root / Path(*safe.parts)).resolve()
                if receipt_root.resolve() not in path.parents:
                    raise ValueError
                data = path.read_bytes()
                receipt = loads(data)
            except Exception:
                errors.append(f"batch: public receipt unavailable for {lane}/{item}")
                continue
            if row.get("sha256") != sha256(data):
                errors.append(f"batch: public receipt hash mismatch for {lane}/{item}")
            errors.extend(validate_public_receipt_shape(receipt))
            if receipt.get("lane") != lane or receipt.get("item_id") != item:
                errors.append(f"batch: receipt occupies wrong grid cell {lane}/{item}")
            for key in common:
                if receipt.get(key) != value.get(key):
                    errors.append(f"batch: common binding mismatch for {lane}/{item}: {key}")
            preregistered = preregistration.get("items", {}).get(item, {})
            for key in ("packet_sha256", "prompt_sha256", "response_sha256"):
                if receipt.get(key) != preregistered.get(key):
                    errors.append(f"batch: {key} differs from preregistration for {lane}/{item}")
            packet_by_lane[lane][item] = receipt.get("packet_sha256", "")
    for item in ITEMS:
        if packet_by_lane["grade_a"].get(item) != packet_by_lane["grade_b"].get(item):
            errors.append(f"batch: lane packet hashes differ for {item}")
    try:
        seal = value["seal"]
        if _datetime(seal["first_public_disclosure_at"]) <= _datetime(seal["last_private_sealed_at"]):
            errors.append("batch: public disclosure did not follow final private seal")
    except Exception:
        errors.append("batch: seal chronology is invalid")
    return errors


def _print(errors: list[str], success: str) -> int:
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(success)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode")

    sub.add_parser("components")
    profile_cmd = sub.add_parser("profile")
    profile_cmd.add_argument("profile", type=Path)
    profile_cmd.add_argument("--preflight", type=Path, required=True)
    activation_cmd = sub.add_parser("activation")
    activation_cmd.add_argument("receipt", type=Path)
    activation_cmd.add_argument("--component-ref", default="HEAD")
    activation_cmd.add_argument("--official", action="store_true")
    prereg_cmd = sub.add_parser("preregistration")
    prereg_cmd.add_argument("receipt", type=Path)
    dispatch_cmd = sub.add_parser("dispatch")
    dispatch_cmd.add_argument("ledger", type=Path)
    dispatch_cmd.add_argument("--preregistration", type=Path, required=True)
    dispatch_cmd.add_argument("--previous-ledger", type=Path)
    dispatch_cmd.add_argument("--repository", type=Path, default=ROOT)
    dispatch_cmd.add_argument("--ledger-commit", required=True)
    public_cmd = sub.add_parser("public-receipt")
    public_cmd.add_argument("receipt", type=Path)
    private_cmd = sub.add_parser("private-bundle")
    private_cmd.add_argument("--repository", type=Path, required=True)
    private_cmd.add_argument("--commit", required=True)
    private_cmd.add_argument("--manifest-path", required=True)
    private_cmd.add_argument("--public-receipt", type=Path)
    audit_cmd = sub.add_parser("audit")
    audit_cmd.add_argument("receipt", type=Path)
    audit_cmd.add_argument("--profile", type=Path, required=True)
    audit_cmd.add_argument("--authentication-evidence", type=Path, required=True)
    audit_cmd.add_argument("--signed-repository", type=Path)
    audit_cmd.add_argument("--private-repository", type=Path, required=True)
    audit_cmd.add_argument("--private-commit", required=True)
    audit_cmd.add_argument("--private-manifest-path", required=True)
    audit_cmd.add_argument("--public-receipt", type=Path, required=True)
    batch_cmd = sub.add_parser("batch")
    batch_cmd.add_argument("receipt", type=Path)
    batch_cmd.add_argument("--receipt-root", type=Path, required=True)
    batch_cmd.add_argument("--preregistration", type=Path, required=True)
    batch_cmd.add_argument("--dispatch-ledger", type=Path, required=True)
    batch_cmd.add_argument("--repository", type=Path, default=ROOT)

    args = parser.parse_args()
    mode = args.mode or "components"
    if mode == "components":
        return _print(component_errors(), "OK: custody-v2 components validate; state=PENDING_DESIGNATION_AND_PRIVATE_PREFLIGHT")
    if mode == "profile":
        try:
            profile_bytes = args.profile.read_bytes()
            profile = loads(profile_bytes)
            preflight_bytes = args.preflight.read_bytes()
        except Exception as exc:
            return _print([f"profile inputs malformed: {type(exc).__name__}"], "")
        return _print(validate_profile(profile, preflight_bytes), "CUSTODY_PROFILE_VALID_PENDING_ACTIVATION")
    if mode == "activation":
        try:
            receipt = load(args.receipt)
        except Exception as exc:
            return _print([f"activation receipt malformed: {type(exc).__name__}"], "")
        errors, state = validate_activation(receipt, component_ref=args.component_ref, official=args.official)
        return _print(errors, state)
    if mode == "preregistration":
        return _print(validate_preregistration(load(args.receipt)), "PREREGISTRATION_VALID")
    if mode == "dispatch":
        prereg_bytes = args.preregistration.read_bytes()
        ledger_bytes = args.ledger.read_bytes()
        previous_bytes = args.previous_ledger.read_bytes() if args.previous_ledger else None
        previous = loads(previous_bytes) if previous_bytes is not None else None
        try:
            trusted_main = canonical_main_commit()
        except Exception as exc:
            return _print([f"dispatch cannot resolve pinned GitHub authority: {type(exc).__name__}"], "")
        return _print(
            validate_dispatch(
                loads(ledger_bytes),
                loads(prereg_bytes),
                prereg_bytes,
                ledger_bytes=ledger_bytes,
                repository=args.repository,
                ledger_commit=args.ledger_commit,
                canonical_commit=trusted_main,
                previous_ledger=previous,
                previous_ledger_bytes=previous_bytes,
            ),
            "DISPATCH_LEDGER_VALID",
        )
    if mode == "public-receipt":
        return _print(validate_public_receipt_shape(load(args.receipt)), "PUBLIC_COMMITMENT_SHAPE_VALID")
    if mode == "private-bundle":
        public = load(args.public_receipt) if args.public_receipt else None
        errors, _ = validate_private_bundle(
            args.repository,
            args.commit,
            args.manifest_path,
            public_receipt=public,
        )
        return _print(errors, "PRIVATE_BUNDLE_VALID")
    if mode == "audit":
        try:
            audit_bytes = args.receipt.read_bytes()
            audit_receipt = loads(audit_bytes)
            profile_bytes = args.profile.read_bytes()
            profile = loads(profile_bytes)
            public_bytes = args.public_receipt.read_bytes()
            public_receipt = loads(public_bytes)
        except Exception as exc:
            return _print([f"audit inputs malformed: {type(exc).__name__}"], "")
        private_errors, private_manifest = validate_private_bundle(
            args.private_repository,
            args.private_commit,
            args.private_manifest_path,
            public_receipt=public_receipt,
        )
        auth_errors = verify_audit_authentication(
            profile,
            audit_receipt,
            args.receipt,
            args.authentication_evidence,
            signed_repository=args.signed_repository,
        )
        if private_manifest is None:
            audit_errors = []
        else:
            try:
                private_tree = git_tree(args.private_repository, args.private_commit)
                private_manifest_bytes = git_bytes(
                    args.private_repository, args.private_commit, args.private_manifest_path)
            except Exception as exc:
                audit_errors = [f"audit private identity unavailable: {type(exc).__name__}"]
            else:
                audit_errors = validate_audit_receipt(
                    audit_receipt,
                    profile,
                    private_manifest,
                    profile_bytes=profile_bytes,
                    private_commit=args.private_commit,
                    private_tree=private_tree,
                    private_manifest_path=args.private_manifest_path,
                    private_manifest_bytes=private_manifest_bytes,
                    authentication_verified=not auth_errors,
                )
        binding_errors = validate_public_audit_binding(public_receipt, audit_receipt, audit_bytes)
        return _print(
            private_errors + auth_errors + audit_errors + binding_errors,
            "AUTHENTICATED_PRIVATE_AUDIT_VALID",
        )
    try:
        preregistration_bytes = args.preregistration.read_bytes()
        dispatch_ledger_bytes = args.dispatch_ledger.read_bytes()
        trusted_main = canonical_main_commit()
    except Exception as exc:
        return _print([f"batch inputs or pinned GitHub authority unavailable: {type(exc).__name__}"], "")
    return _print(validate_batch(
        load(args.receipt),
        args.receipt_root,
        loads(preregistration_bytes),
        preregistration_bytes,
        loads(dispatch_ledger_bytes),
        dispatch_ledger_bytes,
        repository=args.repository,
        canonical_commit=trusted_main,
    ), "PUBLIC_BATCH_COMMITMENT_SHAPE_VALID")


if __name__ == "__main__":
    raise SystemExit(main())
