"""Build and verify the model-free Sol-root administrative canary freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
PREFIX = "tier-bench/sol-root-activation"
CATALOG = EXPERIMENT / "generated" / "catalog_projection_v0_2.json"
OWNER_CELL = "gpt-5.6-sol@high#standard"
CLI = {
    "version": "codex-cli 0.144.5",
    "sha256": "efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a",
    "observed_path": "C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe",
}
INPUTS = ("owner_prompt.txt", "executor_prompt.txt", "final_schema.json", "runner.py", "build_activation_v0_3.py")


class ActivationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ActivationError(message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value.replace(b"\r\n", b"\n")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationError(f"cannot load {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def split_cell(cell_id: str) -> tuple[str, str, str]:
    try:
        model, remainder = cell_id.split("@", 1)
        effort, tier = remainder.split("#", 1)
    except ValueError as exc:
        raise ActivationError(f"invalid catalog cell_id: {cell_id}") from exc
    require(tier in {"standard", "fast"}, f"unsupported tier: {tier}")
    return model, effort, tier


def invocation(cell_id: str, role: str) -> dict[str, Any]:
    model, effort, tier = split_cell(cell_id)
    return {
        "cell_id": cell_id,
        "role": role,
        "model": model,
        "reasoning_effort": effort,
        "catalog_tier": tier,
        "service_tier_config": "default" if tier == "standard" else "priority",
        "sandbox": "read-only" if role == "owner" else "workspace-write",
        "prompt": "owner_prompt.txt" if role == "owner" else "executor_prompt.txt",
    }


def build() -> dict[str, Any]:
    catalog = load(CATALOG)
    require(catalog.get("schema") == "tier-bench/sol-root-matched-config/catalog-projection@0.2", "wrong catalog")
    require(catalog.get("status") == "proposal_only_unactivated_unfrozen", "catalog state changed")
    cells = catalog.get("cells")
    require(isinstance(cells, list) and len(cells) == 58, "expected exactly 58 executor cells")
    cell_ids = [cell.get("cell_id") for cell in cells]
    require(all(isinstance(cell_id, str) for cell_id in cell_ids), "catalog cell_id missing")
    require(len(set(cell_ids)) == 58 and OWNER_CELL in cell_ids, "catalog cells are not unique or owner is missing")

    schedule = [invocation(OWNER_CELL, "owner")]
    schedule.extend(invocation(cell_id, "executor") for cell_id in cell_ids)
    for sequence, item in enumerate(schedule):
        item["sequence"] = sequence

    return {
        "schema": f"{PREFIX}/freeze-candidate@0.3",
        "status": "awaiting_prospective_operator_ratification",
        "prepared_date_utc": "2026-07-17",
        "source": {
            "catalog_path": "../generated/catalog_projection_v0_2.json",
            "catalog_sha256": sha256_file(CATALOG),
            "protocol_path": "../PROTOCOL_PROPOSAL_V0_3.md",
            "protocol_sha256": sha256_file(EXPERIMENT / "PROTOCOL_PROPOSAL_V0_3.md"),
            "custody_closure_path": "../custody_closure_receipt_v0_3.json",
            "custody_closure_sha256": sha256_file(EXPERIMENT / "custody_closure_receipt_v0_3.json"),
        },
        "inputs": {name: sha256_file(HERE / name) for name in INPUTS},
        "cli_identity": CLI,
        "identity_evidence": {
            "claim": "requested_configuration_bound_to_pinned_cli_binary",
            "provider_side_actual_model_attestation_available": False,
            "limitation": "Codex CLI JSONL events expose requested-run behavior and usage but no provider-signed actual-model identity.",
            "forbidden_overclaim": "provider-side actual-model identity proven",
        },
        "authorization_contract": {
            "receipt_schema": f"{PREFIX}/operator-authorization@0.3",
            "must_bind_exact_freeze_sha256": True,
            "authorized_call_ceiling": 59,
            "no_retries": True,
            "authorization_must_be_prospective": True,
        },
        "execution_contract": {
            "administrative_calls": 59,
            "scientific_calls": 0,
            "owner_calls": 1,
            "executor_calls": 58,
            "coordinator_calls": 0,
            "ordering": "owner_then_catalog_order_executors",
            "no_retries": True,
            "network_for_generated_commands": False,
            "stop_on_first_failure": True,
            "evidence_root": "run/activation_v0_3/<freeze_sha256>/",
        },
        "command_contract": {
            "subcommand": "exec",
            "flags": ["--ignore-user-config", "--strict-config", "--ephemeral", "--json", "--output-schema", "--output-last-message", "-C", "-"],
            "fixed_config": {
                "approval_policy": "never",
                "features.multi_agent": False,
                "agents.max_depth": 1,
                "agents.max_threads": 1,
                "history.persistence": "none",
                "web_search": "disabled",
                "sandbox_workspace_write.network_access": False,
            },
            "tier_mapping": {"standard": "default", "fast": "priority"},
        },
        "acceptance": {
            "owner": "exit zero; final JSON exactly status=ready; git tree unchanged",
            "executor": "exit zero; final JSON exactly status=ready; only result.txt is added with exact frozen bytes",
            "accepted_executor_file_utf8": "SOL_ROOT_CANARY_V0_3\n",
            "all_cells_required": True,
            "partial_success_admissible": False,
        },
        "schedule": schedule,
        "provider_calls": 0,
        "scientific_observations": 0,
    }


def receipt(freeze: dict[str, Any]) -> dict[str, Any]:
    schedule = freeze.get("schedule", [])
    checks = {
        "status_is_unratified": freeze.get("status") == "awaiting_prospective_operator_ratification",
        "exactly_59_calls": len(schedule) == 59 == freeze.get("execution_contract", {}).get("administrative_calls"),
        "owner_first_and_unique": sum(item.get("role") == "owner" for item in schedule) == 1 and schedule[0].get("cell_id") == OWNER_CELL,
        "all_58_executor_cells_unique": len({item.get("cell_id") for item in schedule[1:]}) == 58 and all(item.get("role") == "executor" for item in schedule[1:]),
        "no_retries": freeze.get("execution_contract", {}).get("no_retries") is True,
        "zero_scientific_calls": freeze.get("execution_contract", {}).get("scientific_calls") == 0,
        "zero_provider_calls_during_build": freeze.get("provider_calls") == 0,
        "provider_identity_limit_explicit": freeze.get("identity_evidence", {}).get("provider_side_actual_model_attestation_available") is False,
    }
    return {
        "schema": f"{PREFIX}/offline-verification-receipt@0.3",
        "freeze_sha256": sha256_bytes(canonical(freeze)),
        "checks": checks,
        "all_pass": all(checks.values()),
        "provider_calls": 0,
        "scientific_observations": 0,
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists(), f"refusing to overwrite {path}")
    path.write_bytes(canonical(value))


def verify(freeze_path: Path, receipt_path: Path) -> None:
    frozen = load(freeze_path)
    expected = build()
    require(canonical(frozen) == canonical(expected), "freeze differs from deterministic build")
    recorded = load(receipt_path)
    require(canonical(recorded) == canonical(receipt(expected)), "offline receipt differs from deterministic verification")
    require(recorded.get("all_pass") is True, "offline checks failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--freeze", type=Path, default=HERE / "freeze_candidate.json")
    parser.add_argument("--receipt", type=Path, default=HERE / "offline_verification_receipt.json")
    args = parser.parse_args()
    try:
        if args.command == "build":
            frozen = build()
            write_new(args.freeze, frozen)
            write_new(args.receipt, receipt(frozen))
        else:
            verify(args.freeze, args.receipt)
    except (ActivationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("OK - Sol-root activation v0.3 offline freeze; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
