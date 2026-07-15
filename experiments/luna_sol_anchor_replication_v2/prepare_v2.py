#!/usr/bin/env python3
"""Build and self-test the frozen Luna/Sol anchor-replication episode."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK = ROOT / "task"
VISIBLE = TASK / "subject_bundle"
PRIVATE = TASK / "private"
PROMPTS = ROOT / "prompts"
SCHEMAS = PROMPTS / "schemas"
PROMPT_SOURCE = Path(r"C:\Users\BAM-Desktop\Downloads\LUNA_SOL_ANCHOR_REPLICATION_V2_PROMPT.txt")

REFERENCE_STAGE = '''from __future__ import annotations
import json
import sys
from pathlib import Path

ALLOWED_STATUS = {"open", "settled"}
KINDS = {"invoice", "credit", "fee", "waiver"}

def normalize(raw: dict) -> dict:
    records = []
    for index, item in enumerate(raw["records"]):
        amount = int(item["amount_cents"])
        kind = item["kind"]
        status = item["status"]
        period = int(item["period"])
        priority = int(item.get("priority", 0))
        if amount < 0 or kind not in KINDS:
            raise ValueError("invalid ledger record")
        records.append({
            "id": str(item["id"]), "account": str(item["account"]),
            "period": period, "kind": kind, "amount_cents": amount,
            "status": status, "priority": priority,
            "eligible": status in ALLOWED_STATUS and period <= int(raw["cutoff_period"]),
            "fee_relief_eligible": kind == "waiver" and priority >= 2,
            "source_index": index,
        })
    return {"schema": 1, "cutoff_period": int(raw["cutoff_period"]), "records": records}

def main() -> int:
    source, destination = map(Path, sys.argv[1:3])
    destination.write_text(json.dumps(normalize(json.loads(source.read_text())), sort_keys=True) + "\\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

REFERENCE_SOLUTION = '''from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

def rollup(normalized: dict) -> dict:
    grouped = defaultdict(lambda: {"invoice": 0, "credit": 0, "fee": 0, "relief": 0, "count": 0})
    for record in normalized["records"]:
        if not record["eligible"]:
            continue
        bucket = grouped[record["account"]]
        bucket["count"] += 1
        if record["kind"] == "invoice":
            bucket["invoice"] += record["amount_cents"]
        elif record["kind"] == "credit":
            bucket["credit"] -= record["amount_cents"]
        elif record["kind"] == "fee":
            bucket["fee"] += record["amount_cents"]
        elif record["fee_relief_eligible"]:
            bucket["relief"] += record["amount_cents"]
    accounts = []
    for account in sorted(grouped):
        bucket = grouped[account]
        adjusted_fee = max(0, bucket["fee"] - bucket["relief"])
        accounts.append({
            "account": account,
            "invoice_cents": bucket["invoice"],
            "credit_cents": bucket["credit"],
            "fee_cents": bucket["fee"],
            "relief_cents": bucket["relief"],
            "adjusted_fee_cents": adjusted_fee,
            "due_cents": bucket["invoice"] + bucket["credit"] + adjusted_fee,
            "record_count": bucket["count"],
        })
    return {"accounts": accounts, "grand_total_cents": sum(a["due_cents"] for a in accounts)}

def main() -> int:
    normalized = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(rollup(normalized), sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

ALT_STAGE = '''import json, sys
from pathlib import Path

def main():
    src, dst = (Path(x) for x in sys.argv[1:3])
    data = json.loads(src.read_text())
    out = {"schema": 1, "cutoff_period": int(data["cutoff_period"]), "records": []}
    for n, row in enumerate(data["records"]):
        kind = row["kind"]; status = row["status"]; period = int(row["period"])
        if int(row["amount_cents"]) < 0 or kind not in {"invoice", "credit", "fee", "waiver"}:
            raise ValueError("invalid ledger record")
        out["records"].append({"id": str(row["id"]), "account": str(row["account"]),
            "period": period, "kind": kind, "amount_cents": int(row["amount_cents"]),
            "status": status, "priority": int(row.get("priority", 0)),
            "eligible": status in {"open", "settled"} and period <= out["cutoff_period"],
            "fee_relief_eligible": kind == "waiver" and int(row.get("priority", 0)) >= 2,
            "source_index": n})
    dst.write_text(json.dumps(out, separators=(",", ":")) + "\\n")
if __name__ == "__main__": main()
'''

ALT_SOLUTION = '''import json, sys
from pathlib import Path

def main():
    rows = json.loads(Path(sys.argv[1]).read_text())["records"]
    state = {}
    for row in rows:
        if not row["eligible"]: continue
        acc = state.setdefault(row["account"], [0, 0, 0, 0, 0])
        acc[4] += 1
        if row["kind"] == "invoice": acc[0] += row["amount_cents"]
        elif row["kind"] == "credit": acc[1] -= row["amount_cents"]
        elif row["kind"] == "fee": acc[2] += row["amount_cents"]
        elif row["fee_relief_eligible"]: acc[3] += row["amount_cents"]
    accounts = []
    for name, (inv, cred, fee, relief, count) in sorted(state.items()):
        adjusted = max(0, fee - relief)
        accounts.append({"account": name, "invoice_cents": inv, "credit_cents": cred,
            "fee_cents": fee, "relief_cents": relief, "adjusted_fee_cents": adjusted,
            "due_cents": inv + cred + adjusted, "record_count": count})
    print(json.dumps({"accounts": accounts,
        "grand_total_cents": sum(item["due_cents"] for item in accounts)}, separators=(",", ":")))
if __name__ == "__main__": main()
'''

CASES = [
    {"cutoff_period": 202601, "records": [
        {"id": "a1", "account": "alpha", "period": 202601, "kind": "invoice", "amount_cents": 10000, "status": "open", "priority": 0},
        {"id": "a2", "account": "alpha", "period": 202601, "kind": "fee", "amount_cents": 1500, "status": "settled", "priority": 0},
        {"id": "a3", "account": "alpha", "period": 202601, "kind": "waiver", "amount_cents": 4000, "status": "settled", "priority": 2},
        {"id": "a4", "account": "alpha", "period": 202602, "kind": "credit", "amount_cents": 500, "status": "open", "priority": 0},
        {"id": "a5", "account": "alpha", "period": 202601, "kind": "invoice", "amount_cents": 999, "status": "void", "priority": 0},
        {"id": "b1", "account": "beta", "period": 202601, "kind": "invoice", "amount_cents": 3000, "status": "settled", "priority": 0},
        {"id": "b2", "account": "beta", "period": 202601, "kind": "credit", "amount_cents": 700, "status": "settled", "priority": 0},
    ]},
    {"cutoff_period": 202602, "records": [
        {"id": "c1", "account": "north", "period": 202602, "kind": "invoice", "amount_cents": 7000, "status": "open", "priority": 0},
        {"id": "c2", "account": "north", "period": 202601, "kind": "fee", "amount_cents": 500, "status": "open", "priority": 0},
        {"id": "c3", "account": "north", "period": 202602, "kind": "waiver", "amount_cents": 1000, "status": "settled", "priority": 1},
        {"id": "c4", "account": "south", "period": 202603, "kind": "invoice", "amount_cents": 8000, "status": "open", "priority": 0},
        {"id": "c5", "account": "south", "period": 202602, "kind": "fee", "amount_cents": 2000, "status": "settled", "priority": 0},
        {"id": "c6", "account": "south", "period": 202602, "kind": "waiver", "amount_cents": 2500, "status": "settled", "priority": 2},
    ]},
    {"cutoff_period": 202603, "records": [
        {"id": "d1", "account": "x", "period": 202603, "kind": "invoice", "amount_cents": 1200, "status": "settled", "priority": 0},
        {"id": "d2", "account": "x", "period": 202603, "kind": "credit", "amount_cents": 2200, "status": "settled", "priority": 0},
        {"id": "d3", "account": "x", "period": 202603, "kind": "fee", "amount_cents": 900, "status": "settled", "priority": 0},
        {"id": "d4", "account": "x", "period": 202603, "kind": "waiver", "amount_cents": 400, "status": "settled", "priority": 2},
        {"id": "d5", "account": "y", "period": 202602, "kind": "invoice", "amount_cents": 4500, "status": "draft", "priority": 0},
        {"id": "d6", "account": "y", "period": 202603, "kind": "fee", "amount_cents": 600, "status": "open", "priority": 0},
    ]},
    {"cutoff_period": 202604, "records": [
        {"id": "e1", "account": "one", "period": 202604, "kind": "invoice", "amount_cents": 100, "status": "open", "priority": 0},
        {"id": "e2", "account": "one", "period": 202604, "kind": "fee", "amount_cents": 1000, "status": "open", "priority": 0},
        {"id": "e3", "account": "one", "period": 202604, "kind": "waiver", "amount_cents": 400, "status": "settled", "priority": 2},
        {"id": "e4", "account": "two", "period": 202604, "kind": "invoice", "amount_cents": 900, "status": "open", "priority": 0},
        {"id": "e5", "account": "two", "period": 202604, "kind": "credit", "amount_cents": 100, "status": "open", "priority": 0},
    ]},
    {"cutoff_period": 202605, "records": [
        {"id": "f1", "account": "red", "period": 202605, "kind": "invoice", "amount_cents": 10000, "status": "settled", "priority": 0},
        {"id": "f2", "account": "red", "period": 202605, "kind": "credit", "amount_cents": 1000, "status": "settled", "priority": 0},
        {"id": "f3", "account": "red", "period": 202605, "kind": "fee", "amount_cents": 100, "status": "settled", "priority": 0},
        {"id": "f4", "account": "red", "period": 202605, "kind": "waiver", "amount_cents": 50, "status": "settled", "priority": 2},
        {"id": "f5", "account": "blue", "period": 202605, "kind": "invoice", "amount_cents": 2500, "status": "open", "priority": 0},
        {"id": "f6", "account": "blue", "period": 202605, "kind": "fee", "amount_cents": 250, "status": "void", "priority": 0},
    ]},
    {"cutoff_period": 202606, "records": [
        {"id": "g1", "account": "late", "period": 202606, "kind": "invoice", "amount_cents": 6000, "status": "open", "priority": 0},
        {"id": "g2", "account": "late", "period": 202607, "kind": "invoice", "amount_cents": 7000, "status": "open", "priority": 0},
        {"id": "g3", "account": "late", "period": 202606, "kind": "fee", "amount_cents": 800, "status": "settled", "priority": 0},
        {"id": "g4", "account": "late", "period": 202606, "kind": "waiver", "amount_cents": 900, "status": "settled", "priority": 2},
        {"id": "g5", "account": "early", "period": 202605, "kind": "invoice", "amount_cents": 3200, "status": "settled", "priority": 0},
        {"id": "g6", "account": "early", "period": 202605, "kind": "credit", "amount_cents": 300, "status": "settled", "priority": 0},
    ]},
]

VISIBLE_SAMPLE = CASES[0]

TASK_TEXT = """# Derived ledger rollup\n\nImplement the two-stage ledger pipeline in this repository.\n\nThe input JSON has an integer `cutoff_period` and `records`. Each record has `id`, `account`, `period`, `kind`, `amount_cents`, `status`, and optional integer `priority`. Amounts are non-negative integers. Kinds are `invoice`, `credit`, `fee`, and `waiver`.\n\nFirst, implement `src/ledger_stage.py`. It must read an input ledger and write a normalized JSON state to the output path. Preserve source order. Each normalized record must include `id`, `account`, `period`, `kind`, `amount_cents`, `status`, `priority`, `eligible`, `fee_relief_eligible`, and `source_index`. A record is eligible exactly when its status is `open` or `settled` and its period is less than or equal to the input cutoff. Fee relief is eligible exactly for a `waiver` with priority at least 2. The stage output must contain `schema: 1`, the cutoff, and the normalized records.\n\nSecond, implement `src/solution.py`. It must read only the normalized state path supplied on its command line and print one compact JSON object. For eligible records, group by account: invoices add to invoice cents, credits subtract from credit cents, fees add to fee cents, and eligible waivers add to relief cents. Adjusted fees are `max(0, fee_cents - relief_cents)`. Due is invoice plus credit plus adjusted fees. Include one sorted account object per account with the fields `account`, `invoice_cents`, `credit_cents`, `fee_cents`, `relief_cents`, `adjusted_fee_cents`, `due_cents`, and `record_count`, plus `grand_total_cents`.\n\nThe visible validator is `python run_visible.py`. Keep the two stages dependent: the final solution must fail when the normalized state file is absent. You may edit only `src/ledger_stage.py` and `src/solution.py`; generated normalized JSON is a runtime artifact. Do not edit the task, validator, or sample data.\n"""

