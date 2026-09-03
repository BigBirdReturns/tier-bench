from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any


class AuditFailure(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_object(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AuditFailure(detail)


def load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def zip_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), f"duplicate ZIP member in {path.name}")
        return {name: archive.read(name) for name in names if not name.endswith("/")}


def require_member(members: dict[str, bytes], name: str) -> bytes:
    require(name in members, f"required artifact member is absent: {name}")
    return members[name]


def verify_sha256sums(members: dict[str, bytes]) -> dict[str, str]:
    raw = require_member(members, "SHA256SUMS").decode("utf-8")
    observed: dict[str, str] = {}
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(match is not None, f"invalid SHA256SUMS line {line_number}")
        digest, name = match.groups()
        require(name != "SHA256SUMS", "SHA256SUMS must not self-reference")
        require(name in members, f"SHA256SUMS names absent member {name}")
        require(sha256_bytes(members[name]) == digest, f"member digest mismatch: {name}")
        observed[name] = digest
    require(observed, "SHA256SUMS is empty")
    return observed


def verify_payload(value: dict[str, Any], label: str) -> str:
    claimed = value.get("payload_sha256")
    require(isinstance(claimed, str) and re.fullmatch(r"[0-9a-f]{64}", claimed) is not None,
            f"{label} payload SHA-256 is absent")
    body = copy.deepcopy(value)
    body.pop("payload_sha256", None)
    require(sha256_object(body) == claimed, f"{label} payload SHA-256 does not reproduce")
    return claimed


def validate_packet(
    qualification: dict[str, Any],
    publication: dict[str, Any],
    windows: dict[str, Any],
    launcher_text: str,
    expected_head: str,
    expected_tree: str,
    expected_run: int,
) -> None:
    source = qualification.get("source", {})
    conformance = qualification.get("conformance", {})
    actual = qualification.get("actual_binding", {})
    authority = qualification.get("authority", {})

    require(qualification.get("run_id") == expected_run, "qualification run substitution")
    require(source.get("head_sha1") == expected_head, "qualification head substitution")
    require(source.get("tree_sha1") == expected_tree, "qualification tree substitution")
    require(source.get("binder_head_sha1") == "af03cef494a509ab7ba5df29fa4b4ccba423f1f8",
            "binder head substitution")
    require(source.get("binder_tree_sha1") == "519ea2f8f448a464e817a024ad8ed1ac64493931",
            "binder tree substitution")

    require(conformance.get("tests") == 27, "qualification test denominator substitution")
    require(conformance.get("binder_tests") == 20, "binder test denominator substitution")
    require(conformance.get("release_tests") == 7, "release test denominator substitution")
    require(conformance.get("linux_tests") == 27, "Linux test denominator substitution")
    require(conformance.get("linux_skipped") == 0, "unexpected Linux skip")
    require(conformance.get("windows_tests") == 27, "Windows test denominator substitution")
    require(conformance.get("windows_skipped") == 1, "Windows skip denominator substitution")
    require(conformance.get("powershell_parse_linux") is True, "Linux parser gate absent")
    require(conformance.get("powershell_parse_windows") is True, "Windows parser gate absent")
    require(conformance.get("windows_preflight_executed") is True, "Windows Preflight absent")
    require(conformance.get("control_roles") == 3, "control denominator substitution")
    require(conformance.get("generator_cases") == 108, "generator denominator substitution")
    require(conformance.get("expected_empirical_observations") == 648,
            "observation denominator substitution")

    require(actual.get("state") == "UNBOUND", "actual control identity authority widened")
    require(actual.get("bound_controls") == 0, "bound-control authority widened")
    require(actual.get("empirical_observations") == 0, "empirical execution authority widened")
    require(authority.get("provider_or_model_calls") == 0, "provider/model call authority widened")
    require(authority.get("empirical_subject_execution") is False,
            "empirical subject execution authority widened")
    require(authority.get("numeric_stage2_freeze") == "NOT_ISSUED", "numeric freeze widened")
    require(authority.get("callable_astra_identity") == "UNBOUND", "Astra identity widened")
    require(authority.get("live_provider_dispatch") == "PROHIBITED", "dispatch widened")
    require(authority.get("optional_24_call_block") == "DISABLED", "optional call block widened")
    require(authority.get("benchmark_verdict_authority") == "NONE", "verdict authority widened")
    require(authority.get("merge_authority") == "NONE", "merge authority widened")

    require(publication.get("workflow_run_id") == expected_run, "publication run substitution")
    require(publication.get("source_head_sha1") == expected_head, "publication head substitution")
    require(publication.get("source_tree_sha1") == expected_tree, "publication tree substitution")
    require(publication.get("qualification_payload_sha256") == qualification.get("payload_sha256"),
            "publication qualification payload substitution")
    require(publication.get("tests") == 27, "publication test denominator substitution")
    require(publication.get("windows_tests") == 27, "publication Windows denominator substitution")
    require(publication.get("windows_skipped") == 1, "publication Windows skip substitution")
    require(publication.get("linux_tests") == 27, "publication Linux denominator substitution")
    require(publication.get("actual_control_identities") == "UNBOUND",
            "publication identity authority widened")
    require(publication.get("provider_or_model_calls") == 0,
            "publication call authority widened")
    require(publication.get("numeric_stage2_freeze") == "NOT_ISSUED",
            "publication freeze authority widened")
    require(publication.get("live_provider_dispatch") == "PROHIBITED",
            "publication dispatch authority widened")
    require(publication.get("merge_authority") == "NONE", "publication merge authority widened")

    require(windows.get("source_head_sha1") == expected_head, "independent Windows head substitution")
    require(windows.get("source_tree_sha1") == expected_tree, "independent Windows tree substitution")
    require(windows.get("tests") == 27, "independent Windows denominator substitution")
    require(windows.get("passed") == 26, "independent Windows pass denominator substitution")
    require(windows.get("skipped") == 1, "independent Windows skip substitution")
    require(windows.get("failed") == 0, "independent Windows failure present")
    require(windows.get("errors") == 0, "independent Windows error present")
    require(windows.get("powershell_parse") == "PASS", "independent Windows parser absent")
    require(windows.get("launcher_preflight") == "PASS", "independent Windows Preflight absent")
    require(windows.get("binder_import_smoke") == "PASS", "binder import smoke absent")
    require(windows.get("binder_execution_cwd") == "PINNED_BINDER_ROOT",
            "binder working-directory proof absent")
    require(windows.get("binder_pythonpath") == "PINNED_BINDER_ROOT",
            "binder import-root proof absent")
    require(windows.get("binder_caller_cwd") == "DELIBERATELY_NON_BINDER",
            "non-binder caller proof absent")
    require(windows.get("preflight_downloads") == 0, "independent Preflight downloaded assets")
    require(windows.get("model_calls") == 0, "independent Preflight executed a model")
    require(windows.get("provider_calls") == 0, "independent Preflight called a provider")
    require(windows.get("actual_executable_control_identities") == "UNBOUND",
            "independent Preflight widened identity authority")

    required_launcher_fragments = (
        "function Invoke-PinnedBinder",
        "$env:PYTHONPATH = $expectedRoot",
        "Push-Location -LiteralPath $expectedRoot",
        "Remove-Item Env:PYTHONPATH",
        "preflight-binder-import-smoke",
        "non-binder-cwd",
        "'-Command', 'template', '-Out', $smokeTemplate",
        "binder_import_smoke = 'PASS'",
        "binder_execution_cwd = 'PINNED_BINDER_ROOT'",
        "binder_pythonpath = 'PINNED_BINDER_ROOT'",
        "${Repository}: expected",
        "REUSE_EXISTING_EXACT_ASSETS",
    )
    for fragment in required_launcher_fragments:
        require(fragment in launcher_text, f"launcher control absent: {fragment}")


