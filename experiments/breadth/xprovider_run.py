#!/usr/bin/env python3
"""Run the OpenAI cross-provider breadth reproduction.

This is intentionally a thin protocol runner, not a grader rewrite:

* Solver prompts contain only public task material.
* Hidden graders run only after a candidate/counterexample is produced.
* Provider generation rows are logged before hidden grading starts.
* Hidden grade rows are separate zero-token/cost rows tied to generation rows.

Example:

    OPENAI_API_KEY=... python experiments/breadth/xprovider_run.py \
        --model gpt-4.1-mini --k 3
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
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
CACHED_PRICE_KEYS = ("cached_input_per_1M", "cache_read_per_1M", "input_cached_per_1M")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_attempt_id(task_id: str, phase: str, trial: int) -> str:
    return f"{task_id}:{phase}:{trial}:{uuid.uuid4().hex[:12]}"


def model_registry_entry(model: str) -> dict[str, Any]:
    data = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
    return data["models"][model]


class OpenAICaller:
    def __init__(self, model: str, account: str, registry_entry: dict[str, Any], max_tokens: int):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OPENAI_API_KEY is required for a real cross-provider run")
        self.key = key
        self.model = model
        self.account = account
        self.price_in = float(registry_entry["input_per_1M"])
        self.price_out = float(registry_entry["output_per_1M"])
        self.cached_price_in = self._cached_price(registry_entry)
        self.max_tokens = max_tokens
        self.pending: dict[str, Any] = {}

    @staticmethod
    def _cached_price(registry_entry: dict[str, Any]) -> float | None:
        for key in CACHED_PRICE_KEYS:
            if key in registry_entry:
                return float(registry_entry[key])
        return None

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
        self.pending = self._usage_to_ledger(data.get("usage", {}), elapsed)
        return data["choices"][0]["message"].get("content") or ""

    def _usage_to_ledger(self, usage: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached_tokens = int(details.get("cached_tokens") or 0)
        billable_input_tokens = max(input_tokens - cached_tokens, 0)

        extra: dict[str, Any] = {"evidence_class": "single-source, cross-provider"}
        if cached_tokens and self.cached_price_in is None:
            cached_price = self.price_in
            extra["cache_pricing"] = "full_input_rate_assumed"
        else:
            cached_price = self.cached_price_in if self.cached_price_in is not None else self.price_in
            if cached_tokens:
                extra["cache_pricing"] = "registry_cached_input_rate"

        cost = (
            billable_input_tokens * self.price_in
            + cached_tokens * cached_price
            + output_tokens * self.price_out
        ) / 1_000_000
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cached_tokens,
            "cache_write_tokens": 0,
            "cost_usd": round(cost, 8),
            "latency_ms": round(elapsed_ms, 3),
            "extra": extra,
        }


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
    try:
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
    except subprocess.TimeoutExpired as e:
        return False, f"GRADER TIMEOUT: {e}"
    except Exception as e:  # defensive: grader failures are evidence, not erased spend
        return False, f"GRADER ERROR: {type(e).__name__}: {e}"


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
    except subprocess.TimeoutExpired as e:
        return False, f"GRADER TIMEOUT: {e}"
    except Exception as e:
        return False, f"GRADER ERROR: {type(e).__name__}: {e}\n{text}"


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


def merge_extra(base: dict[str, Any] | None, more: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(more)
    return merged


def log_generation(caller: OpenAICaller, *, task_id: str, phase: str, trial: int,
                   attempt_id: str, response: str, note: str = "") -> None:
    usage = dict(caller.pending)
    extra = merge_extra(usage.pop("extra", {}), {
        "attempt_id": attempt_id,
        "response_sha256": short_hash(response),
    })
    log_call(
        LEDGER,
        ts=stamp(),
        account=caller.account,
        model=caller.model,
        tier="cheap",
        task_id=task_id,
        phase=phase,
        outcome="generated",
        effort="",
        trial=trial,
        note=note,
        **usage,
        extra=extra,
    )


def log_grade(caller: OpenAICaller, *, task_id: str, phase: str, trial: int,
              parent_attempt_id: str, candidate_text: str, passed: bool, report: str) -> None:
    outcome = "pass" if passed else "fail"
    if report.startswith("GRADER TIMEOUT:") or report.startswith("GRADER ERROR:"):
        outcome = "error"
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
        note=report[:1000],
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.0,
        latency_ms=0.0,
        extra={
            "evidence_class": "single-source, cross-provider",
            "parent_attempt_id": parent_attempt_id,
            "candidate_sha256": short_hash(candidate_text),
        },
    )


def grade_response(task_id: str, response: str) -> tuple[bool, str, str]:
    if task_id == "task06_select":
        passed, report = grade_counterexample(response)
        return passed, report, response
    candidate = extract_code(response)
    passed, report = grade_code(task_id, candidate)
    return passed, report, candidate


def run_trial(caller: OpenAICaller, task_id: str, phase: str, trial: int) -> tuple[bool, str]:
    packet = read_public_packet(task_id)
    if phase == "solo":
        attempt_id = new_attempt_id(task_id, phase, trial)
        response = caller.call(solver_prompt(task_id, packet))
        log_generation(
            caller,
            task_id=task_id,
            phase="solo_generate",
            trial=trial,
            attempt_id=attempt_id,
            response=response,
        )
        passed, report, candidate_text = grade_response(task_id, response)
        log_grade(
            caller,
            task_id=task_id,
            phase="solo_grade",
            trial=trial,
            parent_attempt_id=attempt_id,
            candidate_text=candidate_text,
            passed=passed,
            report=report,
        )
        return passed, report

    lens_calls: list[dict[str, Any]] = []

    def lens_call(prompt: str) -> str:
        lens_attempt_id = new_attempt_id(task_id, "harness_lens", trial)
        text = caller.call(prompt)
        lens_calls.append({"usage": dict(caller.pending), "text": text, "attempt_id": lens_attempt_id})
        return text

    result = review(packet, lens_call, lenses=all_lenses())
    for i, call in enumerate(lens_calls, start=1):
        caller.pending = call["usage"]
        log_generation(
            caller,
            task_id=task_id,
            phase=f"harness_lens_{i}",
            trial=trial,
            attempt_id=call["attempt_id"],
            response=call["text"],
        )

    attempt_id = new_attempt_id(task_id, "harness_synthesize", trial)
    response = caller.call(synth_prompt(task_id, packet, result.merged_text()))
    log_generation(
        caller,
        task_id=task_id,
        phase="harness_synthesize",
        trial=trial,
        attempt_id=attempt_id,
        response=response,
    )
    passed, report, candidate_text = grade_response(task_id, response)
    log_grade(
        caller,
        task_id=task_id,
        phase="harness_grade",
        trial=trial,
        parent_attempt_id=attempt_id,
        candidate_text=candidate_text,
        passed=passed,
        report=report,
    )
    return passed, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4.1-mini")
    ap.add_argument("--account", default="codex-openai")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=2500)
    args = ap.parse_args()
    registry_entry = model_registry_entry(args.model)
    caller = OpenAICaller(args.model, args.account, registry_entry, args.max_tokens)
    for task_id in TASKS:
        for phase in ("solo", "harness"):
            for trial in range(1, args.k + 1):
                passed, report = run_trial(caller, task_id, phase, trial)
                print(f"{task_id} {phase} trial={trial}: {'PASS' if passed else 'FAIL'}")
                print(report.splitlines()[0] if report else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
