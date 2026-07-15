import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "experiments" / "luna_sol_anchor_replication_v2" / "run_v2.py"
spec = importlib.util.spec_from_file_location("luna_run_v221_error_test", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_exact_preserved_canary_two_provider_error_is_typed_before_missing_final() -> None:
    events = ROOT / "experiments" / "luna_sol_anchor_replication_v2" / "canaries" / "canary_2_initial_planner" / "call" / "events.jsonl"
    error = runner.extract_remote_error(events.read_bytes())
    assert error == {
        "code": "API_INVALID_JSON_SCHEMA",
        "stage": "response_schema_validation",
        "http_status": 400,
        "provider_error_type": "invalid_request_error",
        "provider_error_code": "invalid_json_schema",
        "provider_param": "text.format.schema",
        "message": "Invalid schema for response_format 'codex_output_schema': In context=('properties', 'action'), schema must have a 'type' key.",
        "agent_output_observed": False,
        "event_type": "error",
    }