VISIBLE_RUNNER = '''import json, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parent
normalized = root / "data" / "normalized_ledger.json"
subprocess.run([sys.executable, "src/ledger_stage.py", "data/sample_ledger.json", str(normalized)], cwd=root, check=True)
result = subprocess.run([sys.executable, "src/solution.py", str(normalized)], cwd=root, check=True, capture_output=True, text=True)
actual = json.loads(result.stdout)
expected = {"accounts": [
    {"account": "alpha", "invoice_cents": 10000, "credit_cents": 0, "fee_cents": 1500, "relief_cents": 0, "adjusted_fee_cents": 1500, "due_cents": 11500, "record_count": 2},
    {"account": "beta", "invoice_cents": 3000, "credit_cents": -700, "fee_cents": 0, "relief_cents": 0, "adjusted_fee_cents": 0, "due_cents": 2300, "record_count": 2}], "grand_total_cents": 13800}
assert actual == expected, (actual, expected)
print("VISIBLE_OK")
'''

def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())

def write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode() if isinstance(data, str) else data
    path.write_bytes(raw.replace(b"\r\n", b"\n"))

def extract_base(source: bytes, name: str) -> bytes:
    text = source.decode("utf-8").replace("\r\n", "\n")
    m = re.search(rf"{name}_BEGIN\n(.*?){name}_END\n", text, re.S)
    if not m:
        raise RuntimeError(f"missing base prompt {name}")
    return (m.group(1).rstrip("\r\n") + "\n").encode()

