"""Build and verify the canonical machine-only v0.3 continuation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = Path(__file__).resolve().parent / ".cart0" / "000.000.json"
SCHEMA = "tier-bench/sol-root-matched-config/continuation-manifest@0.3"
EVIDENCE_PATHS = (
    ".github/workflows/breadth-durability.yml",
    "experiments/sol_root_matched_config/PROTOCOL_PROPOSAL_V0_3.md",
    "experiments/sol_root_matched_config/compile_proposal_v0_3.py",
    "experiments/sol_root_matched_config/design_proposal_v0_3.json",
    "experiments/sol_root_matched_config/generated/catalog_projection_v0_2.json",
    "experiments/sol_root_matched_config/generated_v0_3/acceptance_contract_proposal_v0_3.json",
    "experiments/sol_root_matched_config/generated_v0_3/custody_contract_proposal_v0_3.json",
    "experiments/sol_root_matched_config/generated_v0_3/offline_verification_receipt_v0_3.json",
    "experiments/sol_root_matched_config/generated_v0_3/schedule_proposal_v0_3.json",
    "tests/test_sol_root_matched_config.py",
    "tests/test_sol_root_matched_config_v0_3.py",
)


class ManifestError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def git_bytes(git: str, *args: str) -> bytes:
    completed = subprocess.run([git, "-C", str(ROOT), *args], capture_output=True)
    if completed.returncode != 0:
        raise ManifestError(completed.stderr.decode("utf-8", errors="replace").strip() or "git command failed")
    return completed.stdout


def commit_oid(git: str, revision: str) -> str:
    return git_bytes(git, "rev-parse", f"{revision}^{{commit}}").decode("ascii").strip()


def blob(git: str, commit: str, path: str) -> bytes:
    return git_bytes(git, "show", f"{commit}:{path}")


def blob_json(git: str, commit: str, path: str) -> dict[str, Any]:
    try:
        value = json.loads(blob(git, commit, path))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON at {commit}:{path}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"object required at {commit}:{path}")
    return value


def build_manifest(git: str, source_commit: str) -> dict[str, Any]:
    source_commit = commit_oid(git, source_commit)
    refs = []
    for path in EVIDENCE_PATHS:
        content = blob(git, source_commit, path)
        refs.append({
            "repo": "BigBirdReturns/tier-bench",
            "commit": source_commit,
            "path": path,
            "blob_sha256": hashlib.sha256(content).hexdigest(),
            "hash_basis": "git_blob_bytes",
        })
    schedule = blob_json(git, source_commit, "experiments/sol_root_matched_config/generated_v0_3/schedule_proposal_v0_3.json")
    receipt = blob_json(git, source_commit, "experiments/sol_root_matched_config/generated_v0_3/offline_verification_receipt_v0_3.json")
    if receipt.get("all_pass") is not True:
        raise ManifestError("source commit does not contain a passing v0.3 receipt")
    return {
        "schema": SCHEMA,
        "dewey": "000.000",
        "status": "proposal_only_unactivated_unfrozen",
        "source": {
            "repo": "BigBirdReturns/tier-bench",
            "branch": "codex/luna-sol-anchor-replication-v2",
            "artifact_commit": source_commit,
        },
        "supersedes": {
            "path": "experiments/sol_root_matched_config/.cart0/000.000.INDEX.md",
            "mode": "machine_primary_human_history_preserved",
        },
        "authority": {
            "queue_id": "SOL-ROOT-MATCHED-CONFIG-V0.3",
            "allowed": ["offline_verification", "push_exact_codex_branch_for_reachability"],
            "forbidden": ["provider_call", "canary", "task_or_grader_implementation", "hidden_vector", "scientific_freeze", "benchmark", "pr", "merge"],
        },
        "experiment": {
            "pinned_owner_cell_id": schedule["pinned_owner_cell_id"],
            "initial_scientific_call_ceiling": schedule["initial_scientific_call_ceiling"],
            "deferred_topology_c_call_ceiling": schedule["deferred_topology_c"]["scientific_call_ceiling"],
            "absolute_initial_repair_ceiling": schedule["conditional_repair"]["absolute_initial_call_ceiling"],
            "reporting_ratio_points": schedule["reporting_ratio_points"],
            "schedule_depends_on_reporting_ratio_points": False,
        },
        "evidence_refs": refs,
        "verification": {
            "commands": [
                "python tests/test_sol_root_matched_config.py",
                "python tests/test_sol_root_matched_config_v0_3.py",
                "python experiments/sol_root_matched_config/build_machine_continuation_v0_3.py verify --git git",
            ],
            "expected": {"v0_2_checks": 16, "v0_3_checks": 7, "provider_calls": 0, "scientific_observations": 0},
        },
        "custody": {
            "state": "prepared_local",
            "next": "push_artifact_commit_then_commit_reachability_receipt",
            "cross_engine_receipt_branch_namespace": "claude/*",
            "canonical_closure_requires_separate_pr_merge_authority": True,
        },
        "provider_calls": 0,
        "scientific_observations": 0,
        "authority_created": False,
    }


def verify_manifest(git: str, path: Path) -> dict[str, Any]:
    try:
        observed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc
    if not isinstance(observed, dict) or observed.get("schema") != SCHEMA:
        raise ManifestError("wrong manifest schema")
    source = observed.get("source", {}).get("artifact_commit")
    if not isinstance(source, str):
        raise ManifestError("artifact commit missing")
    expected = build_manifest(git, source)
    checks = {
        "exact_manifest_match": observed == expected,
        "evidence_refs_complete": len(observed.get("evidence_refs", [])) == len(EVIDENCE_PATHS),
        "all_blob_hashes_verified": observed.get("evidence_refs") == expected.get("evidence_refs"),
        "authority_is_nonexpanding": observed.get("authority_created") is False,
        "provider_calls_zero": observed.get("provider_calls") == 0,
    }
    return {
        "schema": "tier-bench/sol-root-matched-config/continuation-verification@0.3",
        "manifest_sha256": hashlib.sha256(canonical(observed)).hexdigest(),
        "artifact_commit": source,
        "checks": checks,
        "all_pass": all(checks.values()),
        "provider_calls": 0,
        "scientific_observations": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--git", required=True)
    build.add_argument("--source-commit", required=True)
    build.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    verify = sub.add_parser("verify")
    verify.add_argument("--git", required=True)
    verify.add_argument("--manifest", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        if args.action == "build":
            if args.out.exists():
                raise ManifestError(f"refusing to overwrite {args.out}")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            value = build_manifest(args.git, args.source_commit)
            args.out.write_bytes(canonical(value))
        else:
            value = verify_manifest(args.git, args.manifest)
        print(canonical(value).decode("utf-8"), end="")
        return 0 if args.action == "build" or value["all_pass"] else 2
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
