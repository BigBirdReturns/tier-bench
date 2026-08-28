from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import time
import unittest

from tier_runner.kimi3_common import (
    COMMUNITY_CONFIG_SCHEMA,
    KimiObservatoryError,
    OBSERVATORY_SCHEMA,
    load_json,
    write_json,
)
from tier_runner.kimi3_community import (
    extract_claims,
    fuse_claims_with_plan,
    sync_community,
    validate_community_config,
)
from tier_runner.kimi3_observatory import (
    build_execution_bundle,
    observe,
    validate_observatory_config,
    windows_schedule_script,
)
from tier_runner.kimi3_probe import reduce_router_trace, simulate_expert_cache
from tier_runner.kimi3_weights import (
    build_dissection_plan,
    freeze_baseline,
    numeric_sample,
    scan_model,
)


def _write_safetensors(path: Path, tensors: list[tuple[str, str, list[int], bytes]]) -> None:
    offset = 0
    header: dict[str, object] = {"__metadata__": {"format": "pt"}}
    data = bytearray()
    for name, dtype, shape, payload in tensors:
        header[name] = {
            "dtype": dtype,
            "shape": shape,
            "data_offsets": [offset, offset + len(payload)],
        }
        data.extend(payload)
        offset += len(payload)
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header_bytes)) + header_bytes + data)


def _model_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tensors = [
        (
            "model.embed_tokens.weight",
            "F32",
            [2, 2],
            struct.pack("<ffff", 1.0, 2.0, 3.0, 4.0),
        ),
        (
            "model.layers.0.self_attn.q_proj.weight",
            "F32",
            [2, 2],
            struct.pack("<ffff", 0.5, -0.5, 1.5, -1.5),
        ),
        (
            "model.layers.0.mlp.experts.0.down_proj.weight",
            "F16",
            [2, 2],
            struct.pack("<eeee", 1.0, 0.0, -1.0, 2.0),
        ),
        (
            "model.layers.1.self_attn.q_proj.weight",
            "F32",
            [2, 2],
            struct.pack("<ffff", 0.25, -0.25, 1.25, -1.25),
        ),
        (
            "model.layers.1.mlp.experts.0.down_proj.weight",
            "F16",
            [2, 2],
            struct.pack("<eeee", 0.5, 0.0, -0.5, 1.0),
        ),
    ]
    _write_safetensors(root / "model-00001-of-00001.safetensors", tensors)
    write_json(
        root / "model.safetensors.index.json",
        {
            "metadata": {"total_size": sum(len(payload) for _, _, _, payload in tensors)},
            "weight_map": {
                name: "model-00001-of-00001.safetensors"
                for name, _, _, _ in tensors
            },
        },
    )
    write_json(
        root / "config.json",
        {
            "architectures": ["KimiK3ForCausalLM"],
            "model_type": "kimi_k3",
            "num_hidden_layers": 2,
            "num_experts": 1,
            "num_experts_per_tok": 1,
            "hidden_size": 16,
            "max_position_embeddings": 1000000,
            "torch_dtype": "float16",
        },
    )
    (root / "modeling_kimi_k3.py").write_text(
        """
class KimiDeltaAttention: pass
class AttentionResidual: pass
class KimiMoE: pass
class KimiRouter: pass
def load_model(): return None
""".strip()
        + "\n",
        encoding="utf-8",
    )