def hidden_grader_source() -> str:
    cases = json.dumps(CASES, sort_keys=True, separators=(",", ":"))
    return f'''#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

CASES = {cases}
def expected(raw):
    buckets = {{}}
    for row in raw["records"]:
        if row["status"] not in {{"open", "settled"}} or int(row["period"]) > int(raw["cutoff_period"]):
            continue
        b = buckets.setdefault(row["account"], [0, 0, 0, 0, 0])
        b[4] += 1
        if row["kind"] == "invoice": b[0] += int(row["amount_cents"])
        elif row["kind"] == "credit": b[1] -= int(row["amount_cents"])
        elif row["kind"] == "fee": b[2] += int(row["amount_cents"])
        elif row["kind"] == "waiver" and int(row.get("priority", 0)) >= 2: b[3] += int(row["amount_cents"])
    accounts = []
    for name in sorted(buckets):
        inv, cred, fee, relief, count = buckets[name]
        adjusted = max(0, fee - relief)
        accounts.append({{"account": name, "invoice_cents": inv, "credit_cents": cred,
            "fee_cents": fee, "relief_cents": relief, "adjusted_fee_cents": adjusted,
            "due_cents": inv + cred + adjusted, "record_count": count}})
    return {{"accounts": accounts, "grand_total_cents": sum(x["due_cents"] for x in accounts)}}

def run(candidate, raw, number):
    work = candidate / ("_grade_case_" + str(number))
    work.mkdir()
    ledger = work / "ledger.json"; normalized = work / "normalized.json"
    ledger.write_text(json.dumps(raw) + "\\n")
    stage = subprocess.run([sys.executable, "src/ledger_stage.py", str(ledger), str(normalized)], cwd=candidate, capture_output=True, text=True)
    if stage.returncode != 0 or not normalized.is_file(): return False, "stage:" + stage.stderr[-200:]
    try:
        state = json.loads(normalized.read_text())
        if state.get("cutoff_period") != raw["cutoff_period"] or len(state.get("records", [])) != len(raw["records"]): return False, "state-shape"
    except Exception: return False, "state-json"
    solution = subprocess.run([sys.executable, "src/solution.py", str(normalized)], cwd=candidate, capture_output=True, text=True)
    if solution.returncode != 0: return False, "solution:" + solution.stderr[-200:]
    try: actual = json.loads(solution.stdout)
    except Exception: return False, "output-json"
    return actual == expected(raw), "mismatch" if actual != expected(raw) else "ok"

def main():
    if len(sys.argv) != 2: return 2
    candidate = Path(sys.argv[1]).resolve()
    failures = []
    for i, raw in enumerate(CASES):
        ok, why = run(candidate, raw, i)
        if not ok: failures.append({{"case": i, "reason": why}})
    print(json.dumps({{"cases": len(CASES), "failures": failures, "passed": not failures}}, sort_keys=True))
    return 0 if not failures else 1
if __name__ == "__main__": raise SystemExit(main())
'''

