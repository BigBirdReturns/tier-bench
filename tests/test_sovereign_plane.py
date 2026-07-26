#!/usr/bin/env python3
"""Zero-model-call tests for the sovereign desktop plane."""
from __future__ import annotations

import copy
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import shutil
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.sovereign_cache import (  # noqa: E402
    cache_inventory_from_registry,
    normalize_server_url,
    restore_slot_cache,
    save_slot_cache,
)
from tier_runner.sovereign_common import PlaneError, sha256_file  # noqa: E402
from tier_runner.sovereign_context import (  # noqa: E402
    materialize_context_pack,
    prefix_fingerprint,
    verify_context_receipt,
)
from tier_runner.sovereign_plan import (  # noqa: E402
    compile_campaigns,
    compile_plan,
    verify_plan,
)
from tier_runner.sovereign_schema import validate_manifest  # noqa: E402


def fixture(parent: Path) -> tuple[Path, dict]:
    repo = parent / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("constitution\n" * 100, encoding="utf-8")
    (repo / "MAP.md").write_text("map\n" * 80, encoding="utf-8")
    (repo / "TASK.md").write_text("task evidence\n" * 25, encoding="utf-8")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "chat.jsonl").write_text('{"message":"one"}\n', encoding="utf-8")
    manifest = {
        "schema": "tier-bench/sovereign-desktop-plane@1",
        "id": "fixture-plane",
        "title": "Fixture plane",
        "optimization": {
            "primary": "operator_attention",
            "wall_clock": "secondary",
            "max_parallel_jobs": 2,
        },
        "resources": [
            {"id": "gpu:3090", "kind": "gpu", "capacity": 1, "roles": ["decode"]},
            {"id": "gpu:4060", "kind": "gpu", "capacity": 1, "roles": ["extract"]},
            {"id": "quota:frontier", "kind": "quota", "capacity": 1, "roles": ["overflow"]},
        ],
        "runtimes": [
            {
                "id": "local-3090",
                "model_id": "qwen-large",
                "tokenizer_id": "qwen-tokenizer",
                "runtime_id": "llama.cpp",
                "runtime_version": "b9000",
                "quantization": "Q4_K_M",
                "resource": "gpu:3090",
                "execution_class": "local",
                "source_access": "source_and_weights",
                "context_limit_tokens": 65536,
                "capabilities": {"code": True, "prefix_cache": True},
                "cache": {"mode": "persistent_slot", "persistent": True},
                "backend": {
                    "manifest": "backends/local.json",
                    "arm": "arm_b",
                    "estimated_max_cost_usd": 0,
                },
                "load_cost_seconds": 40,
                "declared_order": 0,
            },
            {
                "id": "local-4060",
                "model_id": "qwen-utility",
                "tokenizer_id": "qwen-tokenizer",
                "runtime_id": "llama.cpp",
                "runtime_version": "b9000",
                "quantization": "Q5_K_M",
                "resource": "gpu:4060",
                "execution_class": "local",
                "source_access": "source_and_weights",
                "context_limit_tokens": 32768,
                "capabilities": {"extract": True, "prefix_cache": True},
                "cache": {"mode": "prefix", "persistent": False},
                "backend": {
                    "manifest": "backends/utility.json",
                    "arm": "arm_b",
                    "estimated_max_cost_usd": 0,
                },
                "load_cost_seconds": 10,
                "declared_order": 1,
            },
            {
                "id": "frontier",
                "model_id": "frontier-model",
                "tokenizer_id": "provider-native",
                "runtime_id": "provider-cli",
                "runtime_version": "1",
                "quantization": "provider-native",
                "resource": "quota:frontier",
                "execution_class": "remote_closed",
                "source_access": "subscription_only",
                "context_limit_tokens": 1000000,
                "capabilities": {"code": True, "extract": True, "prefix_cache": True},
                "cache": {"mode": "prefix", "persistent": False},
                "backend": {
                    "manifest": "backends/frontier.json",
                    "arm": "arm_b",
                    "estimated_max_cost_usd": 1,
                },
                "load_cost_seconds": 0,
                "declared_order": 2,
            },
        ],
        "context_packs": [
            {
                "id": "repo-pack",
                "source_identity": "git:fixture/repo",
                "source_revision": "abc123",
                "source_tokens": 100000,
                "blocks": [
                    {
                        "id": "constitution",
                        "kind": "instruction",
                        "stability": "estate",
                        "sha256": sha256_file(repo / "README.md"),
                        "tokens": 5000,
                        "source": "README",
                        "content_path": "README.md",
                    },
                    {
                        "id": "map",
                        "kind": "retrieval",
                        "stability": "campaign",
                        "sha256": sha256_file(repo / "MAP.md"),
                        "tokens": 6000,
                        "source": "repository map",
                        "content_path": "MAP.md",
                    },
                    {
                        "id": "task",
                        "kind": "source",
                        "stability": "job",
                        "sha256": sha256_file(repo / "TASK.md"),
                        "tokens": 1000,
                        "source": "task slice",
                        "content_path": "TASK.md",
                    },
                ],
            },
            {
                "id": "chat-pack",
                "source_identity": "file:chat.jsonl",
                "source_revision": "one",
                "source_tokens": 500000,
                "blocks": [
                    {
                        "id": "chat-query",
                        "kind": "retrieval",
                        "stability": "job",
                        "sha256": sha256_file(repo / "chat.jsonl"),
                        "tokens": 2500,
                        "source": "chat slice",
                        "content_path": "chat.jsonl",
                    }
                ],
            },
        ],
        "cache_inventory": [],
        "jobs": [
            {
                "id": "repair",
                "title": "Repair app",
                "task": "Repair the bounded app defect.",
                "files": ["app.py"],
                "context_pack": "repo-pack",
                "context_delivery": "prompt_prefix",
                "runtime_candidates": ["local-3090", "frontier"],
                "privacy": "sovereign_preferred",
                "required_capabilities": ["code"],
                "priority": 90,
                "delta_tokens": 800,
                "expected_output_tokens": 1000,
                "depends_on": [],
                "acceptance": "python -m py_compile app.py",
                "campaign": {"mode": "local_first", "k": 1, "max_trials_per_route": 3},
            },
            {
                "id": "harden",
                "title": "Harden app",
                "task": "Harden the adjacent invariant.",
                "files": ["app.py"],
                "context_pack": "repo-pack",
                "context_delivery": "prompt_prefix",
                "runtime_candidates": ["local-3090", "frontier"],
                "privacy": "sovereign_preferred",
                "required_capabilities": ["code"],
                "priority": 80,
                "delta_tokens": 500,
                "expected_output_tokens": 800,
                "depends_on": ["repair"],
                "acceptance": "python -m py_compile app.py",
                "campaign": {"mode": "local_first", "k": 1, "max_trials_per_route": 3},
            },
            {
                "id": "mine-chat",
                "title": "Mine chat",
                "task": "Extract one recurring task family.",
                "files": ["chat.jsonl"],
                "context_pack": "chat-pack",
                "context_delivery": "read_only_file",
                "runtime_candidates": ["local-4060", "frontier"],
                "privacy": "local_only",
                "required_capabilities": ["extract"],
                "priority": 70,
                "delta_tokens": 200,
                "expected_output_tokens": 400,
                "depends_on": [],
                "acceptance": "python -c \"print('ok')\"",
                "campaign": {"mode": "local_first", "k": 1, "max_trials_per_route": 3},
            },
        ],
    }
    return repo, manifest


