#!/usr/bin/env python3
"""Run the OpenAI cross-provider breadth reproduction.

This is intentionally a thin protocol runner, not a grader rewrite:

* The solver prompt contains only the public subject/spec/visible validator.
* Hidden graders are invoked only after a candidate/counterexample is produced.
* Every OpenAI call is appended to ``run/xprovider_ledger.jsonl`` with usage.

Example:

    OPENAI_API_KEY=... python experiments/breadth/xprovider_run.py \
        --model gpt-4.1-mini --k 3
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from capability_harness import review  # noqa: E402
from capability_harness.lenses_contrib import all_lenses  # noqa: E402
from experiments.breadth.ledger import log_call  # noqa: E402

LEDGER = ROOT / "experiments/breadth/run/xprovider_ledger.jsonl"
TASK_ROOT = ROOT / "experiments/tier-uplift"
TASKS = {
    "task01_parse_duration": TASK_ROOT / "task01_parse_duration",
    "task02_wildcard": TASK_ROOT / "task02_wildcard",
    "task06_select": TASK_ROOT / "task06_select",
}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def registry_price(model: str) -> tuple[float, float]:
    data = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
    entry = data["models"][model]
    return float(entry["input_per_1M"]), float(entry["output_per_1M"])


class OpenAICaller:
    def __init__(self, model: str, account: str, price_in: float, price_out: float, max_tokens: int):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OPENAI_API_KEY is required for a real cross-provider run")
        self.key = key
        self.model = model
        self.account = account
        self.price_in = price_in
        self.price_out = price_out
        self.max_tokens = max_tokens
        self.pending: dict[str, Any] = {}

    def call(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = (time.perf_counter() - start) * 1000
        usage = data.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost = (input_tokens * self.price_in + output_tokens * self.price_out) / 1_000_000
        self.pending = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
            "latency_ms": round(elapsed, 3),
        }
        return data["choices"][0]["message"].get("content") or ""


def read_public_packet(task_id: str) -> str:
    d = TASKS[task_id]
    parts = [f"# {task_id}", (d / "spec.md").read_text(encoding="utf-8")]
    subject = d / "subject.py"
    if subject.exists():
        parts.append("## subject.py\n```python\n" + subject.read_text(encoding="utf-8") + "\n```")
    visible = d / "visible_tests.py"
    if visible.exists():
        parts.append("## visible_tests.py\n```python\n" + visible.read_text(encoding="utf-8") + "\n```")
    else:
        parts.append("## visible_tests.py\nNo visible validator is provided for this task.")
    return "\n\n".join(parts)


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


def grade_code(task_id: str, code: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        cand = Path(td) / "candidate.py"
        cand.write_text(code, encoding="utf-8")
        grader = "hidden_tests.py" if task_id == "task01_parse_duration" else "hidden_oracle.py"
        p = subprocess.run(
            [sys.executable, str(TASKS[task_id] / grader), str(cand)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
    out = p.stdout
    m = re.search(r"SCORE\s+(\d+)/(\d+)", out)
    return bool(m and m.group(1) == m.group(2)), out


def extract_counterexample(text: str) -> tuple[list[tuple[int, int]], int]:
    m = re.search(r"items\s*=\s*(\[.*?\])\s*;?\s*k\s*=\s*(-?\d+)", text, re.S)
    if not m:
        raise ValueError("response did not contain `items=[...]; k=...`")
    items = ast.literal_eval(m.group(1))
    k = int(m.group(2))
    return items, k


def grade_counterexample(text: str) -> tuple[bool, str]:
    try:
        items, k = extract_counterexample(text)
    except Exception as e:
        return False, f"EXTRACT ERROR: {e}\n{text}"
    check = f"items={items!r}; k={k!r}"
    p = subprocess.run(
        [sys.executable, str(TASKS["task06_select"] / "grader.py"), "--check", check],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    return "COUNTEREXAMPLE: True" in p.stdout, p.stdout


def solver_prompt(task_id: str, packet: str) -> str:
    if task_id == "task06_select":
        return packet + "\n\nReturn exactly one counterexample as: items=[...]; k=...\n"
    return packet + "\n\nReturn only the Python function implementation. No prose, no markdown.\n"


def synth_prompt(task_id: str, packet: str, lens_text: str) -> str:
    if task_id == "task06_select":
        return (
            packet
            + "\n\nHarness lens findings:\n"
            + lens_text
            + "\n\nUsing the findings, return exactly one counterexample as: items=[...]; k=...\n"
        )
    return (
        packet
        + "\n\nHarness lens findings:\n"
        + lens_text
        + "\n\nUsing the findings, return only the corrected Python function implementation.\n"
    )


def log_after_call(caller: OpenAICaller, *, task_id: str, phase: str, trial: int,
                   outcome: str, note: str = "") -> None:
    log_call(
        LEDGER,
        ts=stamp(),
        account=caller.account,
        model=caller.model,
        tier="cheap",
        task_id=task_id,
        phase=phase,
        outcome=outcome,
        effort="",
        trial=trial,
        note=note,
        **caller.pending,
        evidence_class="single-source, cross-provider",
    )


def run_trial(caller: OpenAICaller, task_id: str, phase: str, trial: int) -> tuple[bool, str]:
    packet = read_public_packet(task_id)
    if phase == "solo":
        response = caller.call(solver_prompt(task_id, packet))
        if task_id == "task06_select":
            passed, report = grade_counterexample(response)
        else:
            passed, report = grade_code(task_id, extract_code(response))
        log_after_call(caller, task_id=task_id, phase=phase, trial=trial,
                       outcome="pass" if passed else "fail", note=report[:1000])
        return passed, report

    lens_calls: list[dict[str, str]] = []

    def lens_call(prompt: str) -> str:
        text = caller.call(prompt)
        lens_calls.append({"usage": dict(caller.pending), "text": text})
        return text

    result = review(packet, lens_call, lenses=all_lenses())
    for i, call in enumerate(lens_calls, start=1):
        caller.pending = call["usage"]
        log_after_call(caller, task_id=task_id, phase=f"harness_lens_{i}", trial=trial,
                       outcome="partial", note="")
    response = caller.call(synth_prompt(task_id, packet, result.merged_text()))
    if task_id == "task06_select":
        passed, report = grade_counterexample(response)
    else:
        passed, report = grade_code(task_id, extract_code(response))
    log_after_call(caller, task_id=task_id, phase="harness", trial=trial,
                   outcome="pass" if passed else "fail", note=report[:1000])
    return passed, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4.1-mini")
    ap.add_argument("--account", default="codex-openai")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=2500)
    args = ap.parse_args()
    price_in, price_out = registry_price(args.model)
    caller = OpenAICaller(args.model, args.account, price_in, price_out, args.max_tokens)
    for task_id in TASKS:
        for phase in ("solo", "harness"):
            for trial in range(1, args.k + 1):
                passed, report = run_trial(caller, task_id, phase, trial)
                print(f"{task_id} {phase} trial={trial}: {'PASS' if passed else 'FAIL'}")
                print(report.splitlines()[0] if report else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
