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


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validator_result(name: str = "visible", status: str = "pass") -> dict:
    return {"name": name, "status": status, "detail": None}


def anchor_fixture() -> dict:
    return {
        "parent_anchor_sha256": None,
        "task_id": "derived_ledger_rollup_v2",
        "trial_id": "replicate_001",
        "objective": "implement the stage",
        "invariants": ["stages remain dependent"],
        "decisions": [{"decision": "stage first", "evidence_refs": ["state"]}],
        "accepted_state": {"state_sha256": "a" * 64, "files": [], "status_paths": []},
        "work_graph": [{"node_id": "stage", "objective": "stage", "depends_on": []}],
        "open_risks": [],
        "remaining_budget": {"planner_calls": 2, "spark_calls": 2},
        "stop_condition": "stop after validation",
    }


def crate_fixture() -> dict:
    return {
        "crate_id": "crate-1", "task_id": "derived_ledger_rollup_v2", "trial_id": "replicate_001",
        "parent_state_sha256": "a" * 64, "anchor_sha256": None, "objective": "implement the stage",
        "allowed_paths": ["src/ledger_stage.py"], "forbidden_paths": ["task/private"],
        "dependencies": [], "visible_context_refs": ["state"], "validator_ids": ["stage"],
        "command_budget": 4, "wall_time_seconds": 120, "required_receipt_schema_sha256": "b" * 64,
        "stop_condition": "stop after validation",
    }


def fixture(name: str) -> dict:
    if name == "full_agent.schema.json":
        return {
            "status": "completed", "summary": "done", "files_inspected": [], "files_changed": [],
            "commands": [], "visible_validators": [validator_result()], "unresolved_blockers": [],
            "final_state_claim": "complete",
        }
    if name == "planner.schema.json":
        return {
            "action": "spawn", "anchor_patch": anchor_fixture(),
            "work_graph": [{"node_id": "stage", "objective": "stage", "depends_on": []}],
            "crate": crate_fixture(), "decision_record": [{"decision": "stage first", "evidence_refs": ["state"]}],
            "remaining_budget": {"planner_calls": 2, "spark_calls": 2}, "stop_reason": None,
        }
    return {
        "status": "completed", "crate_id": "crate-1", "parent_state_sha256": "a" * 64,
        "files_inspected": [], "files_changed": [], "commands": [], "visible_validators": [validator_result()],
        "evidence": [], "unresolved_blockers": [], "patch_sha256": None,
        "resulting_state_sha256": "b" * 64, "summary": "done",
    }


class LunaSchemaTests(unittest.TestCase):
    def assert_invalid(self, schema: dict, path: str | None = None) -> None:
        errors = validate_schema(schema)
        self.assertTrue(errors)
        if path:
            self.assertTrue(any(error["path"] == path for error in errors), errors)

    def test_exact_defective_pre_repair_schema_and_nested_detail_diagnostic(self) -> None:
        schema = load("full_agent.schema.json")
        defective = copy.deepcopy(schema)
        defective["properties"]["visible_validators"]["items"]["properties"]["detail"] = {"type": "string"}
        defective["properties"]["visible_validators"]["items"]["required"].remove("detail")
        errors = validate_schema(defective)
        self.assertTrue(any(error["path"] == "/properties/visible_validators/items/required" for error in errors), errors)
        self.assertTrue(any("required names must equal property names" in error["message"] for error in errors), errors)

    def test_root_and_nested_required_must_match_properties(self) -> None:
        root = load("full_agent.schema.json")
        root["required"].pop()
        self.assert_invalid(root, "/required")
        nested = load("full_agent.schema.json")
        nested["properties"]["visible_validators"]["items"]["required"].pop()
        self.assert_invalid(nested, "/properties/visible_validators/items/required")

    def test_additional_properties_false_is_required_at_every_object_depth(self) -> None:
        schema = load("full_agent.schema.json")
        schema["properties"]["visible_validators"]["items"]["additionalProperties"] = True
        self.assert_invalid(schema, "/properties/visible_validators/items/additionalProperties")

    def test_nullable_optional_field_is_required_and_accepted(self) -> None:
        schema = load("full_agent.schema.json")
        self.assertFalse(validate_schema(schema), validate_schema(schema))
        self.assertFalse(validate_instance(fixture("full_agent.schema.json"), schema), validate_instance(fixture("full_agent.schema.json"), schema))

    def test_root_anyof_is_rejected(self) -> None:
        self.assert_invalid({"anyOf": [{"type": "object", "properties": {}, "required": [], "additionalProperties": False}]}, "/anyOf")

    def test_valid_nested_anyof_branches_are_accepted(self) -> None:
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {"choice": {"anyOf": [
                {"type": "object", "additionalProperties": False, "properties": {"value": {"type": "string"}}, "required": ["value"]},
                {"type": "null"},
            ]}},
            "required": ["choice"],
        }
        self.assertFalse(validate_schema(schema), validate_schema(schema))

    def test_unsupported_composition_keywords_are_rejected(self) -> None:
        for keyword in ("allOf", "oneOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else", "patternProperties", "unevaluatedProperties", "contains", "prefixItems", "default"):
            schema = {"type": "object", "additionalProperties": False, "properties": {}, "required": [], keyword: {}}
            self.assert_invalid(schema, f"/{keyword}")

    def test_each_production_schema_and_fixture(self) -> None:
        for name in ("full_agent.schema.json", "planner.schema.json", "spark.schema.json"):
            schema = load(name)
            self.assertFalse(validate_schema(schema), name)
            value = fixture(name)
            self.assertFalse(validate_instance(value, schema), name)
            missing = copy.deepcopy(value)
            missing.pop(next(iter(schema["required"])))
            self.assertTrue(validate_instance(missing, schema), name)
            extra = copy.deepcopy(value)
            extra["unexpected"] = True
            self.assertTrue(validate_instance(extra, schema), name)


if __name__ == "__main__":
    unittest.main()