def schema_files() -> dict[str, dict]:
    validator = {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["name", "status", "detail"], "properties": {"name": {"type": "string"},
        "status": {"enum": ["pass", "fail", "not_run"]}, "detail": {"type": ["string", "null"]}}}}
    text_array = {"type": "array", "items": {"type": "string"}}
    state_file = {"type": "object", "additionalProperties": False,
        "required": ["path", "sha256"], "properties": {"path": {"type": "string"}, "sha256": {"type": "string"}}}
    accepted_state = {"type": "object", "additionalProperties": False,
        "required": ["state_sha256", "files", "status_paths"], "properties": {
            "state_sha256": {"type": "string"}, "files": {"type": "array", "items": state_file},
            "status_paths": text_array}}
    budget = {"type": "object", "additionalProperties": False,
        "required": ["planner_calls", "spark_calls"], "properties": {
            "planner_calls": {"type": "integer"}, "spark_calls": {"type": "integer"}}}
    work_node = {"type": "object", "additionalProperties": False,
        "required": ["node_id", "objective", "depends_on"], "properties": {
            "node_id": {"type": "string"}, "objective": {"type": "string"},
            "depends_on": text_array}}
    crate = {"type": "object", "additionalProperties": False, "required": ["crate_id", "task_id", "trial_id", "parent_state_sha256", "anchor_sha256", "objective", "allowed_paths", "forbidden_paths", "dependencies", "visible_context_refs", "validator_ids", "command_budget", "wall_time_seconds", "required_receipt_schema_sha256", "stop_condition"], "properties": {"crate_id": {"type": "string"}, "task_id": {"type": "string"}, "trial_id": {"type": "string"}, "parent_state_sha256": {"type": "string"}, "anchor_sha256": {"type": ["string", "null"]}, "objective": {"type": "string"}, "allowed_paths": text_array, "forbidden_paths": text_array, "dependencies": text_array, "visible_context_refs": text_array, "validator_ids": text_array, "command_budget": {"type": "integer"}, "wall_time_seconds": {"type": "integer"}, "required_receipt_schema_sha256": {"type": "string"}, "stop_condition": {"type": "string"}}}
    anchor = {"type": "object", "additionalProperties": False, "required": ["parent_anchor_sha256", "task_id", "trial_id", "objective", "invariants", "decisions", "accepted_state", "work_graph", "open_risks", "remaining_budget", "stop_condition"], "properties": {"parent_anchor_sha256": {"type": ["string", "null"]}, "task_id": {"type": "string"}, "trial_id": {"type": "string"}, "objective": {"type": "string"}, "invariants": text_array, "decisions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["decision", "evidence_refs"], "properties": {"decision": {"type": "string"}, "evidence_refs": text_array}}}, "accepted_state": accepted_state, "work_graph": {"type": "array", "items": work_node}, "open_risks": text_array, "remaining_budget": budget, "stop_condition": {"type": "string"}}}
    return {
        "full_agent.schema.json": {"type": "object", "additionalProperties": False, "required": ["status", "summary", "files_inspected", "files_changed", "commands", "visible_validators", "unresolved_blockers", "final_state_claim"], "properties": {"status": {"enum": ["completed", "blocked", "failed"]}, "summary": {"type": "string"}, "files_inspected": text_array, "files_changed": text_array, "commands": text_array, "visible_validators": validator, "unresolved_blockers": text_array, "final_state_claim": {"type": "string"}}},
        "planner.schema.json": {"type": "object", "additionalProperties": False, "required": ["action", "anchor_patch", "work_graph", "crate", "decision_record", "remaining_budget", "stop_reason"], "properties": {"action": {"enum": ["spawn", "finish", "fail"]}, "anchor_patch": {"anyOf": [{"type": "null"}, anchor]}, "work_graph": {"type": "array", "items": work_node}, "crate": {"anyOf": [{"type": "null"}, crate]}, "decision_record": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["decision", "evidence_refs"], "properties": {"decision": {"type": "string"}, "evidence_refs": text_array}}}, "remaining_budget": budget, "stop_reason": {"type": ["string", "null"]}}},
        "spark.schema.json": {"type": "object", "additionalProperties": False, "required": ["status", "crate_id", "parent_state_sha256", "files_inspected", "files_changed", "commands", "visible_validators", "evidence", "unresolved_blockers", "patch_sha256", "resulting_state_sha256", "summary"], "properties": {"status": {"enum": ["completed", "blocked", "failed"]}, "crate_id": {"type": "string"}, "parent_state_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "files_inspected": text_array, "files_changed": text_array, "commands": text_array, "visible_validators": validator, "evidence": text_array, "unresolved_blockers": text_array, "patch_sha256": {"type": ["string", "null"]}, "resulting_state_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "summary": {"type": "string"}}},
    }

