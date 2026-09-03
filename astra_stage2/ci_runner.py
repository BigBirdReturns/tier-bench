"""Provider-free exact-head CI transaction for the Astra Stage 2 scaffold."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from .calibration import derive_calibration_result
from .canonical import (
    Stage2Error,
    pretty_json_bytes,
    sha256_object,
    strict_json_load,
    write_bytes_atomic,
    write_json_atomic,
    write_jsonl_atomic,
)
from .cli import FORBIDDEN_PUBLIC_MARKERS, _qualification, build_parser as build_cli_parser
from .contracts import validate_control_manifest, validate_generator_manifest, validate_plan, verify_stage1_blobs
from .generator import (
    build_calibration_plan,
    build_fixture_observations,
    build_generator_manifest,
    build_plan_index,
    empirical_control_template,
    fixture_control_manifest,
)


def _generator_index(manifest: dict) -> dict:
    index = {
        "schema": "tier-bench/astra-stage2-generator-manifest-index@1",
        "generator_version": manifest["generator_version"],
        "case_count": manifest["case_count"],
        "families": manifest["families"],
        "k_levels": manifest["k_levels"],
        "r_levels": manifest["r_levels"],
        "replicates": manifest["replicates"],
        "cases_sha256": hashlib.sha256(
            json.dumps(manifest["cases"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "generator_manifest_payload_sha256": manifest["payload_sha256"],
    }
    index["payload_sha256"] = sha256_object(index)
    return index


def _require_equal(path: Path, data: bytes) -> None:
    if not path.is_file() or path.read_bytes() != data:
        raise Stage2Error(f"committed generated product drift: {path}")


def _run_tests(repo_root: Path, output: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_astra_stage2_calibration.py",
        "-v",
    ]
    process = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, timeout=120)
    text = process.stdout + process.stderr
    write_bytes_atomic(output, text.encode("utf-8"))
    if process.returncode != 0:
        raise Stage2Error(f"adversarial witness suite failed with exit {process.returncode}")


def execute(args: argparse.Namespace) -> dict:
    repo_root = args.repo_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    for path in sorted((repo_root / "schemas").glob("astra-stage2-*.schema.json")):
        strict_json_load(path)
    for path in sorted((repo_root / "experiments/astra_kxr/stage2").glob("*.json")):
        strict_json_load(path)

    test_log = output / "test-astra-stage2.log"
    _run_tests(repo_root, test_log)

    generator = validate_generator_manifest(build_generator_manifest())
    generator_path = output / "generator-manifest.json"
    write_json_atomic(generator_path, generator)
    generator_index = _generator_index(generator)
    generator_index_path = output / "generator-manifest.index.json"
    write_json_atomic(generator_index_path, generator_index)
    _require_equal(
        repo_root / "experiments/astra_kxr/stage2/generator-manifest.index.json",
        pretty_json_bytes(generator_index),
    )

    controls = validate_control_manifest(fixture_control_manifest())
    controls_path = output / "fixture-control-manifest.json"
    write_json_atomic(controls_path, controls)
    _require_equal(
        repo_root / "experiments/astra_kxr/stage2/fixture-control-manifest.json",
        pretty_json_bytes(controls),
    )

    empirical = empirical_control_template()
    empirical_path = output / "empirical-control-manifest.template.json"
    write_json_atomic(empirical_path, empirical)
    _require_equal(
        repo_root / "experiments/astra_kxr/stage2/empirical-control-manifest.template.json",
        pretty_json_bytes(empirical),
    )

    plan = validate_plan(build_calibration_plan(generator, controls), generator, controls)
    plan_path = output / "calibration-plan.fixture.json"
    write_json_atomic(plan_path, plan)
    plan_index = build_plan_index(plan)
    plan_index_path = output / "calibration-plan.fixture.index.json"
    write_json_atomic(plan_index_path, plan_index)
    _require_equal(
        repo_root / "experiments/astra_kxr/stage2/calibration-plan.fixture.index.json",
        pretty_json_bytes(plan_index),
    )

    observations = build_fixture_observations(plan)
    observations_path = output / "fixture-observations.jsonl"
    write_jsonl_atomic(observations_path, observations)
    result = derive_calibration_result(
        observations,
        plan,
        controls,
        generator_manifest=generator,
        repo_root=repo_root,
    )
    if (
        result["state"] != "FIXTURE_CONFORMANCE_ONLY"
        or result["stage2_frozen"] is not False
        or result["candidate_thresholds"] != {}
    ):
        raise Stage2Error("fixture transaction widened Stage 2 authority")
    result_path = output / "fixture-result.json"
    write_json_atomic(result_path, result)

    stage1 = {
        "schema": "tier-bench/astra-stage2-stage1-blob-verification@1",
        "stage1_blobs": verify_stage1_blobs(repo_root),
    }
    stage1["payload_sha256"] = sha256_object(stage1)
    write_json_atomic(output / "stage1-blob-verification.json", stage1)
    write_bytes_atomic(
        output / "astra-stage2-cli-help.txt",
        build_cli_parser().format_help().encode("utf-8"),
    )

    for path in output.iterdir():
        if not path.is_file():
            continue
        data = path.read_bytes()
        for marker in FORBIDDEN_PUBLIC_MARKERS:
            if marker in data:
                raise Stage2Error(f"public evidence retained forbidden marker in {path.name}")
        if b'"stage2_frozen": true' in data:
            raise Stage2Error(f"public evidence attempted to freeze Stage 2 in {path.name}")

    receipt = _qualification(
        SimpleNamespace(
            repo_root=repo_root,
            repository=args.repository,
            branch=args.branch,
            source_head=args.source_head,
            tree=args.tree,
            parent=args.parent,
            changed_paths_z=args.changed_paths_z,
            test_log=test_log,
            generator_manifest=generator_path,
            control_manifest=controls_path,
            plan=plan_path,
            fixture_observations=observations_path,
            fixture_result=result_path,
        )
    )
    write_json_atomic(output / "qualification-receipt.json", receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--changed-paths-z", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        receipt = execute(build_parser().parse_args(argv))
        print(json.dumps(receipt, sort_keys=True, indent=2))
        return 0
    except (Stage2Error, subprocess.TimeoutExpired) as exc:
        print(f"astra-stage2-ci: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
