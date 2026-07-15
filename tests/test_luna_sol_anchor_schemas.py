from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_strict_output_schemas import validate_instance, validate_schema  # noqa: E402

SCHEMA_DIR = ROOT / "experiments" / "luna_sol_anchor_replication_v2" / "prompts" / "schemas"
PRODUCTION = ("full_agent.schema.json", "planner_initial.schema.json", "planner_continuation.schema.json", "spark.schema.json", "final_receipt.schema.json")


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def anchor() -> dict:
    return {"objective": "preserve durable progress", "invariants": ["bounded"], "decisions": ["stage first"], "open_risks": [], "stop_condition": "validator passes"}


def crate(phase: str) -> dict:
    return {"crate_id": f"crate-{phase}", "objective": "bounded work", "allowed_paths": ["src/ledger_stage.py"] if phase == "one" else ["src/solution.py"], "forbidden_paths": ["src/solution.py"] if phase == "one" else ["src/ledger_stage.py"], "dependencies": [] if phase == "one" else ["hand_1"], "visible_context_refs": ["state"], "validator_ids": ["stage"] if phase == "one" else ["visible"], "command_budget": 4, "wall_time_seconds": 60, "stop_condition": "validator passes"}


def fixture(name: str) -> dict:
    if name == "full_agent.schema.json":
        return {"summary": "done", "files_inspected_claimed": [], "files_changed_claimed": [], "commands_claimed": [], "unresolved_blockers": []}
    if name == "spark.schema.json":
        return {"crate_id": "crate-one", "summary": "done", "files_inspected_claimed": [], "files_changed_claimed": [], "commands_claimed": [], "unresolved_blockers": []}
    if name == "final_receipt.schema.json":
        return {"trial": "replicate_001", "arm": "SOL_FULL", "candidate": None, "disposition": "NOT_RUN", "patch_sha256": None, "state_sha256": None, "hidden_grade": "NOT_RUN"}
    if name == "planner_initial.schema.json":
        return {"action": "spawn_hand_1", "anchor_state": anchor(), "work_graph": [{"node_id": "hand_1", "objective": "stage", "depends_on": []}, {"node_id": "hand_2", "objective": "rollup", "depends_on": ["hand_1"]}], "crate": crate("one"), "decision_record": ["two dependent hands"]}
    return {"action": "spawn_hand_2", "anchor_state": anchor(), "crate": crate("two")}


class LunaSchemaTests(unittest.TestCase):
    def assert_invalid(self, schema: dict, path: str | None = None) -> None:
        errors = validate_schema(schema)
        self.assertTrue(errors)
        if path:
            self.assertTrue(any(error["path"] == path for error in errors), errors)

    def test_exact_captured_bad_action_schema_rejected_at_action(self) -> None:
        schema = load("planner_initial.schema.json")
        schema["properties"]["action"] = {"const": "spawn_hand_1"}
        self.assert_invalid(schema, "/properties/action")

    def test_single_value_string_enum_is_accepted(self) -> None:
        schema = load("planner_initial.schema.json")
        schema["properties"]["action"] = {"type": "string", "enum": ["spawn_hand_1"]}
        self.assertFalse(validate_schema(schema), validate_schema(schema))

    def test_const_with_explicit_compatible_type_is_accepted(self) -> None:
        schema = load("planner_initial.schema.json")
        schema["properties"]["action"] = {"type": "string", "const": "spawn_hand_1"}
        self.assertFalse(validate_schema(schema), validate_schema(schema))

    def test_const_without_type_is_rejected(self) -> None:
        schema = load("planner_initial.schema.json")
        schema["properties"]["action"] = {"const": "spawn_hand_1"}
        self.assert_invalid(schema, "/properties/action")

    def test_enum_without_type_is_rejected(self) -> None:
        schema = load("planner_initial.schema.json")
        schema["properties"]["action"] = {"enum": ["spawn_hand_1"]}
        self.assert_invalid(schema, "/properties/action")

    def test_array_without_type_is_rejected(self) -> None:
        schema = load("full_agent.schema.json")
        schema["properties"]["files_inspected_claimed"] = {"items": {"type": "string"}}
        self.assert_invalid(schema, "/properties/files_inspected_claimed")

    def test_array_items_without_type_closure_are_rejected(self) -> None:
        schema = load("full_agent.schema.json")
        schema["properties"]["files_inspected_claimed"] = {"type": "array", "items": {}}
        self.assert_invalid(schema, "/properties/files_inspected_claimed/items")

    def test_refs_to_typed_and_untyped_definitions(self) -> None:
        base = {"type": "object", "additionalProperties": False, "properties": {"value": {"$ref": "#/$defs/value"}}, "required": ["value"], "$defs": {"value": {"type": "string"}}}
        self.assertFalse(validate_schema(base), validate_schema(base))
        broken = copy.deepcopy(base); broken["$defs"]["value"] = {}
        self.assertTrue(validate_schema(broken))

    def test_every_anyof_branch_requires_explicit_type_closure(self) -> None:
        valid = {"type": "object", "additionalProperties": False, "properties": {"choice": {"anyOf": [{"type": "string"}, {"type": "null"}]}}, "required": ["choice"]}
        self.assertFalse(validate_schema(valid), validate_schema(valid))
        broken = copy.deepcopy(valid); broken["properties"]["choice"]["anyOf"][1] = {}
        self.assertTrue(validate_schema(broken), validate_schema(broken))

    def test_root_anyof_is_rejected(self) -> None:
        self.assert_invalid({"anyOf": [{"type": "object", "additionalProperties": False, "properties": {}, "required": []}], "type": "object"}, "/anyOf")

    def test_all_production_schemas_pass_strict_gate(self) -> None:
        for name in PRODUCTION:
            errors = validate_schema(load(name), name)
            self.assertFalse(errors, (name, errors))

    def test_all_production_fixtures_reject_missing_and_extra_keys(self) -> None:
        for name in PRODUCTION:
            schema = load(name); value = fixture(name)
            self.assertFalse(validate_instance(value, schema), name)
            missing = copy.deepcopy(value); missing.pop(schema["required"][0])
            self.assertTrue(validate_instance(missing, schema), name)
            extra = copy.deepcopy(value); extra["unexpected"] = True
            self.assertTrue(validate_instance(extra, schema), name)


if __name__ == "__main__":
    unittest.main()