def replay_attacks(
    qualification: dict[str, Any],
    publication: dict[str, Any],
    windows: dict[str, Any],
    launcher_text: str,
    expected_head: str,
    expected_tree: str,
    expected_run: int,
) -> list[dict[str, Any]]:
    attacks: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], str]] = []

    q = copy.deepcopy(qualification)
    q["source"]["head_sha1"] = "0" * 40
    attacks.append(("qualification head substitution", q, copy.deepcopy(publication), copy.deepcopy(windows), launcher_text))

    p = copy.deepcopy(publication)
    p["source_tree_sha1"] = "0" * 40
    attacks.append(("publication tree substitution", copy.deepcopy(qualification), p, copy.deepcopy(windows), launcher_text))

    w = copy.deepcopy(windows)
    w["tests"] = 26
    attacks.append(("Windows denominator substitution", copy.deepcopy(qualification), copy.deepcopy(publication), w, launcher_text))

    attacks.append((
        "binder PYTHONPATH removal",
        copy.deepcopy(qualification),
        copy.deepcopy(publication),
        copy.deepcopy(windows),
        launcher_text.replace("$env:PYTHONPATH = $expectedRoot", "$env:PYTHONPATH = $null", 1),
    ))

    w = copy.deepcopy(windows)
    w["binder_caller_cwd"] = "BINDER_ROOT"
    attacks.append(("non-binder caller substitution", copy.deepcopy(qualification), copy.deepcopy(publication), w, launcher_text))

    q = copy.deepcopy(qualification)
    q["actual_binding"]["state"] = "BOUND"
    attacks.append(("identity authority widening", q, copy.deepcopy(publication), copy.deepcopy(windows), launcher_text))

    p = copy.deepcopy(publication)
    p["provider_or_model_calls"] = 1
    attacks.append(("provider-call authority widening", copy.deepcopy(qualification), p, copy.deepcopy(windows), launcher_text))

    results: list[dict[str, Any]] = []
    for label, q_value, p_value, w_value, text_value in attacks:
        try:
            validate_packet(
                q_value,
                p_value,
                w_value,
                text_value,
                expected_head,
                expected_tree,
                expected_run,
            )
        except AuditFailure as exc:
            results.append({
                "label": label,
                "expected": "REFUSAL",
                "observed": "REFUSAL",
                "detail": str(exc),
                "passed": True,
            })
        else:
            results.append({
                "label": label,
                "expected": "REFUSAL",
                "observed": "ACCEPTED",
                "detail": "mutated packet was accepted",
                "passed": False,
            })
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--publication-zip", type=Path, required=True)
    parser.add_argument("--windows-receipt", type=Path, required=True)
    parser.add_argument("--release-head", required=True)
    parser.add_argument("--release-tree", required=True)
    parser.add_argument("--release-run", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    evidence_members = zip_members(args.evidence_zip)
    publication_members = zip_members(args.publication_zip)
    evidence_member_hashes = verify_sha256sums(evidence_members)

    qualification = load_json_bytes(
        require_member(evidence_members, "qualification-receipt.json"),
        "qualification receipt",
    )
    publication = load_json_bytes(
        require_member(publication_members, "publication-index.json"),
        "publication index",
    )
    windows = load_json_bytes(args.windows_receipt.read_bytes(), "Windows audit receipt")
    launcher_bytes = require_member(
        evidence_members,
        "Invoke-AstraStage2ControlIdentityBinding.ps1",
    )
    launcher_text = launcher_bytes.decode("utf-8-sig")

    qualification_payload = verify_payload(qualification, "qualification")
    publication_payload = verify_payload(publication, "publication")
    windows_payload = verify_payload(windows, "Windows audit")

    repository_launcher = (
        args.release_root
        / "scripts"
        / "Invoke-AstraStage2ControlIdentityBinding.ps1"
    ).read_bytes()
    require(repository_launcher == launcher_bytes, "artifact launcher differs from release tree")

    validate_packet(
        qualification,
        publication,
        windows,
        launcher_text,
        args.release_head,
        args.release_tree,
        args.release_run,
    )
    attacks = replay_attacks(
        qualification,
        publication,
        windows,
        launcher_text,
        args.release_head,
        args.release_tree,
        args.release_run,
    )
    failed = sum(not attack["passed"] for attack in attacks)

    result: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-import-root-audit@1",
        "target": {
            "release_head_sha1": args.release_head,
            "release_tree_sha1": args.release_tree,
            "qualification_run": args.release_run,
            "evidence_zip_sha256": sha256_file(args.evidence_zip),
            "publication_zip_sha256": sha256_file(args.publication_zip),
            "qualification_payload_sha256": qualification_payload,
            "publication_payload_sha256": publication_payload,
            "windows_audit_payload_sha256": windows_payload,
        },
        "rederived": {
            "tests": 27,
            "binder_tests": 20,
            "release_tests": 7,
            "windows_tests": 27,
            "windows_passed": 26,
            "windows_skipped": 1,
            "windows_failed": 0,
            "windows_errors": 0,
            "linux_tests": 27,
            "control_roles": 3,
            "generator_cases": 108,
            "expected_empirical_observations": 648,
            "powershell_parse": "PASS",
            "non_binder_cwd_preflight": "PASS",
            "binder_import_smoke": "PASS",
            "binder_execution_cwd": "PINNED_BINDER_ROOT",
            "binder_pythonpath": "PINNED_BINDER_ROOT",
            "actual_executable_control_identities": "UNBOUND",
        },
        "artifacts": {
            "evidence_members": evidence_member_hashes,
            "publication_members": {
                name: {"bytes": len(data), "sha256": sha256_bytes(data)}
                for name, data in sorted(publication_members.items())
            },
        },
        "attack_count": len(attacks),
        "refused_count": sum(attack["observed"] == "REFUSAL" for attack in attacks),
        "failed_count": failed,
        "attacks": attacks,
        "authority": {
            "provider_or_model_calls": 0,
            "empirical_subject_execution": False,
            "actual_executable_control_identities": "UNBOUND",
            "empirical_calibration": "NOT_RUN",
            "numeric_stage2_freeze": "NOT_ISSUED",
            "callable_astra_identity": "UNBOUND",
            "live_provider_dispatch": "PROHIBITED",
            "optional_24_call_block": "DISABLED",
            "benchmark_verdict_authority": "NONE",
            "merge_authority": "NONE",
        },
        "disposition": (
            "PASS_CROSS_PLATFORM_BINDER_IMPORT_ROOT_RELEASE_ONLY"
            if failed == 0
            else "FAIL"
        ),
    }
    result["payload_sha256"] = sha256_object(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
