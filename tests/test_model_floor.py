from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from tier_runner.model_floor import (
    compute_delta_report,
    compute_floor,
    ingest_waterline_tree,
    observations_from_waterline,
    validate_observation,
)
from tier_runner.model_floor_cli import windows_schedule_script
from tier_runner.model_floor_common import (
    FLOOR_CONFIG_SCHEMA,
    OBSERVATION_SCHEMA,
    REGISTRY_SCHEMA,
    SOURCE_CONFIG_SCHEMA,
    hash_json,
    read_jsonl,
)
from tier_runner.model_floor_external import _request, sync_sources, validate_source_config
from tier_runner.model_identity import (
    audit_identities,
    registry_from_models_json,
    resolve_identity,
    validate_registry,
)


def registry() -> dict:
    return {
        "schema": REGISTRY_SCHEMA,
        "id": "fixture-registry",
        "models": [
            {
                "id": "claude-opus-5",
                "provider": "anthropic",
                "family": "claude-opus",
                "access": "closed",
                "aliases": ["opus-5"],
                "official_ids": ["claude-opus-5"],
                "surfaces": [
                    {
                        "id": "anthropic:opus5",
                        "kind": "subscription_cli",
                        "status": "ready",
                        "runtime_patterns": ["claude-opus-5"],
                        "runtime_attestation_required": True,
                        "price": {
                            "input_per_million": 5,
                            "output_per_million": 25,
                            "basis": "fixture",
                        },
                    }
                ],
            },
            {
                "id": "claude-fable-5",
                "provider": "anthropic",
                "family": "claude-fable",
                "access": "closed",
                "aliases": ["fable-5"],
                "official_ids": ["claude-fable-5"],
                "surfaces": [
                    {
                        "id": "anthropic:fable5",
                        "kind": "subscription_cli",
                        "status": "ready",
                        "runtime_patterns": ["claude-fable-5"],
                        "runtime_attestation_required": True,
                        "price": {
                            "input_per_million": 10,
                            "output_per_million": 50,
                            "basis": "fixture",
                        },
                    }
                ],
            },
            {
                "id": "local-qwen",
                "provider": "ollama",
                "family": "qwen",
                "access": "open_weight",
                "aliases": [],
                "official_ids": ["local-qwen"],
                "surfaces": [
                    {
                        "id": "local:qwen",
                        "kind": "local_runtime",
                        "status": "ready",
                        "runtime_patterns": ["local-qwen"],
                        "runtime_attestation_required": True,
                        "price": {
                            "input_per_million": 0,
                            "output_per_million": 0,
                            "basis": "fixture",
                        },
                    }
                ],
            },
        ],
    }


def protocol() -> dict:
    return {
        "schema": "tier-bench/model-waterline-protocol@1",
        "id": "opus-fable-fixture",
        "subject_model": "claude-opus-5",
        "reference_model": "claude-fable-5",
        "routes": [
            {
                "id": "opus-low",
                "model_id": "claude-opus-5",
                "effort": "low",
                "role": "candidate",
                "lane": "native",
                "price": {"input_per_million": 5, "output_per_million": 25},
            },
            {
                "id": "fable-high",
                "model_id": "claude-fable-5",
                "effort": "high",
                "role": "reference",
                "lane": "native",
                "price": {"input_per_million": 10, "output_per_million": 50},
            },
        ],
    }