def test_validate_and_plan(parent: Path) -> None:
    _, raw = fixture(parent)
    manifest = validate_manifest(raw)
    assert manifest["id"] == "fixture-plane"
    plan = compile_plan(raw)
    assert plan["totals"]["jobs_planned"] == 3
    assert plan["totals"]["jobs_blocked"] == 0
    assert plan["totals"]["selection_avoided_tokens"] > 0
    rows = {
        job["job_id"]: job
        for batch in plan["batches"]
        for job in batch["jobs"]
    }
    assert rows["repair"]["planned_cache_reuse"] == "miss"
    assert rows["harden"]["planned_cache_reuse"] == "planned_after_prior_job"
    assert rows["harden"]["planned_cache_read_tokens"] == 11000
    assert len(plan["waves"]) >= 2
    assert {job["resource"] for job in plan["waves"][0]["jobs"]} == {
        "gpu:3090",
        "gpu:4060",
    }


def test_plan_tamper_fails(parent: Path) -> None:
    _, raw = fixture(parent)
    plan = compile_plan(raw)
    assert verify_plan(raw, plan) == []
    plan["totals"]["jobs_planned"] = 9000
    assert any("totals" in error for error in verify_plan(raw, plan))


def test_runtime_version_invalidates_prefix(parent: Path) -> None:
    _, raw = fixture(parent)
    manifest = validate_manifest(raw)
    runtimes = {row["id"]: row for row in manifest["runtimes"]}
    packs = {row["id"]: row for row in manifest["context_packs"]}
    first = prefix_fingerprint(runtimes["local-3090"], packs["repo-pack"])
    changed = copy.deepcopy(runtimes["local-3090"])
    changed["runtime_version"] = "b9001"
    second = prefix_fingerprint(changed, packs["repo-pack"])
    assert first != second


def test_cache_inventory_must_bind_exactly(parent: Path) -> None:
    _, raw = fixture(parent)
    manifest = validate_manifest(raw)
    runtimes = {row["id"]: row for row in manifest["runtimes"]}
    packs = {row["id"]: row for row in manifest["context_packs"]}
    prefix = prefix_fingerprint(runtimes["local-3090"], packs["repo-pack"])
    raw["cache_inventory"] = [
        {
            "runtime_id": "local-3090",
            "context_pack": "repo-pack",
            "prefix_fingerprint": prefix,
            "tier": "disk",
            "tokens": 11000,
            "valid": True,
            "receipt_sha256": "a" * 64,
        }
    ]
    plan = compile_plan(raw)
    first = plan["batches"][0]["jobs"][0]
    assert first["planned_cache_reuse"] == "observed_inventory"
    bad = copy.deepcopy(raw)
    bad["runtimes"][0]["runtime_version"] = "drift"
    try:
        compile_plan(bad)
    except PlaneError as exc:
        assert "cache inventory binding mismatch" in str(exc)
    else:
        raise AssertionError("runtime drift should invalidate cache inventory")


