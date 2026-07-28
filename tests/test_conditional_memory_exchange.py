#!/usr/bin/env python3
"""Zero-network distributed exchange tests for desktop and dual-seat Gram roles."""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.conditional_memory_common import load_json  # noqa: E402
from tier_runner.conditional_memory_exchange import (  # noqa: E402
    collect_flight,
    exchange_status,
    publish_flight,
    run_worker_node,
    validate_cluster,
)


def cluster() -> dict:
    return {
        "schema": "tier-bench/conditional-memory-cluster@1",
        "id": "fixture-cluster",
        "coordinator": {
            "id": "desktop-4060",
            "require_hostname": False,
            "service_gpu_uuid_env": "TIER_GPU_4060_UUID",
            "service_gpu_expected_name_contains": "4060",
        },
        "worker": {
            "id": "lg-gram-dual3090",
            "require_hostname": False,
            "seats": [
                {"id": "seat-a", "kind": "cpu", "require_identity": False},
                {"id": "seat-b", "kind": "cpu", "require_identity": False},
            ],
        },
        "exchange": {
            "kind": "shared_filesystem",
            "root_env": "TIER_EXCHANGE_ROOT",
            "poll_seconds": 0.1,
            "heartbeat_seconds": 0.25,
            "lease_seconds": 60,
            "copy_checkpoints": True,
            "cross_verify": True,
            "verification_loss_tolerance": 0.01,
            "require_top_token_match": True,
        },
    }


def lab() -> dict:
    return {
        "schema": "tier-bench/conditional-memory-lab@1",
        "id": "distributed-fixture",
        "title": "Distributed fixture",
        "purpose": "Prove artifact exchange and opposite-seat replay.",
        "default_profile": "default",
        "state_root": "D:/TierRuns/ConditionalMemory",
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
            "seeds": [11, 17],
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
            "min_complete_seeds": 2,
            "min_relative_validation_loss_improvement": 0.0,
            "max_p95_step_time_regression": 100.0,
            "max_peak_memory_regression": 100.0,
            "require_seat_balance": True,
            "require_checkpoint_identity": True,
            "failure_default": "hold",
        },
    }


def test_cluster_contract_is_strict() -> None:
    normalized = validate_cluster(cluster())
    assert normalized["coordinator"]["id"] == "desktop-4060"
    assert [seat["id"] for seat in normalized["worker"]["seats"]] == ["seat-a", "seat-b"]
    broken = cluster()
    broken["exchange"]["heartbeat_seconds"] = 100
    try:
        validate_cluster(broken)
    except ValueError as exc:
        assert "heartbeat_seconds" in str(exc)
    else:
        raise AssertionError("heartbeat longer than lease must fail")


def test_distributed_roundtrip() -> None:
    try:
        import torch  # noqa: F401
    except ImportError:
        print("  skip  test_distributed_roundtrip: torch unavailable")
        return
    parent = Path(tempfile.mkdtemp(prefix="cmem-exchange-"))
    try:
        published = publish_flight(
            raw_lab=lab(),
            profile="default",
            raw_cluster=cluster(),
            exchange_root=parent / "exchange",
            flight_id="fixture-flight",
            force_cpu=True,
        )
        flight_root = Path(published["root"])
        assert len(published["manifest"]["packets"]) == 8
        worker = run_worker_node(
            root=flight_root,
            node_id="lg-gram-dual3090",
            work_root=parent / "worker",
            force_cpu=True,
            reclaim_stale=False,
            max_wait_seconds=120,
        )
        assert worker["ok"], worker
        status = exchange_status(flight_root)
        assert status["counts"]["completed"] == 8
        collected = collect_flight(
            root=flight_root,
            coordinator_state=parent / "coordinator",
            force_cpu=True,
        )
        assert collected["ok"], collected
        assert collected["cross_verified_count"] == 4
        report = load_json(Path(collected["coordinator_state"]) / "cluster-report.json")
        assert report["cross_verified_count"] == report["expected_trial_count"]
        assert report["promotion_authorized"] is False
        local_receipts = list(Path(collected["coordinator_state"]).rglob("receipt.local.json"))
        assert len(local_receipts) == 4
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    tests = [test_cluster_contract_is_strict, test_distributed_roundtrip]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} exchange tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