class Kimi3ObservatoryTests(unittest.TestCase):
    def test_scan_census_index_and_numeric_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model = base / "model"
            _model_fixture(model)
            out = base / "state/model"
            scan = scan_model(
                model,
                out_dir=out,
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            census = load_json(out / "tensor-census.json")
            self.assertEqual(scan["totals"]["pending_files"], 0)
            self.assertEqual(census["tensor_count"], 5)
            self.assertEqual(census["layer_count_observed"], 2)
            self.assertEqual(census["global_expert_count"], 1)
            self.assertTrue(census["index_contract"]["valid"])
            self.assertTrue(scan["source_inventory"][0]["architecture_symbols"])
            sample = numeric_sample(
                model,
                tensor_index=out / "tensors.jsonl",
                patterns=["experts", "embed_tokens"],
                max_tensors=10,
                samples_per_tensor=4,
            )
            self.assertEqual(sample["totals"]["sampled"], 3)
            embedded = next(
                row for row in sample["results"] if "embed_tokens" in row["name"]
            )
            self.assertAlmostEqual(embedded["mean"], 2.5)
            self.assertEqual(embedded["zero_rate"], 0.0)


    def test_model_estate_digest_is_stable_across_receipt_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model = base / "model"
            _model_fixture(model)
            out = base / "state/model"
            first = scan_model(
                model,
                out_dir=out,
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            time.sleep(0.01)
            second = scan_model(
                model,
                out_dir=out,
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            self.assertEqual(first["model_estate_sha256"], second["model_estate_sha256"])
            self.assertNotEqual(first["created_at"], second["created_at"])

    def test_heavy_scan_defers_and_execution_bundle_links_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model = base / "model"
            _model_fixture(model)
            marker = base / "grid.active"
            marker.write_text("active\n", encoding="utf-8")
            config_path = base / "observatory.json"
            config = validate_observatory_config(
                {
                    "schema": OBSERVATORY_SCHEMA,
                    "id": "k3-local",
                    "model_root": str(model),
                    "state_dir": str(base / "state"),
                    "grid_root": str(base / "grid"),
                    "defer_heavy_when_exists": [str(marker)],
                    "numeric_patterns": ["router"],
                },
                config_path=config_path,
            )
            receipt = observe(config, profile="nightly")
            self.assertTrue(receipt["deferred_heavy_scan"])
            self.assertEqual(receipt["executed_profile"], "frequent")
            plan = load_json(base / "state/model/dissection-plan.json")
            bundle = build_execution_bundle(config, plan, None)
            automated = {
                row["id"]
                for row in bundle["work_orders"]
                if row["dispatch_state"] == "AUTOMATED"
            }
            self.assertIn("K3-A00-download-convergence", automated)
            self.assertIn("K3-C01-numeric-fingerprints", automated)
            self.assertTrue((base / "state/execution-bundle.json").exists())

    def test_pending_partial_download_is_not_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model = base / "model"
            _model_fixture(model)
            (model / "model-00002.safetensors.part").write_bytes(b"unfinished")
            scan = scan_model(
                model,
                out_dir=base / "state/model",
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            self.assertEqual(scan["totals"]["pending_files"], 1)
            self.assertEqual(scan["pending_files"][0]["reason"], "partial_suffix")

    def test_dissection_plan_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model = base / "model"
            _model_fixture(model)
            out = base / "state/model"
            scan = scan_model(
                model,
                out_dir=out,
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            census = load_json(out / "tensor-census.json")
            plan = build_dissection_plan(scan, census)
            ids = {row["id"] for row in plan["work_orders"]}
            self.assertIn("K3-D02-router-utilization-grid", ids)
            self.assertIn("K3-E01-expert-offload-simulator", ids)
            self.assertIn("K3-F01-desktop-capture", ids)
            self.assertTrue(all(row["acceptance"] for row in plan["work_orders"]))

    def test_baseline_freeze_binds_grid_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model = base / "model"
            _model_fixture(model)
            out = base / "state/model"
            scan = scan_model(
                model,
                out_dir=out,
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            census = load_json(out / "tensor-census.json")
            plan = build_dissection_plan(scan, census)
            write_json(out / "dissection-plan.json", plan)
            grid = base / "grid/run-001"
            grid.mkdir(parents=True)
            write_json(
                grid / "receipt.json",
                {
                    "schema": "tier-bench/tier-run-receipt@1",
                    "state": "ACCEPTED",
                    "task_id": "grid-001",
                    "call": {
                        "model": "kimi-k3",
                        "effort": "max",
                        "outcome": "accepted",
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cost_usd": 0.1,
                        "latency_ms": 1000,
                    },
                },
            )
            baseline = freeze_baseline(
                scan_path=out / "model-scan.json",
                census_path=out / "tensor-census.json",
                plan_path=out / "dissection-plan.json",
                grid_root=base / "grid",
                label="k3-grid-v1",
            )
            self.assertEqual(baseline["grid"]["receipt_count"], 1)
            self.assertEqual(len(baseline["baseline_sha256"]), 64)

    def test_community_import_claims_and_fusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            import_path = base / "community.jsonl"
            import_path.write_text(
                json.dumps(
                    {
                        "id": "reddit-post-1",
                        "url": "https://www.reddit.com/r/LocalLLaMA/comments/example",
                        "title": "Kimi K3 expert offload on a 3090",
                        "body": (
                            "I ran vLLM 0.18 on RTX 3090 with 64 GiB RAM. "
                            "The expert cache reached 1.2 tok/s using --cpu-offload-gb 48."
                        ),
                        "score": 42,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config = {
                "schema": COMMUNITY_CONFIG_SCHEMA,
                "id": "k3-community",
                "excerpt_chars": 800,
                "retention_days": 90,
                "training_use": "prohibited",
                "sources": [
                    {
                        "id": "manual-reddit",
                        "kind": "jsonl_import",
                        "enabled": True,
                        "paths": [str(import_path)],
                    }
                ],
            }
            state = base / "state/community"
            receipt = sync_community(config, state_dir=state)
            self.assertEqual(receipt["totals"]["added"], 1)
            report = extract_claims(state_dir=state)
            self.assertEqual(report["claims"], 1)
            claim = json.loads((state / "claims.jsonl").read_text().splitlines()[0])
            self.assertEqual(claim["training_use"], "prohibited")
            self.assertIn("expert-offload", claim["topics"])
            self.assertIn("K3-E01-expert-offload-simulator", claim["proposed_experiments"])

            model = base / "model"
            _model_fixture(model)
            out = base / "state/model"
            scan = scan_model(
                model,
                out_dir=out,
                state_dir=base / "state/hash",
                stable_age_seconds=0,
            )
            plan = build_dissection_plan(scan, load_json(out / "tensor-census.json"))
            write_json(out / "dissection-plan.json", plan)
            queue = fuse_claims_with_plan(
                claims_path=state / "claims.jsonl",
                dissection_plan_path=out / "dissection-plan.json",
            )
            self.assertEqual(queue["totals"]["hypotheses"], 1)
            self.assertEqual(queue["hypotheses"][0]["status"], "PROPOSED")

    def test_reddit_source_requires_approval(self) -> None:
        config = {
            "schema": COMMUNITY_CONFIG_SCHEMA,
            "id": "k3-community",
            "training_use": "prohibited",
            "sources": [
                {
                    "id": "reddit",
                    "kind": "reddit_oauth",
                    "enabled": True,
                    "approval_confirmed": False,
                    "subreddits": ["LocalLLaMA"],
                    "queries": ["Kimi K3"],
                }
            ],
        }
        normalized = validate_community_config(config)
        with tempfile.TemporaryDirectory() as temporary:
            receipt = sync_community(normalized, state_dir=Path(temporary))
            self.assertEqual(receipt["totals"]["blocked_sources"], 1)
            self.assertIn("approval", receipt["errors"][0]["error"].lower())

    def test_training_use_fails_closed(self) -> None:
        with self.assertRaises(KimiObservatoryError):
            validate_community_config(
                {
                    "schema": COMMUNITY_CONFIG_SCHEMA,
                    "id": "bad",
                    "training_use": "allowed",
                    "sources": [
                        {
                            "id": "import",
                            "kind": "jsonl_import",
                            "enabled": True,
                            "paths": ["items.jsonl"],
                        }
                    ],
                }
            )

    def test_runtime_trace_reduction_and_offload_simulation(self) -> None:
        from tier_runner.kimi3_common import append_jsonl, hash_json

        with tempfile.TemporaryDirectory() as temporary:
            trace = Path(temporary) / "trace.jsonl"
            for sequence, routes in enumerate(
                (
                    [[0, 1], [0, 2]],
                    [[0, 1], [0, 3]],
                    [[0, 1], [0, 2]],
                ),
                1,
            ):
                event = {
                    "schema": "tier-bench/kimi3-runtime-trace@1",
                    "sequence": sequence,
                    "created_at": "2026-07-27T00:00:00Z",
                    "model_revision": "model-sha",
                    "runtime_revision": "runtime-sha",
                    "task_family": "coding",
                    "prompt_id_sha256": "a" * 64,
                    "module": "model.layers.0.moe.router",
                    "module_class": "Router",
                    "kind": "router",
                    "inputs": [],
                    "outputs": [],
                    "experts": routes,
                    "taint": "runtime_observation",
                }
                event["event_sha256"] = hash_json(event)
                append_jsonl(trace, event)
            report = reduce_router_trace(trace)
            self.assertEqual(report["totals"]["router_modules"], 1)
            self.assertEqual(report["modules"][0]["top_experts"][0]["expert"], 0)
            simulation = simulate_expert_cache(
                trace,
                expert_bytes=1024,
                gpu_experts=2,
                ram_experts=4,
                pcie_gbps=20,
                nvme_gbps=5,
                prewarm_experts=1,
            )
            self.assertEqual(simulation["routes"], 12)
            self.assertGreater(simulation["hit_rates"]["gpu"], 0)

    def test_observatory_config_and_windows_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config_path = base / "experiments/kimi3/observatory.json"
            config_path.parent.mkdir(parents=True)
            raw = {
                "schema": OBSERVATORY_SCHEMA,
                "id": "k3-local",
                "model_root": "D:/Models/Kimi-K3",
                "state_dir": "D:/TierEstate/Kimi-K3",
                "grid_root": "D:/TierRuns/Kimi-K3",
                "community_config": "community.json",
                "frequent_interval_minutes": 30,
                "nightly_hour": 2,
                "numeric_patterns": ["experts", "router"],
                "defer_heavy_when_exists": ["D:/TierRuns/Kimi-K3/.grid-active"],
            }
            config = validate_observatory_config(raw, config_path=config_path)
            script = windows_schedule_script(config_path, config)
            self.assertIn("New-ScheduledTaskAction", script)
            self.assertIn("--profile frequent", script)
            self.assertIn("--profile nightly", script)
            self.assertIn("MultipleInstances IgnoreNew", script)


if __name__ == "__main__":
    unittest.main()