def waterline_report(task_count: int = 10, residue_task: int | None = None) -> dict:
    tasks = []
    for index in range(task_count):
        opus_clear = index != residue_task
        tasks.append(
            {
                "task_id": f"task-{index:02d}",
                "family": "repo-repair",
                "campaign_id": f"campaign-{index:02d}",
                "classification": (
                    "REPLICATED_NATIVE" if opus_clear else "REFERENCE_RESIDUE"
                ),
                "selected_route": "opus-low" if opus_clear else None,
                "selected_reference_route": "fable-high",
                "reference_routes_clear": ["fable-high"],
                "economic_status": "no_worse" if opus_clear else "not_applicable",
                "attention_status": "no_worse" if opus_clear else "not_applicable",
                "audit_status": "no_worse" if opus_clear else "not_applicable",
                "route_summaries": [
                    {
                        "route_id": "opus-low",
                        "role": "candidate",
                        "lane": "native",
                        "model_id": "claude-opus-5",
                        "effort": "low",
                        "state": "clears" if opus_clear else "wall",
                        "k": 3,
                        "trial_count": 3,
                        "valid_decisive": 3,
                        "passes": 3 if opus_clear else 0,
                        "failures": 0 if opus_clear else 3,
                        "invalid_trials": [],
                        "priced_cost_usd": 0.3,
                        "observed_cost_usd": 0.0,
                        "cost_per_verified_success_usd": 0.1 if opus_clear else None,
                        "attention_minutes": 0.0,
                        "attention_per_verified_success": 0.0 if opus_clear else None,
                    },
                    {
                        "route_id": "fable-high",
                        "role": "reference",
                        "lane": "native",
                        "model_id": "claude-fable-5",
                        "effort": "high",
                        "state": "clears",
                        "k": 3,
                        "trial_count": 3,
                        "valid_decisive": 3,
                        "passes": 3,
                        "failures": 0,
                        "invalid_trials": [],
                        "priced_cost_usd": 0.6,
                        "observed_cost_usd": 0.0,
                        "cost_per_verified_success_usd": 0.2,
                        "attention_minutes": 0.0,
                        "attention_per_verified_success": 0.0,
                    },
                ],
            }
        )
    return {
        "schema": "tier-bench/model-waterline-report@1",
        "protocol_id": "opus-fable-fixture",
        "protocol_sha256": "a" * 64,
        "generated_at": "2026-07-27T00:00:00Z",
        "waterline_status": (
            "PROPOSED_NATIVE_WATERLINE" if residue_task is None else "REFERENCE_RESIDUE_REMAINS"
        ),
        "capability_status": (
            "PROPOSED_NATIVE_WATERLINE" if residue_task is None else "REFERENCE_RESIDUE_REMAINS"
        ),
        "blocked_reasons": [],
        "tasks": tasks,
    }


def floor_config() -> dict:
    return {
        "schema": FLOOR_CONFIG_SCHEMA,
        "id": "fixture-floor",
        "minimum_sample_size": 3,
        "minimum_distinct_tasks": 10,
        "external_min_evidence": "detailed_report",
        "allow_external_unattested": True,
        "internal_identity_required": True,
        "objectives": [
            "cost_per_verified_success_usd",
            "attention_per_verified_success",
        ],
        "family_rules": [
            {
                "family": "repo-repair",
                "metric": "accepted",
                "direction": "higher",
                "adequacy_threshold": 1.0,
                "minimum_distinct_tasks": 10,
                "require_cost": True,
                "require_attention": True,
                "max_critical_escaped_defects": 0,
            }
        ],
    }


def external_observation(
    model_id: str,
    score: float,
    *,
    benchmark_id: str = "SWE-bench/SWE-bench_Verified",
    revision: str = "2026-07",
    scaffold: str = "official",
    observation_id: str | None = None,
) -> dict:
    benchmark = {
        "id": benchmark_id,
        "revision": revision,
        "task_family": "repo-repair",
        "metric": "resolved_rate",
        "direction": "higher",
        "unit": "percent",
        "scaffold": scaffold,
        "tools": "official",
        "attempts": 1,
        "context_policy": "official",
        "adequacy_threshold": None,
    }
    benchmark["comparison_key"] = hash_json(
        {
            key: benchmark.get(key)
            for key in (
                "id",
                "revision",
                "task_family",
                "metric",
                "direction",
                "unit",
                "scaffold",
                "tools",
                "attempts",
                "context_policy",
            )
        }
    )
    row = {
        "schema": OBSERVATION_SCHEMA,
        "id": observation_id or f"ext-{model_id}-{score}".replace(".", "-"),
        "observed_at": "2026-07-27T00:00:00Z",
        "source": {"id": "hf", "kind": "hf_leaderboard"},
        "model": {
            "declared_id": model_id,
            "runtime_id": None,
            "surface_id": None,
        },
        "benchmark": benchmark,
        "result": {
            "value": score,
            "sample_size": 500,
            "cost_usd": None,
            "observed_cost_usd": None,
            "cost_per_verified_success_usd": None,
            "attention_minutes": None,
            "attention_per_verified_success": None,
            "latency_ms": None,
            "autonomy_minutes": None,
            "critical_escaped_defects": 0,
        },
        "evidence": {
            "tier": "official_benchmark",
            "verified": True,
            "training_use": "prohibited",
        },
        "metadata": {},
    }
    row["observation_sha256"] = hash_json(
        {key: value for key, value in row.items() if key != "observation_sha256"}
    )
    return row


