#!/usr/bin/env python3
"""Deterministic v2.2.2 task/visible/oracle consistency gate."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TASK = ROOT / "task"
VISIBLE = TASK / "subject_bundle"
PRIVATE = TASK / "private"
PREPARE = ROOT / "prepare_v2.py"
OLD_ORACLE = TASK / "oracle_self_test.json"

NO_RELIEF_STAGE = '''
import json, sys
raw=json.load(open(sys.argv[1])); out=[]
for i,r in enumerate(raw["records"]):
    p=int(r.get("priority",0)); out.append({"id":str(r["id"]),"account":str(r["account"]),"period":int(r["period"]),"kind":r["kind"],"amount_cents":int(r["amount_cents"]),"status":r["status"],"priority":p,"eligible":r["kind"] != "waiver" and r["status"] in {"open","settled"} and int(r["period"]) <= int(raw["cutoff_period"]),"fee_relief_eligible":False,"source_index":i})
json.dump({"schema":1,"cutoff_period":int(raw["cutoff_period"]),"records":out},open(sys.argv[2],"w"),sort_keys=True)
'''


def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def load_prepare() -> Any:
    spec = importlib.util.spec_from_file_location("luna_prepare_v222", PREPARE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def visible_bundle_sha256() -> str:
    files = {
        path.relative_to(VISIBLE).as_posix(): sha(path)
        for path in sorted(VISIBLE.rglob("*"))
        if path.is_file() and path.name != "normalized_ledger.json"
    }
    return sha_bytes(canon(files))


def candidate(destination: Path, stage: str, solution: str) -> None:
    shutil.copytree(
        VISIBLE,
        destination,
        ignore=shutil.ignore_patterns("normalized_ledger.json", "__pycache__"),
    )
    (destination / "src" / "ledger_stage.py").write_text(stage, encoding="utf-8", newline="\n")
    (destination / "src" / "solution.py").write_text(solution, encoding="utf-8", newline="\n")


def run_visible(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "run_visible.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )


def run_hidden(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PRIVATE / "hidden_grader.py"), str(root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def evaluate() -> dict[str, Any]:
    prepare = load_prepare()
    reference_stage = (PRIVATE / "reference_stage.py").read_text(encoding="utf-8")
    reference_solution = (PRIVATE / "reference_solution.py").read_text(encoding="utf-8")
    tests: list[dict[str, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        tests.append({"name": name, "result": "PASS" if passed else "FAIL", "detail": detail})

    with tempfile.TemporaryDirectory(prefix="luna-v222-consistency-") as temp:
        base = Path(temp)
        for label, stage, solution in (
            ("reference", reference_stage, reference_solution),
            ("equivalent", prepare.ALT_STAGE, prepare.ALT_SOLUTION),
        ):
            visible_candidate = base / f"{label}-visible"
            candidate(visible_candidate, stage, solution)
            visible_result = run_visible(visible_candidate)
            check(
                f"{label}_passes_visible",
                visible_result.returncode == 0 and visible_result.stdout.strip() == "VISIBLE_OK",
                (visible_result.stdout + visible_result.stderr)[-500:],
            )
            hidden_candidate = base / f"{label}-hidden"
            candidate(hidden_candidate, stage, solution)
            hidden_result = run_hidden(hidden_candidate)
            check(
                f"{label}_passes_hidden",
                hidden_result.returncode == 0,
                (hidden_result.stdout + hidden_result.stderr)[-500:],
            )

        mutant_visible = base / "old-no-relief-visible"
        candidate(mutant_visible, NO_RELIEF_STAGE, reference_solution)
        mutant_visible_result = run_visible(mutant_visible)
        check("old_no_relief_fails_visible", mutant_visible_result.returncode != 0)

        mutant_hidden = base / "old-no-relief-hidden"
        candidate(mutant_hidden, NO_RELIEF_STAGE, reference_solution)
        mutant_hidden_result = run_hidden(mutant_hidden)
        check("old_no_relief_fails_hidden", mutant_hidden_result.returncode != 0)

        missing = base / "dependency"
        candidate(missing, reference_stage, reference_solution)
        dependency_result = subprocess.run(
            [sys.executable, "src/solution.py", "missing.json"],
            cwd=missing,
            capture_output=True,
            text=True,
        )
        check("normalized_state_dependency", dependency_result.returncode != 0)

    stage_module = load_module("luna_reference_stage_v222", PRIVATE / "reference_stage.py")
    solution_module = load_module("luna_reference_solution_v222", PRIVATE / "reference_solution.py")
    witness = {
        "cutoff_period": 1,
        "records": [
            {"id": "fee", "account": "a", "period": 1, "kind": "fee", "amount_cents": 1500, "status": "settled", "priority": 0},
            {"id": "waiver", "account": "a", "period": 1, "kind": "waiver", "amount_cents": 4000, "status": "settled", "priority": 2},
        ],
    }
    witness_result = solution_module.rollup(stage_module.normalize(witness))
    check(
        "minimal_fee_waiver_witness",
        witness_result == {
            "accounts": [{
                "account": "a", "invoice_cents": 0, "credit_cents": 0,
                "fee_cents": 1500, "relief_cents": 4000,
                "adjusted_fee_cents": 0, "due_cents": 0, "record_count": 2,
            }],
            "grand_total_cents": 0,
        },
        json.dumps(witness_result, sort_keys=True),
    )

    forbidden = ["reference_stage", "reference_solution", "hidden_grader.py", "controlling_solution", "golden implementation", "expected hidden"]
    visible_bytes = b"\n".join(
        path.read_bytes().lower()
        for path in VISIBLE.rglob("*")
        if path.is_file() and path.name != "normalized_ledger.json"
    )
    leaks = [token for token in forbidden if token.encode() in visible_bytes]
    check("visible_bundle_leak_scan", not leaks, ",".join(leaks))

    prior = json.loads(OLD_ORACLE.read_text(encoding="utf-8"))
    task_packet_sha = sha(TASK / "task_packet.json")
    hidden_grader_sha = sha(PRIVATE / "hidden_grader.py")
    check("task_packet_unchanged", task_packet_sha == prior["build"]["task_packet_sha256"])
    check("hidden_grader_unchanged", hidden_grader_sha == prior["build"]["hidden_grader_sha256"])

    receipt = {
        "schema": "luna-sol-anchor-replication/task-visible-consistency@2.2.2",
        "protocol_revision": "2.2.2",
        "build": {
            "task_packet_sha256": task_packet_sha,
            "hidden_grader_sha256": hidden_grader_sha,
            "visible_bundle_sha256": visible_bundle_sha256(),
            "prior_visible_bundle_sha256": prior["build"]["visible_bundle_sha256"],
        },
        "tests": tests,
        "all_pass": all(item["result"] == "PASS" for item in tests),
    }
    return receipt


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: task_visible_consistency_gate.py OUTPUT_JSON")
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite: {output}")
    receipt = evaluate()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canon(receipt))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