def build() -> dict:
    if not PROMPT_SOURCE.is_file():
        raise FileNotFoundError(PROMPT_SOURCE)
    source = PROMPT_SOURCE.read_bytes()
    for path in (VISIBLE, PRIVATE, PROMPTS):
        path.mkdir(parents=True, exist_ok=True)
    write(VISIBLE / "TASK.md", TASK_TEXT)
    write(VISIBLE / "run_visible.py", VISIBLE_RUNNER)
    write(VISIBLE / "src/__init__.py", "")
    write(VISIBLE / "src/ledger_stage.py", "raise SystemExit('HAND 1 not implemented')\n")
    write(VISIBLE / "src/solution.py", "raise SystemExit('HAND 2 not implemented')\n")
    write(VISIBLE / "data/sample_ledger.json", canon(VISIBLE_SAMPLE))
    write(PRIVATE / "reference_stage.py", REFERENCE_STAGE)
    write(PRIVATE / "reference_solution.py", REFERENCE_SOLUTION)
    write(PRIVATE / "hidden_grader.py", hidden_grader_source())
    write(PRIVATE / "cases.json", canon(CASES))
    base_names = {"full_agent": "FULL_AGENT_BASE_PROMPT", "planner": "PLANNER_BASE_PROMPT", "spark": "SPARK_HAND_BASE_PROMPT"}
    for filename, marker in base_names.items():
        write(PROMPTS / f"{filename}_base.txt", extract_base(source, marker))
    for filename, schema in schema_files().items():
        write(SCHEMAS / filename, canon(schema))
    task_packet = {"schema": "luna-sol-anchor-replication/task-packet@2", "task_id": "derived_ledger_rollup_v2", "task_text": TASK_TEXT, "visible_bundle_files": sorted(p.relative_to(VISIBLE).as_posix() for p in VISIBLE.rglob("*") if p.is_file()), "allowed_files": ["src/ledger_stage.py", "src/solution.py"], "visible_validator": [sys.executable, "run_visible.py"], "stage_command": [sys.executable, "src/ledger_stage.py", "<input>", "<normalized>"], "solution_command": [sys.executable, "src/solution.py", "<normalized>"], "output_contract": {"stage": "normalized state JSON", "solution": "rollup JSON"}}
    write(TASK / "task_packet.json", canon(task_packet))
    hidden_manifest = {"schema": "luna-sol-anchor-replication/hidden-fixtures@1", "task_id": "derived_ledger_rollup_v2", "case_count": len(CASES), "hidden_grader": {"path": "task/private/hidden_grader.py", "sha256": sha(PRIVATE / "hidden_grader.py")}, "cases_sha256": sha(PRIVATE / "cases.json")}
    write(TASK / "hidden_fixture_manifest.json", canon(hidden_manifest))
    prereg = {"schema": "luna-sol-anchor-replication/preregistration@2", "task_id": "derived_ledger_rollup_v2", "suite_version": "v2", "k": 3, "arms": ["SOL_FULL", "LUNA_FULL", "LUNA_SPARK_CORRECT_ANCHOR", "LUNA_SPARK_NO_ANCHOR"], "models": {"SOL_FULL": ["gpt-5.6-sol", "high"], "LUNA_FULL": ["gpt-5.6-luna", "high"], "LUNA_PLANNER": ["gpt-5.6-luna", "high"], "SPARK": ["gpt-5.3-codex-spark", "low"]}, "task_commit_required": True, "hidden_grade_after_all_calls": True, "no_retries": True, "comparison_rules": {"sol_replication": "SOL_FULL and LUNA_SPARK_CORRECT_ANCHOR both pass 3/3", "anchor_signal": "correct-anchor passes more paired replicates and at least two of three favor it"}, "stopping_rules": {"before_first_call": ["missing CLI", "missing model slug", "oracle self-test failure", "leak scan failure", "isolation failure", "freeze hash failure"], "after_first_call": "continue unless account, CLI, custody, or packet validity blocks continuation"}}
    write(TASK / "preregistration.json", canon(prereg))
    return {"task_packet_sha256": sha(TASK / "task_packet.json"), "hidden_grader_sha256": sha(PRIVATE / "hidden_grader.py"), "visible_bundle_sha256": sha_bytes(canon({p.relative_to(VISIBLE).as_posix(): sha(p) for p in sorted(VISIBLE.rglob("*")) if p.is_file()}))}

