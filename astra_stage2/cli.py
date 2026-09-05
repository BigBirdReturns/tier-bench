"""Command-line surface for the provider-free Stage 2 calibration scaffold."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from .calibration import derive_calibration_result, validate_calibration_result
from .canonical import (
    Stage2Error,
    sha256_bytes,
    sha256_file,
    sha256_object,
    strict_json_load,
    strict_jsonl_load,
    without_field,
    write_json_atomic,
    write_jsonl_atomic,
)
from .contracts import (
    bind_empirical_control_manifest,
    validate_control_manifest,
    validate_generator_manifest,
    validate_observations,
    validate_plan,
    verify_stage1_blobs,
)
from .generator import (
    EXPECTED_CASE_COUNT,
    EXPECTED_OBSERVATION_COUNT,
    build_calibration_plan,
    build_fixture_observations,
    build_generator_manifest,
    build_plan_index,
    empirical_control_template,
    fixture_control_manifest,
    reconstruct_task,
)

TEST_RE = re.compile(r"^Ran\s+(\d+)\s+tests?\s+in\s+", re.MULTILINE)
PROVIDER_CREDENTIAL_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
)
FORBIDDEN_PUBLIC_MARKERS = (
    b"SENSITIVE_CANARY",
    b"PRIVATE_TRANSCRIPT_CANARY",
    b"Reply with",
)


def _load_generator(path: Path) -> dict[str, Any]:
    return validate_generator_manifest(strict_json_load(path))


def _load_control(path: Path, *, empirical_bound: bool = False) -> dict[str, Any]:
    return validate_control_manifest(strict_json_load(path), require_bound_empirical=empirical_bound)


def _load_plan(
    path: Path, generator: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    return validate_plan(strict_json_load(path), generator, control)


def _read_changed_paths(path: Path) -> list[str]:
    raw = path.read_bytes()
    values = sorted({piece.decode("utf-8") for piece in raw.split(b"\0") if piece})
    if not values:
        raise Stage2Error("changed-path inventory is empty")
    for value in values:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise Stage2Error(f"unsafe changed path: {value}")
    return values


def _test_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    matches = TEST_RE.findall(text)
    if len(matches) != 1:
        raise Stage2Error("test log must contain exactly one unittest denominator")
    count = int(matches[0])
    if count <= 0:
        raise Stage2Error("test denominator must be positive")
    return count


def _scan_public_files(paths: list[Path]) -> None:
    for path in paths:
        data = path.read_bytes()
        for marker in FORBIDDEN_PUBLIC_MARKERS:
            if marker in data:
                raise Stage2Error(
                    f"public evidence {path} retained forbidden marker {marker.decode('ascii')}"
                )


def _qualification(args: argparse.Namespace) -> dict[str, Any]:
    generator = _load_generator(args.generator_manifest)
    control = _load_control(args.control_manifest)
    plan = _load_plan(args.plan, generator, control)
    fixture_observations = strict_jsonl_load(args.fixture_observations)
    fixture_result = validate_calibration_result(
        strict_json_load(args.fixture_result),
        generator_manifest=generator,
        control_manifest=control,
        plan=plan,
        observations=fixture_observations,
        repo_root=args.repo_root,
    )
    if fixture_result["state"] != "FIXTURE_CONFORMANCE_ONLY":
        raise Stage2Error("provider-free qualification requires fixture-only result")
    if fixture_result["observation_count"] != EXPECTED_OBSERVATION_COUNT:
        raise Stage2Error("fixture result denominator mismatch")
    stage1_blobs = verify_stage1_blobs(args.repo_root)
    if fixture_result.get("stage1_custody", {}).get("blobs") != stage1_blobs:
        raise Stage2Error("fixture result is not bound to the qualified Stage 1 blob set")
    changed_paths = _read_changed_paths(args.changed_paths_z)
    tests = _test_count(args.test_log)
    if tests != 31:
        raise Stage2Error(f"expected 31 adversarial tests, observed {tests}")
    _scan_public_files(
        [
            args.generator_manifest,
            args.control_manifest,
            args.plan,
            args.fixture_observations,
            args.fixture_result,
            args.test_log,
        ]
    )
    credentials = [name for name in PROVIDER_CREDENTIAL_ENV_NAMES if os.environ.get(name)]
    if credentials:
        raise Stage2Error(f"provider credentials present in provider-free qualification: {credentials}")
    source_head = args.source_head.lower()
    tree = args.tree.lower()
    parent = args.parent.lower()
    for label, value in (("source_head", source_head), ("tree", tree), ("parent", parent)):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise Stage2Error(f"{label} must be a 40-hex Git identity")
    receipt: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-scaffold-qualification@1",
        "classification": "PROVIDER_FREE_SCAFFOLD_QUALIFIED_EMPIRICAL_CALIBRATION_PENDING",
        "source": {
            "repository": args.repository,
            "branch": args.branch,
            "source_head_sha": source_head,
            "tree_sha": tree,
            "parent_sha": parent,
            "changed_path_count": len(changed_paths),
            "changed_paths": changed_paths,
            "changed_paths_sha256_nul": sha256_bytes(
                b"".join(path.encode("utf-8") + b"\0" for path in changed_paths)
            ),
            "stage1_blobs": stage1_blobs,
        },
        "conformance": {
            "test_total": tests,
            "generator_case_count": generator["case_count"],
            "calibration_control_count": control["controls"].__len__(),
            "effort_count": plan["effort_count"],
            "planned_observation_count": plan["observation_count"],
            "fixture_result_state": fixture_result["state"],
            "fixture_result_sha256": fixture_result["payload_sha256"],
            "generator_manifest_sha256": generator["payload_sha256"],
            "control_manifest_sha256": control["payload_sha256"],
            "calibration_plan_sha256": plan["payload_sha256"],
            "incorrect_deterministic_answer_refusal": True,
            "unknown_observation_property_refusal": True,
            "stage1_git_object_verification": True,
            "stage1_crlf_portability_witness": True,
            "derive_stage1_custody_binding": True,
            "generator_semantic_identity_pinned": True,
            "stage1_join_ancestry_verified": True,
            "control_sources_pinned": True,
            "plan_observation_ids_reconstructed": True,
            "result_input_graph_rederived": True,
            "observation_set_sha256": fixture_result["observation_set_sha256"],
            "input_binding_sha256": fixture_result["input_binding_sha256"],
        },
        "authority": {
            "sol_calibration_law_blob": "UNBOUND_PENDING_ACTIVE_CLAIM_5516294861",
            "empirical_local_calibration": "NOT_RUN",
            "stage2_numeric_freeze": "PROHIBITED_IN_SCAFFOLD",
            "astra_instrumentation": "NOT_IMPLEMENTED",
            "callable_astra_identity": "UNBOUND",
            "live_provider_dispatch": "PROHIBITED",
            "optional_24_call_block": "DISABLED",
            "merge_authority": "NONE",
            "network_calls": 0,
            "model_calls": 0,
            "provider_spend_usd": 0,
        },
        "environment": {
            "recognized_provider_credentials_present": credentials,
        },
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (
                args.generator_manifest,
                args.control_manifest,
                args.plan,
                args.fixture_observations,
                args.fixture_result,
                args.test_log,
            )
        },
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astra-stage2",
        description="Provider-free Stage 2 calibration scaffold for FRR-ASTRA-1",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("generator-manifest")
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("fixture-control-manifest")
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("empirical-control-template")
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("bind-control-manifest")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("plan")
    command.add_argument("--generator-manifest", type=Path, required=True)
    command.add_argument("--control-manifest", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("plan-index")
    command.add_argument("--generator-manifest", type=Path, required=True)
    command.add_argument("--control-manifest", type=Path, required=True)
    command.add_argument("--plan", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("fixture-observations")
    command.add_argument("--generator-manifest", type=Path, required=True)
    command.add_argument("--control-manifest", type=Path, required=True)
    command.add_argument("--plan", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("derive")
    command.add_argument("--repo-root", type=Path, required=True)
    command.add_argument("--generator-manifest", type=Path, required=True)
    command.add_argument("--control-manifest", type=Path, required=True)
    command.add_argument("--plan", type=Path, required=True)
    command.add_argument("--observations", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("verify-stage1")
    command.add_argument("--repo-root", type=Path, required=True)
    command.add_argument("--out", type=Path)

    command = subparsers.add_parser("reconstruct")
    command.add_argument("--generator-manifest", type=Path, required=True)
    command.add_argument("--case-id", required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("qualify")
    command.add_argument("--repo-root", type=Path, required=True)
    command.add_argument("--repository", required=True)
    command.add_argument("--branch", required=True)
    command.add_argument("--source-head", required=True)
    command.add_argument("--tree", required=True)
    command.add_argument("--parent", required=True)
    command.add_argument("--changed-paths-z", type=Path, required=True)
    command.add_argument("--test-log", type=Path, required=True)
    command.add_argument("--generator-manifest", type=Path, required=True)
    command.add_argument("--control-manifest", type=Path, required=True)
    command.add_argument("--plan", type=Path, required=True)
    command.add_argument("--fixture-observations", type=Path, required=True)
    command.add_argument("--fixture-result", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = subparsers.add_parser("verify-qualification")
    command.add_argument("--input", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generator-manifest":
            write_json_atomic(args.out, build_generator_manifest())
        elif args.command == "fixture-control-manifest":
            write_json_atomic(args.out, fixture_control_manifest())
        elif args.command == "empirical-control-template":
            write_json_atomic(args.out, empirical_control_template())
        elif args.command == "bind-control-manifest":
            write_json_atomic(args.out, bind_empirical_control_manifest(strict_json_load(args.input)))
        elif args.command == "plan":
            generator = _load_generator(args.generator_manifest)
            control = _load_control(args.control_manifest)
            write_json_atomic(args.out, build_calibration_plan(generator, control))
        elif args.command == "plan-index":
            generator = _load_generator(args.generator_manifest)
            control = _load_control(args.control_manifest)
            plan = _load_plan(args.plan, generator, control)
            write_json_atomic(args.out, build_plan_index(plan))
        elif args.command == "fixture-observations":
            generator = _load_generator(args.generator_manifest)
            control = _load_control(args.control_manifest)
            plan = _load_plan(args.plan, generator, control)
            write_jsonl_atomic(args.out, build_fixture_observations(plan))
        elif args.command == "derive":
            generator = _load_generator(args.generator_manifest)
            raw_control = strict_json_load(args.control_manifest)
            control = validate_control_manifest(
                raw_control,
                require_bound_empirical=raw_control.get("evidence_class") == "empirical_local",
            )
            plan = _load_plan(args.plan, generator, control)
            observations = strict_jsonl_load(args.observations)
            write_json_atomic(
                args.out,
                derive_calibration_result(
                    observations,
                    plan,
                    control,
                    generator_manifest=generator,
                    repo_root=args.repo_root,
                ),
            )
        elif args.command == "verify-stage1":
            result = {
                "schema": "tier-bench/astra-stage2-stage1-blob-verification@1",
                "stage1_blobs": verify_stage1_blobs(args.repo_root),
            }
            result["payload_sha256"] = sha256_object(result)
            if args.out:
                write_json_atomic(args.out, result)
            else:
                print(result["payload_sha256"])
        elif args.command == "reconstruct":
            generator = _load_generator(args.generator_manifest)
            cases = {case["case_id"]: case for case in generator["cases"]}
            if args.case_id not in cases:
                raise Stage2Error("case id is not present in frozen generator manifest")
            write_json_atomic(args.out, reconstruct_task(cases[args.case_id]))
        elif args.command == "qualify":
            write_json_atomic(args.out, _qualification(args))
        elif args.command == "verify-qualification":
            receipt = strict_json_load(args.input)
            if receipt.get("schema") != "tier-bench/astra-stage2-scaffold-qualification@1":
                raise Stage2Error("unexpected qualification schema")
            if receipt.get("payload_sha256") != sha256_object(without_field(receipt, "payload_sha256")):
                raise Stage2Error("qualification self-hash mismatch")
            if receipt.get("authority", {}).get("stage2_numeric_freeze") != "PROHIBITED_IN_SCAFFOLD":
                raise Stage2Error("qualification widened Stage 2 authority")
        else:
            raise Stage2Error(f"unhandled command: {args.command}")
        return 0
    except Stage2Error as exc:
        print(f"astra-stage2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