class ModelFloorTests(unittest.TestCase):
    def test_registry_and_runtime_attestation(self) -> None:
        index = validate_registry(registry())
        resolved = resolve_identity(
            {
                "declared_id": "opus-5",
                "runtime_id": "claude-opus-5",
                "surface_id": "anthropic:opus5",
            },
            index,
        )
        self.assertEqual(resolved["canonical_id"], "claude-opus-5")
        self.assertEqual(resolved["identity_status"], "attested")

        conflict = resolve_identity(
            {
                "declared_id": "opus-5",
                "runtime_id": "claude-fable-5",
                "surface_id": "anthropic:opus5",
            },
            index,
        )
        self.assertEqual(conflict["identity_status"], "conflicted")
        self.assertIn("runtime_model_mismatch", conflict["reasons"])

    def test_registry_from_models_json(self) -> None:
        converted = registry_from_models_json(
            {
                "models": {
                    "fixture": {
                        "provider": "ollama",
                        "input_per_1M": 0,
                        "output_per_1M": 0,
                        "tier_ceiling": "T2",
                    }
                }
            }
        )
        index = validate_registry(converted)
        self.assertIn("fixture", index.models)
        self.assertEqual(index.models["fixture"]["access"], "open_weight")

    def test_waterline_import_and_floor(self) -> None:
        index = validate_registry(registry())
        rows = observations_from_waterline(protocol(), waterline_report())
        self.assertEqual(len(rows), 20)
        report = compute_floor(index, floor_config(), rows)
        family = report["families"][0]
        self.assertEqual(family["status"], "FLOOR_SETTLED")
        self.assertEqual(
            family["selected_floor"]["identity"]["canonical_id"],
            "claude-opus-5",
        )
        self.assertEqual(family["model_matrix"]["local-qwen"]["status"], "unmeasured")
        self.assertEqual(
            family["model_matrix"]["claude-fable-5"]["status"], "adequate"
        )

    def test_reference_residue_prevents_opus_floor(self) -> None:
        index = validate_registry(registry())
        rows = observations_from_waterline(protocol(), waterline_report(residue_task=3))
        report = compute_floor(index, floor_config(), rows)
        family = report["families"][0]
        self.assertEqual(
            family["selected_floor"]["identity"]["canonical_id"],
            "claude-fable-5",
        )
        opus = next(
            row
            for row in family["routes"]
            if row["identity"]["canonical_id"] == "claude-opus-5"
        )
        self.assertIn("capability_below_threshold", opus["adequacy"]["reasons"])

    def test_external_cells_never_average_incompatible_scaffolds(self) -> None:
        index = validate_registry(registry())
        rows = [
            external_observation("claude-opus-5", 96.0, scaffold="agent-a"),
            external_observation(
                "claude-fable-5",
                95.0,
                scaffold="agent-b",
                observation_id="external-fable",
            ),
        ]
        report = compute_floor(index, floor_config(), rows)
        self.assertEqual(report["counts"]["external_cells"], 2)
        self.assertEqual(report["counts"]["settled_families"], 0)

    def test_external_baseline_distribution(self) -> None:
        index = validate_registry(registry())
        rows = [
            external_observation("claude-opus-5", 96.0),
            external_observation(
                "claude-fable-5", 95.0, observation_id="external-fable"
            ),
            external_observation(
                "local-qwen", 80.0, observation_id="external-qwen"
            ),
        ]
        report = compute_floor(index, floor_config(), rows)
        cell = report["external_baselines"][0]
        self.assertEqual(cell["count"], 3)
        self.assertEqual(cell["distribution"]["median"], 95.0)
        self.assertEqual(
            cell["best"][0]["model"]["canonical_id"], "claude-opus-5"
        )

    def test_identity_audit_keeps_unknown_visible(self) -> None:
        index = validate_registry(registry())
        rows = [external_observation("mystery-model", 50.0)]
        report = audit_identities(rows, index)
        self.assertEqual(report["counts"]["unknown"], 1)

    def test_delta_report_combines_internal_and_external_without_promoting_external(self) -> None:
        index = validate_registry(registry())
        external = [
            external_observation("claude-opus-5", 96.0),
            external_observation(
                "claude-fable-5", 95.0, observation_id="external-fable"
            ),
        ]
        report = compute_delta_report(
            index, protocol(), waterline_report(), external
        )
        self.assertEqual(report["internal"]["counts"]["native_replications"], 10)
        self.assertEqual(report["external"]["pair_count"], 1)
        self.assertEqual(
            report["economics"]["declared_token_price_ratio_subject_to_reference"],
            0.5,
        )

    def test_jsonl_import_and_social_score_do_not_upgrade_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            source_path = temp / "community.jsonl"
            source_path.write_text(
                json.dumps(
                    {
                        "id": "post-1",
                        "title": "Opus 5 benchmark",
                        "body": "claude-opus-5 scored 96% and ran 42 tok/s",
                        "url": "https://example.invalid/post-1",
                        "score": 100000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = temp / "sources.json"
            config = {
                "schema": SOURCE_CONFIG_SCHEMA,
                "id": "fixture-sources",
                "excerpt_chars": 500,
                "retention_days": 30,
                "sources": [
                    {
                        "id": "manual-community",
                        "kind": "jsonl_import",
                        "enabled": True,
                        "evidence_tier": "assertion",
                        "verified": False,
                        "training_use": "prohibited",
                        "paths": [str(source_path)],
                    },
                    {
                        "id": "reddit",
                        "kind": "reddit_oauth",
                        "enabled": True,
                        "evidence_tier": "assertion",
                        "verified": False,
                        "training_use": "prohibited",
                        "approval_confirmed": False,
                        "subreddits": ["LocalLLaMA"],
                        "queries": ["Opus 5"],
                    },
                ],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            receipt = sync_sources(
                config, config_path=config_path, state_dir=temp / "state"
            )
            self.assertEqual(receipt["totals"]["sources_blocked"], 1)
            community = read_jsonl(temp / "state" / "community.jsonl")
            self.assertEqual(community[0]["evidence_tier"], "assertion")
            self.assertEqual(community[0]["training_use"], "prohibited")
            self.assertIn("%", {metric["unit"] for metric in community[0]["metrics"]})

    def test_structured_import_becomes_external_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            source_path = temp / "stats.jsonl"
            source_path.write_text(
                json.dumps(
                    {
                        "id": "run-1",
                        "model_id": "claude-opus-5",
                        "score": 88.0,
                        "sample_size": 225,
                        "cost_usd": 12.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = temp / "sources.json"
            config = {
                "schema": SOURCE_CONFIG_SCHEMA,
                "id": "fixture-stats",
                "excerpt_chars": 500,
                "retention_days": 30,
                "sources": [
                    {
                        "id": "manual-stats",
                        "kind": "jsonl_import",
                        "enabled": True,
                        "evidence_tier": "reproducible_receipt",
                        "verified": True,
                        "training_use": "prohibited",
                        "paths": [str(source_path)],
                        "benchmark": {
                            "id": "aider-polyglot",
                            "revision": "fixture",
                            "task_family": "repo-repair",
                            "metric": "percent_correct",
                            "direction": "higher",
                            "unit": "percent",
                            "scaffold": "aider",
                            "tools": "aider",
                            "attempts": 2,
                            "context_policy": "repo-map",
                        },
                    }
                ],
            }
            receipt = sync_sources(
                config, config_path=config_path, state_dir=temp / "state"
            )
            self.assertEqual(receipt["totals"]["observations"], 1)
            row = read_jsonl(temp / "state" / "observations.jsonl")[0]
            validate_observation(row)
            self.assertEqual(row["result"]["cost_usd"], 12.0)


    def test_http_json_paginates_and_preserves_comparison_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            config_path = temp / "sources.json"
            config = {
                "schema": SOURCE_CONFIG_SCHEMA,
                "id": "paged-fixture",
                "excerpt_chars": 500,
                "retention_days": 30,
                "sources": [
                    {
                        "id": "paged-leaderboard",
                        "kind": "http_json",
                        "enabled": True,
                        "evidence_tier": "official_benchmark",
                        "verified": True,
                        "training_use": "prohibited",
                        "url": (
                            "https://example.invalid/rows?"
                            "dataset=fixture&config=latest&split=latest&offset=0&length=2"
                        ),
                        "benchmark": {
                            "id": "fixture/arena",
                            "revision": "rolling",
                            "task_family": "human-preference",
                            "metric": "rating",
                            "direction": "higher",
                            "unit": "rating",
                            "scaffold": "pairwise",
                            "tools": "managed",
                            "attempts": 1,
                            "context_policy": "managed",
                        },
                        "mapping": {
                            "records": "rows",
                            "id": "row.model_name",
                            "model": "row.model_name",
                            "score": "row.rating",
                            "revision": "row.publish_date",
                            "dimensions": {"category": "row.category"},
                        },
                        "pagination": {
                            "kind": "offset_length",
                            "offset_param": "offset",
                            "length_param": "length",
                            "page_size": 2,
                            "start_offset": 0,
                            "max_pages": 5,
                            "total_path": "num_rows_total",
                            "partial_path": "partial",
                            "allow_partial": False,
                        },
                    }
                ],
            }
            pages = {
                0: {
                    "rows": [
                        {
                            "row_idx": 0,
                            "row": {
                                "model_name": "Claude Opus 5",
                                "rating": 1300.0,
                                "category": "overall",
                                "publish_date": "2026-07-27",
                            },
                        },
                        {
                            "row_idx": 1,
                            "row": {
                                "model_name": "Claude Opus 5",
                                "rating": 1275.0,
                                "category": "coding",
                                "publish_date": "2026-07-27",
                            },
                        },
                    ],
                    "num_rows_total": 3,
                    "partial": False,
                },
                2: {
                    "rows": [
                        {
                            "row_idx": 2,
                            "row": {
                                "model_name": "Claude Fable 5",
                                "rating": 1320.0,
                                "category": "overall",
                                "publish_date": "2026-07-27",
                            },
                        }
                    ],
                    "num_rows_total": 3,
                    "partial": False,
                },
            }
            observed_offsets: list[int] = []

            def fake_request_json(url: str, **_: object):
                query = parse_qs(urlsplit(url).query)
                offset = int(query["offset"][0])
                observed_offsets.append(offset)
                value = pages[offset]
                payload = json.dumps(value).encode("utf-8")
                return value, {"etag": f"page-{offset}"}, 200, payload

            with patch(
                "tier_runner.model_floor_external._request_json",
                side_effect=fake_request_json,
            ):
                receipt = sync_sources(
                    config,
                    config_path=config_path,
                    state_dir=temp / "state",
                )

            self.assertEqual(observed_offsets, [0, 2])
            self.assertEqual(receipt["totals"]["sources_succeeded"], 1)
            self.assertEqual(len(receipt["sources"][0]["snapshots"]), 2)
            observations = read_jsonl(temp / "state" / "observations.jsonl")
            self.assertEqual(len(observations), 3)
            opus = [
                row
                for row in observations
                if row["model"]["declared_id"] == "Claude Opus 5"
            ]
            self.assertEqual(len(opus), 2)
            self.assertEqual(
                {row["benchmark"]["dimensions"]["category"] for row in opus},
                {"overall", "coding"},
            )
            self.assertEqual(
                len({row["benchmark"]["comparison_key"] for row in opus}),
                2,
            )
            self.assertEqual(len({row["id"] for row in opus}), 2)
            for row in observations:
                validate_observation(row)

    def test_http_json_partial_dataset_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            config_path = temp / "sources.json"
            config = {
                "schema": SOURCE_CONFIG_SCHEMA,
                "id": "partial-fixture",
                "excerpt_chars": 500,
                "retention_days": 30,
                "sources": [
                    {
                        "id": "partial-leaderboard",
                        "kind": "http_json",
                        "enabled": True,
                        "evidence_tier": "official_benchmark",
                        "verified": True,
                        "training_use": "prohibited",
                        "url": "https://example.invalid/rows?offset=0&length=100",
                        "benchmark": {
                            "id": "fixture/partial",
                            "revision": "rolling",
                            "task_family": "human-preference",
                            "metric": "rating",
                            "direction": "higher",
                            "unit": "rating",
                            "scaffold": "pairwise",
                            "tools": "managed",
                            "attempts": 1,
                            "context_policy": "managed",
                        },
                        "mapping": {
                            "records": "rows",
                            "id": "row.model_name",
                            "model": "row.model_name",
                            "score": "row.rating",
                        },
                        "pagination": {
                            "kind": "offset_length",
                            "page_size": 100,
                            "max_pages": 2,
                            "total_path": "num_rows_total",
                            "partial_path": "partial",
                            "allow_partial": False,
                        },
                    }
                ],
            }
            value = {
                "rows": [
                    {
                        "row_idx": 0,
                        "row": {"model_name": "Claude Opus 5", "rating": 1300.0},
                    }
                ],
                "num_rows_total": 1000,
                "partial": True,
            }

            def fake_request_json(url: str, **_: object):
                payload = json.dumps(value).encode("utf-8")
                return value, {}, 200, payload

            with patch(
                "tier_runner.model_floor_external._request_json",
                side_effect=fake_request_json,
            ):
                receipt = sync_sources(
                    config,
                    config_path=config_path,
                    state_dir=temp / "state",
                )

            self.assertEqual(receipt["totals"]["sources_failed"], 1)
            self.assertIn("partial dataset view", receipt["errors"][0]["error"])
            self.assertEqual(
                read_jsonl(temp / "state" / "observations.jsonl"),
                [],
            )

    def test_registry_overrides_add_aliases_and_models(self) -> None:
        converted = registry_from_models_json(
            {
                "models": {
                    "claude-opus-5": {
                        "provider": "anthropic",
                        "input_per_1M": 5,
                        "output_per_1M": 25,
                        "tier_ceiling": "T5",
                    }
                }
            },
            overrides={
                "schema": "tier-bench/model-floor-registry-overrides@1",
                "models": [
                    {
                        "id": "claude-opus-5",
                        "aliases": ["Claude Opus 5"],
                    },
                    {
                        "id": "new-open-model",
                        "provider": "fixture",
                        "family": "new-open-model",
                        "access": "open_weight",
                        "aliases": ["New Open Model"],
                        "official_ids": ["new-open-model"],
                        "surfaces": [
                            {
                                "id": "local:new-open-model",
                                "kind": "local_runtime",
                                "status": "unmeasured",
                                "runtime_patterns": ["new-open-model"],
                                "runtime_attestation_required": True,
                                "price": {
                                    "input_per_million": 0,
                                    "output_per_million": 0,
                                    "basis": "fixture",
                                },
                            }
                        ],
                    },
                ],
            },
        )
        index = validate_registry(converted)
        self.assertEqual(
            index.aliases["claude opus 5"], "claude-opus-5"
        )
        self.assertIn("new-open-model", index.models)


    def test_ingest_tree_discovers_reports_and_protocols(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            protocols = temp / "protocols"
            reports = temp / "reports"
            protocols.mkdir()
            reports.mkdir()
            (protocols / "protocol.json").write_text(
                json.dumps(protocol()), encoding="utf-8"
            )
            (reports / "report.json").write_text(
                json.dumps(waterline_report(task_count=2)), encoding="utf-8"
            )
            rows, receipt = ingest_waterline_tree(protocols, reports)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(receipt["reports"]), 1)
            self.assertEqual(receipt["unmatched_reports"], [])

    def test_schedule_is_headless_and_batched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            for name in ("sources.json", "registry.json", "floor.json"):
                (temp / name).write_text("{}")
            script = windows_schedule_script(
                repo=temp,
                source_config=temp / "sources.json",
                registry=temp / "registry.json",
                floor_config=temp / "floor.json",
                state_dir=temp / "state",
                protocol_root=temp / "protocols",
                reports_root=temp / "reports",
                frequent_minutes=60,
                nightly_hour=3,
            )
            self.assertIn("MultipleInstances IgnoreNew", script)
            self.assertIn("tier_runner.model_floor_cli refresh", script)
            self.assertIn("--protocol-root", script)
        self.assertIn("--reports-root", script)

    def test_http_429_without_retry_after_uses_bounded_cooldown(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def __enter__(self):
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok": true}'

        throttled = HTTPError(
            "https://example.invalid/rows",
            429,
            "rate limited",
            {},
            io.BytesIO(b"rate limited"),
        )
        with (
            patch(
                "tier_runner.model_floor_external.urlopen",
                side_effect=[throttled, Response()],
            ),
            patch("tier_runner.model_floor_external.time.sleep") as sleep,
        ):
            payload, headers, status = _request(
                "https://example.invalid/rows",
                retries=1,
            )

        self.assertEqual(payload, b'{"ok": true}')
        self.assertEqual(headers, {})
        self.assertEqual(status, 200)
        sleep.assert_called_once_with(60.0)


if __name__ == "__main__":
    unittest.main()
