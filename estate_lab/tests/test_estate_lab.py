from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from estate_lab.adapters import AdapterRefused, execute_adapter
from estate_lab.canonical import load_json, sha256_hex, stable_id
from estate_lab.errors import ManifestError, RouteRefused
from estate_lab.manifest import load_manifest, load_scenario
from estate_lab.model import AdapterSpec
from estate_lab.routing import choose_route
from estate_lab.runtime import EstateLab

HERE = Path(__file__).resolve().parents[1]
MANIFEST_PATH = HERE / "fixtures" / "estate.example.json"
SCENARIO_DIR = HERE / "fixtures" / "scenarios"


class CanonicalTests(unittest.TestCase):
    def test_stable_id_is_content_deterministic(self) -> None:
        first = stable_id("test1", {"b": 2, "a": 1})
        second = stable_id("test1", {"a": 1, "b": 2})
        self.assertEqual(first, second)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "duplicate.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(path)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(MANIFEST_PATH)

    def test_estate_inventory_is_nontrivial(self) -> None:
        self.assertGreaterEqual(len(self.manifest.organs), 14)
        self.assertGreaterEqual(len(self.manifest.adapters), 15)
        self.assertGreaterEqual(len(self.manifest.routes), 18)

    def test_all_reference_scenarios_validate(self) -> None:
        scenarios = [load_scenario(path, self.manifest) for path in sorted(SCENARIO_DIR.glob("*.json"))]
        self.assertEqual(len(scenarios), 5)
        self.assertEqual(len({scenario.scenario_id for scenario in scenarios}), 5)

    def test_machine_readable_schemas_parse(self) -> None:
        schema_dir = HERE / "schemas"
        schemas = sorted(schema_dir.glob("*.schema.json"))
        self.assertEqual(len(schemas), 13)
        for path in schemas:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_fallback_cycle_is_rejected(self) -> None:
        raw = copy.deepcopy(self.manifest.raw)
        direct = next(route for route in raw["routes"] if route["id"] == "route.world.direct")
        direct["fallback_route_ids"] = ["route.world.screen"]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cycle.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_manifest(path)


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(MANIFEST_PATH)
        cls.lab = EstateLab(cls.manifest)

    def choose(self, **kwargs):
        return choose_route(
            self.manifest,
            action_id="engineering.coolant_bypass.set",
            required_role="engineering",
            required_mandate="ship.engineering.control",
            adapter_status=self.lab.adapter_status,
            **kwargs,
        )

    def test_default_selects_direct_verified_route(self) -> None:
        decision = self.choose(
            candidate_route_ids=[
                "route.world.direct",
                "route.world.screen",
                "route.world.agent",
                "route.world.quest",
                "route.world.esp32",
            ]
        )
        self.assertEqual(decision.route_id, "route.world.direct")

    def test_healthy_primary_is_not_replaced_by_higher_scoring_fallback(self) -> None:
        decision = self.choose(candidate_route_ids=["route.world.screen"])
        self.assertEqual(decision.route_id, "route.world.screen")

    def test_unavailable_primary_uses_declared_fallback(self) -> None:
        decision = self.choose(
            candidate_route_ids=["route.world.screen"],
            unavailable_route_ids=["route.world.screen"],
        )
        self.assertEqual(decision.route_id, "route.world.direct")

    def test_physical_constraint_selects_esp32(self) -> None:
        decision = self.choose(
            candidate_route_ids=[
                "route.world.direct",
                "route.world.screen",
                "route.world.agent",
                "route.world.quest",
                "route.world.esp32",
            ],
            constraints={"require_tags": ["physical"]},
        )
        self.assertEqual(decision.route_id, "route.world.esp32")

    def test_impossible_constraint_refuses(self) -> None:
        with self.assertRaises(RouteRefused) as raised:
            self.choose(
                candidate_route_ids=["route.world.direct", "route.world.screen"],
                constraints={"require_tags": ["cloud"]},
            )
        self.assertEqual(raised.exception.reason, "no_admissible_route")


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(MANIFEST_PATH)
        cls.lab = EstateLab(cls.manifest)

    def test_common_control_equivalence_passes(self) -> None:
        scenario = load_scenario(SCENARIO_DIR / "common-control-proof-001.json", self.manifest)
        outcome = self.lab.run_scenario(scenario)
        self.assertEqual(outcome.status, "passed")
        self.assertTrue(outcome.equivalence["state_hashes_equal"])
        self.assertTrue(outcome.equivalence["output_hashes_equal"])
        self.assertTrue(outcome.equivalence["debrief_hashes_equal"])
        self.assertEqual(len(outcome.steps), 5)

    def test_reference_suite_passes(self) -> None:
        outcomes = [
            self.lab.run_scenario(load_scenario(path, self.manifest))
            for path in sorted(SCENARIO_DIR.glob("*.json"))
        ]
        self.assertEqual([outcome.status for outcome in outcomes], ["passed"] * 5)

    def test_run_identity_is_stable(self) -> None:
        scenario = load_scenario(SCENARIO_DIR / "decision-marker-001.json", self.manifest)
        first = self.lab.run_scenario(scenario)
        second = EstateLab(self.manifest).run_scenario(scenario)
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(first.final_state_hash, second.final_state_hash)

    def test_fault_trials_cover_idempotence_and_authority(self) -> None:
        scenario = load_scenario(SCENARIO_DIR / "common-control-proof-001.json", self.manifest)
        outcome = self.lab.run_scenario(scenario)
        trials = {trial["trial_id"]: trial for trial in outcome.fault_trials}
        self.assertTrue(trials["duplicate-is-idempotent"]["passed"])
        self.assertEqual(trials["duplicate-is-idempotent"]["actual"], "duplicate")
        self.assertTrue(trials["stale-ownership-epoch"]["passed"])
        self.assertEqual(
            trials["stale-ownership-epoch"]["actual"],
            "refused:ownership_epoch_stale",
        )

    def test_receipt_bundle_hashes_every_file(self) -> None:
        scenario = load_scenario(SCENARIO_DIR / "estate-circuit-001.json", self.manifest)
        with tempfile.TemporaryDirectory() as temp_dir:
            outcome = self.lab.run_scenario(scenario, output_root=Path(temp_dir))
            self.assertIsNotNone(outcome.receipt_dir)
            receipt = outcome.receipt_dir
            assert receipt is not None
            self.assertTrue((receipt / "run.json").is_file())
            self.assertTrue((receipt / "SUMMARY.md").is_file())
            self.assertTrue((receipt / "report.html").is_file())
            checksum_lines = (receipt / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(checksum_lines), 9)
            for line in checksum_lines:
                digest, relative = line.split("  ", 1)
                actual = hashlib.sha256((receipt / relative).read_bytes()).hexdigest()
                self.assertEqual(digest, actual)

    def test_live_mode_marks_missing_artifact_adapters_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "tier-bench").mkdir()
            lab = EstateLab(self.manifest, workspace=workspace, execution_mode="live")
            self.assertEqual(lab.adapter_status["world.input"], "unavailable")
            self.assertEqual(lab.adapter_status["screen.procedure"], "unavailable")


class CommandAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = {
            "semantic_id": "example.control.set",
            "subject": "example.control",
            "operation": "set",
            "state_path": "/example/control",
            "value": True,
            "authority": {
                "actor": "tester",
                "role": "operator",
                "mandate": "example.control",
                "ownership_epoch": 1,
            },
        }

    def make_adapter(self, script: Path) -> AdapterSpec:
        return AdapterSpec(
            adapter_id="test.command",
            organ_id="test-organ",
            kind="test-command",
            mode="command",
            capabilities=("semantic.input",),
            local_only=True,
            deterministic=True,
            replayable=True,
            evidence_class="measured",
            command=("python", str(script), "{request}", "{response}"),
            timeout_seconds=10,
        )

    def test_command_adapter_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "adapter.py"
            script.write_text(
                """
import json, sys
from pathlib import Path
req=json.loads(Path(sys.argv[1]).read_text())
res={
  'format':'axm-adapter-response/1',
  'adapter_id':req['adapter_id'],
  'phase':req['phase'],
  'accepted':True,
  'reason':None,
  'semantic_digest':req['semantic_digest'],
  'observations':{'mode':'command-test'}
}
Path(sys.argv[2]).write_text(json.dumps(res))
""".strip()
                + "\n",
                encoding="utf-8",
            )
            response = execute_adapter(
                self.make_adapter(script),
                phase="source",
                event=self.event,
                repository=root,
                execution_mode="live",
            )
            self.assertTrue(response["accepted"])
            self.assertEqual(response["semantic_digest"], sha256_hex({
                "semantic_id": self.event["semantic_id"],
                "subject": self.event["subject"],
                "operation": self.event["operation"],
                "state_path": self.event["state_path"],
                "value": self.event["value"],
                "authority": self.event["authority"],
            }))

    def test_command_adapter_semantic_mutation_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "adapter.py"
            script.write_text(
                """
import json, sys
from pathlib import Path
req=json.loads(Path(sys.argv[1]).read_text())
res={
  'format':'axm-adapter-response/1',
  'adapter_id':req['adapter_id'],
  'phase':req['phase'],
  'accepted':True,
  'semantic_digest':'0'*64,
  'observations':{}
}
Path(sys.argv[2]).write_text(json.dumps(res))
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(AdapterRefused) as raised:
                execute_adapter(
                    self.make_adapter(script),
                    phase="source",
                    event=self.event,
                    repository=root,
                    execution_mode="live",
                )
            self.assertEqual(raised.exception.reason, "adapter_semantic_mutation")


if __name__ == "__main__":
    unittest.main()
