#!/usr/bin/env python3
"""Zero-model controls plus an optional one-step PyTorch smoke for the memory lab."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.conditional_memory_common import hash_json, without_hash, write_json  # noqa: E402
from tier_runner.conditional_memory_hardware import parse_nvidia_csv  # noqa: E402
from tier_runner.conditional_memory_plan import compile_plan, verify_plan  # noqa: E402
from tier_runner.conditional_memory_report import (  # noqa: E402
    build_report,
    status_report,
    validate_receipt,
)
from tier_runner.conditional_memory_schema import (  # noqa: E402
    MemoryLabError,
    RECEIPT_SCHEMA,
    validate_lab,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lab() -> dict:
    return {
        "schema": "tier-bench/conditional-memory-lab@1",
        "id": "fixture-memory-lab",
        "title": "Fixture memory lab",
        "purpose": "Exercise matched conditional-memory contracts.",
        "state_root": "D:/TierRuns/ConditionalMemory",
        "default_profile": "default",
        "dataset": {
            "kind": "synthetic_associations",
            "vocab_size": 64,
            "sequence_length": 8,
            "train_sequences": 16,
            "validation_sequences": 8,
            "seed": 7,
            "association_rate": 0.6,
            "bigram_rate": 0.25,
            "random_rate": 0.15,
        },
        "model": {
            "d_model": 16,
            "layers": 1,
            "heads": 2,
            "ffn_hidden": 32,
            "dropout": 0.0,
            "tie_embeddings": True,
            "bias": False,
        },
        "training": {
            "seeds": [11, 17, 23, 29],
            "steps": 1,
            "batch_size": 2,
            "learning_rate": 0.001,
            "weight_decay": 0.0,
            "warmup_steps": 0,
            "gradient_clip": 1.0,
            "eval_interval": 1,
            "amp": "off",
            "deterministic": True,
            "compile": False,
            "save_checkpoint": True,
            "optimizer": "adamw",
        },
        "measurement": {
            "warmup_steps": 0,
            "profile_steps": 1,
            "capture_logits": True,
            "trace_access": True,
            "sample_gpu": False,
        },
        "topology": {
            "assignment": "paired_crossover",
            "seats": [
                {"id": "seat-a", "kind": "cpu", "require_identity": False},
                {"id": "seat-b", "kind": "cpu", "require_identity": False},
            ],
        },
        "arms": [
            {
                "id": "dense",
                "architecture": "dense",
                "role": "control",
                "description": "Dense control",
            },
            {
                "id": "ple",
                "architecture": "ple",
                "role": "candidate",
                "description": "PLE candidate",
                "memory": {
                    "table_rows": "vocab",
                    "memory_dim": 16,
                    "injection_layers": "all",
                    "placement": "vram",
                    "storage_dtype": "fp32",
                    "runtime_dtype": "fp32",
                },
            },
        ],
        "profiles": {},
        "promotion": {
            "baseline_arm": "dense",
            "min_complete_seeds": 3,
            "min_relative_validation_loss_improvement": 0.02,
            "max_p95_step_time_regression": 0.15,
            "max_peak_memory_regression": 0.1,
            "require_seat_balance": True,
            "require_checkpoint_identity": True,
            "failure_default": "hold",
        },
    }


def fake_receipt(plan: dict, trial: dict, *, loss: float, p95: float, peak: int) -> dict:
    seed = trial["seed"]
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "completed",
        "started_at": "2026-07-27T00:00:00Z",
        "completed_at": "2026-07-27T00:01:00Z",
        "lab_id": plan["lab_id"],
        "profile": plan["profile"],
        "lab_sha256": plan["lab_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "trial_id": trial["id"],
        "arm_id": trial["arm_id"],
        "architecture": trial["architecture"],
        "seed": seed,
        "seat": trial["seat"],
        "seat_resolution": {"resolved": True, "seat_id": trial["seat"]["id"]},
        "attempt": 1,
        "pair_id": trial["pair_id"],
        "paired_baseline_trial_id": trial["paired_baseline_trial_id"],
        "source_hashes": {"runner.py": h("same-source")},
        "runtime": {"torch": "fixture", "device": "cuda:0"},
        "data": {
            "combined_sha256": h(f"data-{seed}"),
            "train_sha256": h(f"train-{seed}"),
            "validation_sha256": h(f"val-{seed}"),
        },
        "model": {
            "arm": trial["arm"],
            "initial_state_sha256": h(f"initial-{trial['arm_id']}-{seed}"),
            "final_state_sha256": h(f"final-{trial['arm_id']}-{seed}"),
            "checkpoint_path": f"checkpoint-{trial['arm_id']}-{seed}.pt",
            "checkpoint_sha256": h(f"checkpoint-{trial['arm_id']}-{seed}"),
            "topology_ledger": {
                "stored_parameters": 100 if trial["arm_id"] == "dense" else 200,
                "conditional_memory_parameters": 0 if trial["arm_id"] == "dense" else 100,
            },
        },
        "training": {
            "config": {"save_checkpoint": True},
            "resolved_amp": "off",
            "tokens_seen": 16,
            "loss_trace": [{"step": 1, "training_loss": loss}],
            "final_training_loss": loss,
        },
        "evaluation": {
            "validation_loss": loss,
            "perplexity": 2.0,
            "tokens": 64,
            "elapsed_seconds": 1.0,
            "tokens_per_second": 64.0,
        },
        "golden": {"prompt_sha256": h("prompt"), "logits_sha256": h("logits")},
        "performance": {
            "profile_steps": 1,
            "step_time_ms": {
                "min": p95,
                "median": p95,
                "p95": p95,
                "max": p95,
                "mean": p95,
            },
            "training_tokens_per_second": 10.0,
            "peak_cuda_allocated_bytes": peak,
            "peak_cuda_reserved_bytes": peak,
            "wall_seconds": 1.0,
        },
        "failure": None,
    }
    receipt["receipt_sha256"] = hash_json(receipt)
    return receipt


def test_validation_is_strict() -> None:
    raw = lab()
    normalized = validate_lab(raw)
    assert normalized["promotion"]["baseline_arm"] == "dense"
    raw["training"]["deterministic"] = "true"
    try:
        validate_lab(raw)
    except MemoryLabError as exc:
        assert "must be boolean" in str(exc)
    else:
        raise AssertionError("truthy string must not pass a boolean boundary")


def test_plan_is_deterministic_and_crossover_balanced() -> None:
    first = compile_plan(lab())
    second = compile_plan(lab())
    assert first == second
    assert len(first["trials"]) == 8
    for arm_id, counts in first["pairing"]["seat_counts"].items():
        assert counts == {"seat-a": 2, "seat-b": 2}, arm_id
    assert verify_plan(lab(), first) == []


def test_plan_tamper_fails() -> None:
    plan = compile_plan(lab())
    tampered = copy.deepcopy(plan)
    tampered["trials"][0]["seed"] = 999
    assert any("trials" in error for error in verify_plan(lab(), tampered))


def test_receipt_hash_and_trial_identity_are_bound() -> None:
    plan = compile_plan(lab())
    trial = plan["trials"][0]
    receipt = fake_receipt(plan, trial, loss=1.0, p95=10.0, peak=100)
    assert validate_receipt(receipt, plan) == []
    receipt["seed"] = 999
    errors = validate_receipt(receipt, plan)
    assert any("receipt_sha256" in error for error in errors)
    assert any("receipt.seed" in error for error in errors)


def test_report_promotes_only_after_paired_gates() -> None:
    plan = compile_plan(lab())
    parent = Path(tempfile.mkdtemp(prefix="conditional-memory-report-"))
    try:
        for trial in plan["trials"]:
            baseline = trial["arm_id"] == "dense"
            receipt = fake_receipt(
                plan,
                trial,
                loss=1.0 if baseline else 0.90,
                p95=10.0 if baseline else 10.5,
                peak=100 if baseline else 95,
            )
            path = parent / trial["id"].replace("/", "__") / "attempt-001" / "receipt.json"
            write_json(path, receipt)
        report = build_report(plan, parent)
        by_arm = {row["arm_id"]: row for row in report["arms"]}
        assert by_arm["dense"]["decision"] == "control"
        assert by_arm["ple"]["decision"] == "promote"
        assert report["promotable_arms"] == ["ple"]
        assert report["promotion_authorized"] is False
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_dataset_drift_holds_the_candidate() -> None:
    plan = compile_plan(lab())
    parent = Path(tempfile.mkdtemp(prefix="conditional-memory-drift-"))
    try:
        for trial in plan["trials"]:
            receipt = fake_receipt(
                plan,
                trial,
                loss=1.0 if trial["arm_id"] == "dense" else 0.8,
                p95=10.0,
                peak=100,
            )
            if trial["arm_id"] == "ple" and trial["seed"] == 17:
                receipt["data"]["combined_sha256"] = h("wrong-data")
                receipt["receipt_sha256"] = hash_json(without_hash(receipt, "receipt_sha256"))
            path = parent / trial["id"].replace("/", "__") / "attempt-001" / "receipt.json"
            write_json(path, receipt)
        report = build_report(plan, parent)
        candidate = next(row for row in report["arms"] if row["arm_id"] == "ple")
        assert candidate["decision"] == "hold"
        assert any(
            "dataset fingerprints" in item
            for item in report["status"]["integrity_conflicts"]
        )
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_unimplemented_prefetch_fails_closed() -> None:
    raw = lab()
    raw["arms"][1]["memory"]["prefetch_layers"] = 1
    try:
        validate_lab(raw)
    except MemoryLabError as exc:
        assert "not implemented" in str(exc)
    else:
        raise AssertionError("reserved prefetch configuration must not be silently ignored")


def test_missing_trials_make_status_incomplete() -> None:
    plan = compile_plan(lab())
    parent = Path(tempfile.mkdtemp(prefix="conditional-memory-missing-"))
    try:
        status = status_report(plan, parent)
        assert status["ok"] is False
        assert len(status["missing"]) == len(plan["trials"])
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_nvidia_csv_parser_binds_uuid_and_metrics() -> None:
    rows = parse_nvidia_csv(
        "0, GPU-aaa, NVIDIA GeForce RTX 3090, 24576, 12000, 99, 310.5, 71, 600.1\n"
    )
    assert rows[0]["uuid"] == "GPU-aaa"
    assert rows[0]["memory_total"] == 24576
    assert rows[0]["power_draw_w"] == 310.5


def test_optional_torch_trial_smoke() -> None:
    try:
        import torch  # noqa: F401
        from tier_runner.conditional_memory_runner import execute_trial
    except ImportError:
        print("  skip  test_optional_torch_trial_smoke: torch unavailable")
        return
    raw = lab()
    raw["training"]["seeds"] = [11, 17, 23]
    raw["promotion"]["min_complete_seeds"] = 2
    plan = compile_plan(raw)
    trial = next(row for row in plan["trials"] if row["arm_id"] == "dense")
    parent = Path(tempfile.mkdtemp(prefix="conditional-memory-torch-"))
    try:
        receipt = execute_trial(
            plan=plan,
            trial=trial,
            state_dir=parent,
            seat_resolution={"seat_id": trial["seat"]["id"], "kind": "cpu", "resolved": True},
            attempt=1,
            force_cpu=True,
        )
        assert receipt["status"] == "completed", receipt.get("failure")
        assert receipt["model"]["topology_ledger"]["stored_parameters"] > 0
        assert receipt["golden"]["logits_sha256"]
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_optional_uint16_split_is_exact() -> None:
    try:
        from array import array
        from tier_runner.conditional_memory_common import hash_file
        from tier_runner.conditional_memory_runner import materialize_dataset
    except ImportError:
        print("  skip  test_optional_uint16_split_is_exact: torch unavailable")
        return
    parent = Path(tempfile.mkdtemp(prefix="conditional-memory-u16-"))
    try:
        path = parent / "tokens.bin"
        sequence_length = 8
        rows = 5
        values = array("H", (index % 64 for index in range(rows * (sequence_length + 1))))
        path.write_bytes(values.tobytes())
        dataset = {
            "kind": "uint16_tokens",
            "vocab_size": 64,
            "sequence_length": sequence_length,
            "train_sequences": 3,
            "validation_sequences": 2,
            "seed": 7,
            "path": str(path),
            "sha256": hash_file(path),
            "validation_path": None,
            "validation_sha256": None,
        }
        train, validation, fingerprint = materialize_dataset(dataset, trial_seed=11)
        assert list(train.shape) == [3, sequence_length + 1]
        assert list(validation.shape) == [2, sequence_length + 1]
        assert fingerprint["source_sha256"] == hash_file(path)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_optional_pack_roundtrip() -> None:
    try:
        import torch
        from tier_runner.conditional_memory_pack import (
            evaluate_pack,
            export_pack,
            profile_pack,
            validate_pack,
        )
        from tier_runner.conditional_memory_runner import execute_trial
    except ImportError:
        print("  skip  test_optional_pack_roundtrip: torch unavailable")
        return
    raw = lab()
    raw["training"]["seeds"] = [11, 17, 23]
    plan = compile_plan(raw)
    trial = next(row for row in plan["trials"] if row["arm_id"] == "ple")
    parent = Path(tempfile.mkdtemp(prefix="conditional-memory-pack-"))
    try:
        receipt = execute_trial(
            plan=plan,
            trial=trial,
            state_dir=parent / "state",
            seat_resolution={"seat_id": trial["seat"]["id"], "kind": "cpu", "resolved": True},
            attempt=1,
            force_cpu=True,
        )
        assert receipt["status"] == "completed", receipt.get("failure")
        assert receipt["training"]["optimizer_identity"]["conditional_memory"] == "sparse_adam"
        receipt_path = next((parent / "state").rglob("receipt.json"))
        manifest = export_pack(
            receipt_path=receipt_path,
            out_dir=parent / "pack-int4",
            dtype="int4",
            group_size=8,
        )
        verified, _ = validate_pack(parent / "pack-int4" / "manifest.json")
        assert verified["pack_sha256"] == manifest["pack_sha256"]
        assert manifest["artifact"]["bytes"] < manifest["table"]["source_bytes"]
        assert manifest["quality"]["max_abs_error"] < 0.1
        profile = profile_pack(
            manifest_path=parent / "pack-int4" / "manifest.json",
            placement="host_ram",
            device=torch.device("cpu"),
            batch_rows=4,
            iterations=5,
            warmup=1,
            seed=17,
            pattern="random",
            out=parent / "profile.json",
            seat_resolution={"seat_id": "cpu", "kind": "cpu", "resolved": True},
        )
        assert profile["latency_ms"]["p95"] >= 0
        assert profile["profile_sha256"]
        evaluation = evaluate_pack(
            plan=plan,
            receipt_path=receipt_path,
            manifest_path=parent / "pack-int4" / "manifest.json",
            device=torch.device("cpu"),
            out=parent / "evaluation.json",
            seat_resolution={"seat_id": "cpu", "kind": "cpu", "resolved": True},
            chunk_rows=8,
        )
        assert abs(evaluation["relative_validation_loss_change"]) < 0.10
        assert evaluation["evaluation_sha256"]
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    tests = [
        test_validation_is_strict,
        test_plan_is_deterministic_and_crossover_balanced,
        test_plan_tamper_fails,
        test_receipt_hash_and_trial_identity_are_bound,
        test_report_promotes_only_after_paired_gates,
        test_dataset_drift_holds_the_candidate,
        test_unimplemented_prefetch_fails_closed,
        test_missing_trials_make_status_incomplete,
        test_nvidia_csv_parser_binds_uuid_and_metrics,
        test_optional_torch_trial_smoke,
        test_optional_uint16_split_is_exact,
        test_optional_pack_roundtrip,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} conditional-memory tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