def test_materialize_and_verify(parent: Path) -> None:
    repo, raw = fixture(parent)
    receipt = materialize_context_pack(raw, "repo-pack", repo, parent / "packs")
    directory = parent / "packs" / receipt["pack_fingerprint"]
    assert (directory / "prefix.txt").is_file()
    assert (directory / "dynamic.txt").is_file()
    assert verify_context_receipt(directory) == []
    prefix = (directory / "prefix.txt").read_text(encoding="utf-8")
    assert "constitution" in prefix and "map" in prefix
    assert "task" not in prefix
    dynamic = (directory / "dynamic.txt").read_text(encoding="utf-8")
    assert "task" in dynamic


def test_block_order_fails_closed(parent: Path) -> None:
    _, raw = fixture(parent)
    blocks = raw["context_packs"][0]["blocks"]
    blocks[0], blocks[2] = blocks[2], blocks[0]
    try:
        validate_manifest(raw)
    except PlaneError as exc:
        assert "stable prefix blocks" in str(exc)
    else:
        raise AssertionError("dynamic content before stable prefix should fail")


def test_blocked_dependency_propagates(parent: Path) -> None:
    _, raw = fixture(parent)
    raw["runtimes"][0]["capabilities"]["code"] = False
    raw["jobs"][0]["runtime_candidates"] = ["local-3090"]
    plan = compile_plan(raw)
    blocked = {row["job_id"]: row for row in plan["blocked"]}
    assert "repair" in blocked
    assert blocked["harden"]["reason"] == "dependency blocked"


def test_campaign_compilation(parent: Path) -> None:
    _, raw = fixture(parent)
    bundle = compile_campaigns(raw)
    assert len(bundle["campaigns"]) == 3
    campaign = next(item for item in bundle["campaigns"] if item["title"] == "Repair app")
    assert campaign["queue_now"] is False
    assert [route["id"] for route in campaign["routes"]] == ["local-3090", "frontier"]
    assert campaign["sovereign_context"]["source_tokens"] == 100000


class SlotHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append({"path": self.path, "body": body})
        action = self.path.split("action=", 1)[1]
        payload = {
            "id_slot": 0,
            "filename": body["filename"],
            "n_saved": 11000 if action == "save" else 0,
            "n_written": 12345 if action == "save" else 0,
        }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002
        return


def test_loopback_cache_save_restore(parent: Path) -> None:
    _, raw = fixture(parent)
    server = HTTPServer(("127.0.0.1", 0), SlotHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        saved = save_slot_cache(
            raw,
            runtime_id="local-3090",
            pack_id="repo-pack",
            server_url=base,
            slot=0,
            filename="repo-pack.bin",
            state_dir=parent / "state",
        )
        assert saved["observed"] is True
        restored = restore_slot_cache(
            raw,
            runtime_id="local-3090",
            pack_id="repo-pack",
            server_url=base,
            slot=0,
            filename="repo-pack.bin",
            state_dir=parent / "state",
        )
        assert restored["save_receipt_sha256"] == saved["receipt_sha256"]
        inventory = cache_inventory_from_registry(raw, parent / "state")
        assert len(inventory) == 1 and inventory[0]["tokens"] == 11000
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_network_cache_refuses_remote_by_default(parent: Path) -> None:
    _, raw = fixture(parent)
    try:
        save_slot_cache(
            raw,
            runtime_id="local-3090",
            pack_id="repo-pack",
            server_url="http://192.0.2.1:8080",
            slot=0,
            filename="x.bin",
            state_dir=parent / "state",
            dry_run=True,
        )
    except PlaneError as exc:
        assert "non-loopback" in str(exc)
    else:
        raise AssertionError("remote cache control should require explicit unsafe-network")
    assert normalize_server_url("http://localhost:8080") == "http://localhost:8080"


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="sovereign-plane-"))
    tests = [
        test_validate_and_plan,
        test_plan_tamper_fails,
        test_runtime_version_invalidates_prefix,
        test_cache_inventory_must_bind_exactly,
        test_materialize_and_verify,
        test_block_order_fails_closed,
        test_blocked_dependency_propagates,
        test_campaign_compilation,
        test_loopback_cache_save_restore,
        test_network_cache_refuses_remote_by_default,
    ]
    failed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index:02d}"
            case.mkdir()
            try:
                test(case)
                print(f"  ok  {test.__name__}")
            except Exception as exc:
                failed += 1
                print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        print(f"\n{len(tests) - failed}/{len(tests)} sovereign-plane tests passed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