def run_hidden(candidate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(PRIVATE / "hidden_grader.py"), str(candidate)], capture_output=True, text=True, cwd=ROOT)

def copy_base(destination: Path, stage: str, solution: str) -> None:
    shutil.copytree(VISIBLE, destination)
    write(destination / "src/ledger_stage.py", stage)
    write(destination / "src/solution.py", solution)

def self_test() -> dict:
    if any(p.name in {"hidden_grader.py", "cases.json"} for p in VISIBLE.rglob("*")):
        raise AssertionError("private grading files entered subject bundle")
    forbidden = ["reference_stage", "reference_solution", "hidden_grader.py", "controlling_solution", "golden implementation", "expected hidden"]
    visible_bytes = b"\n".join(p.read_bytes() for p in VISIBLE.rglob("*") if p.is_file()).lower()
    for token in forbidden:
        if token.encode() in visible_bytes:
            raise AssertionError(f"subject leak: {token}")
    with tempfile.TemporaryDirectory(prefix="luna-v2-selftest-") as temp:
        root = Path(temp)
        cases = {}
        for label, stage, solution in [("reference", REFERENCE_STAGE, REFERENCE_SOLUTION), ("equivalent", ALT_STAGE, ALT_SOLUTION)]:
            candidate = root / label; copy_base(candidate, stage, solution)
            result = run_hidden(candidate)
            if result.returncode != 0: raise AssertionError(f"{label} did not pass: {result.stdout}{result.stderr}")
            cases[label] = result.stdout.strip()
        mutants = {
            "hardcoded": REFERENCE_SOLUTION.replace("def main() -> int:", "def main() -> int:", 1).replace("normalized = json.loads(Path(sys.argv[1]).read_text())", "normalized = {'records': [], 'cutoff_period': 0}", 1),
            "wrong_precedence": REFERENCE_SOLUTION.replace("bucket[\"invoice\"] + bucket[\"credit\"] + adjusted_fee", "max(0, bucket[\"invoice\"] + bucket[\"credit\"] + bucket[\"fee\"] - bucket[\"relief\"])", 1),
            "wrong_aggregation": REFERENCE_SOLUTION.replace("for account in sorted(grouped):", "for account in sorted(grouped)[:1]:", 1),
            "omitted_record": REFERENCE_SOLUTION.replace("for record in normalized[\"records\"]:", "for record in normalized[\"records\"][1:]:", 1),
            "off_by_one": REFERENCE_STAGE.replace("period <= int(raw[\"cutoff_period\"])", "period < int(raw[\"cutoff_period\"])", 1),
        }
        for name, mutation in mutants.items():
            stage = mutation if name == "off_by_one" else REFERENCE_STAGE
            solution = mutation if name != "off_by_one" else REFERENCE_SOLUTION
            candidate = root / name; copy_base(candidate, stage, solution)
            result = run_hidden(candidate)
            if result.returncode == 0: raise AssertionError(f"mutant passed: {name}")
        missing = root / "missing"; copy_base(missing, REFERENCE_STAGE, REFERENCE_SOLUTION)
        result = subprocess.run([sys.executable, "src/solution.py", "missing.json"], cwd=missing, capture_output=True)
        if result.returncode == 0: raise AssertionError("deleting parser output did not fail")
        probe = root / "probe"; copy_base(probe, REFERENCE_STAGE, REFERENCE_SOLUTION)
        if any(p.name == "hidden_grader.py" for p in probe.rglob("*")): raise AssertionError("grader copied into candidate")
        if run_hidden(probe).returncode != 0: raise AssertionError("external grader could not grade sealed candidate")
    return {"reference": "pass", "equivalent": "pass", "mutants": "all_fail", "dependency": "pass", "leak_scan": "pass", "external_grader": "pass"}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    build_result = build()
    test_result = self_test() if args.self_test else {"status": "not_run"}
    receipt = {"schema": "luna-sol-anchor-replication/oracle-self-test@2", "build": build_result, "tests": test_result}
    write(TASK / "oracle_self_test.json", canon(receipt))
    print(json.dumps(receipt, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
