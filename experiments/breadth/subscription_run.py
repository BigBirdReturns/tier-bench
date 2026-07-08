#!/usr/bin/env python3
"""Manual subscription-surface breadth runner.

This helper does not call provider APIs. It emits public-only prompts for models
visible in a ChatGPT/Codex subscription surface, then grades saved candidates
locally with the task hidden graders. The ledger rows deliberately use zero
input/output/cache tokens and zero cost because subscription-surface usage is
not API-billed telemetry unless the surface exposes exact usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.breadth.ledger import log_call  # noqa: E402

DEFAULT_LEDGER = ROOT / "experiments/breadth/run/subscription_ledger.jsonl"
TASK_ROOT = ROOT / "experiments/tier-uplift"
TASKS = {
    "task01_parse_duration": TASK_ROOT / "task01_parse_duration",
    "task02_wildcard": TASK_ROOT / "task02_wildcard",
    "task06_select": TASK_ROOT / "task06_select",
}
HIDDEN_NAME_PATTERNS = (
    r"hidden_tests\.py",
    r"hidden_oracle\.py",
    r"grader\.py",
    r"answer_key\.md",
)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def attempt_id(task_id: str, phase: str, trial: int) -> str:
    return f"{task_id}:{phase}:{trial}:{uuid.uuid4().hex[:12]}"


def scrub_public_text(text: str) -> str:
    """Remove incidental hidden-artifact filenames from public comments/docs.

    This is not a permission boundary. The boundary is that hidden files are never
    read into the prompt. Scrubbing only prevents public docstrings/comments from
    accidentally naming hidden artifacts when a prompt is pasted into a model UI.
    """
    out = text
    for pattern in HIDDEN_NAME_PATTERNS:
        out = re.sub(pattern, "[hidden artifact]", out)
    return out


def public_packet(task_id: str) -> str:
    d = TASKS[task_id]
    parts = [f"# {task_id}", scrub_public_text((d / "spec.md").read_text(encoding="utf-8"))]
    subject = d / "subject.py"
    if subject.exists():
        parts.append(
            "## subject.py\n```python\n"
            + scrub_public_text(subject.read_text(encoding="utf-8"))
            + "\n```"
        )
    visible = d / "visible_tests.py"
    if visible.exists():
        parts.append(
            "## visible_tests.py\n```python\n"
            + scrub_public_text(visible.read_text(encoding="utf-8"))
            + "\n```"
        )
    else:
        parts.append("## visible_tests.py\nNo visible validator is provided for this task.")
    return "\n\n".join(parts)


def prompt_for(task_id: str, selected_model_label: str, phase: str, trial: int) -> str:
    if task_id == "task06_select":
        expected = "Return exactly one counterexample as: items=[...]; k=..."
    else:
        expected = "Return only the Python function implementation. No prose, no markdown."
    return (
        f"You are the selected subscription-surface model: {selected_model_label}.\n"
        f"Task: {task_id}\n"
        f"Phase: {phase}\n"
        f"Trial: {trial}\n\n"
        "Use only the public task packet below. Do not assume access to hidden tests, "
        "hidden graders, answer keys, or repository files not shown here.\n\n"
        + public_packet(task_id)
        + "\n\n"
        + expected
        + "\n"
    )


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


def grade_code(task_id: str, candidate_text: str) -> tuple[bool, str, str]:
    code = extract_code(candidate_text)
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
        return bool(m and m.group(1) == m.group(2)), out, code
    except subprocess.TimeoutExpired as e:
        return False, f"GRADER TIMEOUT: {e}", code
    except Exception as e:
        return False, f"GRADER ERROR: {type(e).__name__}: {e}", code


def grade_counterexample(candidate_text: str) -> tuple[bool, str, str]:
    try:
        m = re.search(r"items\s*=\s*(\[.*?\])\s*;?\s*k\s*=\s*(-?\d+)", candidate_text, re.S)
        if not m:
            raise ValueError("candidate did not contain `items=[...]; k=...`")
        check = f"items={m.group(1)}; k={m.group(2)}"
        p = subprocess.run(
            [sys.executable, str(TASKS["task06_select"] / "grader.py"), "--check", check],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        return "COUNTEREXAMPLE: True" in p.stdout, p.stdout, check
    except subprocess.TimeoutExpired as e:
        return False, f"GRADER TIMEOUT: {e}", candidate_text
    except Exception as e:
        return False, f"GRADER ERROR: {type(e).__name__}: {e}", candidate_text


def grade_candidate(task_id: str, candidate_text: str) -> tuple[bool, str, str]:
    if task_id == "task06_select":
        return grade_counterexample(candidate_text)
    return grade_code(task_id, candidate_text)


def subscription_extra(
    *,
    selected_model_label: str,
    token_accounting: str,
    cost_accounting: str,
    quota_status: str,
    parent_attempt_id: str,
    candidate_text: str | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "surface": "chatgpt_codex_subscription",
        "selected_model_label": selected_model_label,
        "telemetry_class": "subscription_surface",
        "token_accounting": token_accounting,
        "cost_accounting": cost_accounting,
        "quota_status": quota_status,
        "parent_attempt_id": parent_attempt_id,
    }
    if candidate_text is not None:
        extra["candidate_sha256"] = sha256_text(candidate_text)
    return extra


def log_subscription_row(
    ledger: Path,
    *,
    selected_model_label: str,
    task_id: str,
    phase: str,
    trial: int,
    outcome: str,
    note: str,
    quota_status: str = "",
    parent_attempt_id: str | None = None,
    candidate_text: str | None = None,
) -> None:
    parent = parent_attempt_id or attempt_id(task_id, phase, trial)
    log_call(
        ledger,
        ts=stamp(),
        account="subscription",
        model=selected_model_label,
        tier="subscription",
        task_id=task_id,
        phase=phase,
        outcome=outcome,
        effort="",
        trial=trial,
        note=note[:1000],
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.0,
        latency_ms=0.0,
        # log_call routes unknown kwargs into Call.extra itself; passing extra=
        # explicitly collides with that and raises TypeError.
        **subscription_extra(
            selected_model_label=selected_model_label,
            token_accounting="unavailable",
            cost_accounting="subscription_quota" if quota_status else "unavailable",
            quota_status=quota_status,
            parent_attempt_id=parent,
            candidate_text=candidate_text,
        ),
    )


def emit_prompts(args: argparse.Namespace) -> int:
    prompt_dir = Path(args.prompt_dir)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    task_ids = TASKS.keys() if args.task_id == "all" else [args.task_id]
    for task_id in task_ids:
        prompt = prompt_for(task_id, args.selected_model_label, args.phase, args.trial)
        out = prompt_dir / f"{task_id}.{args.phase}.prompt.md"
        out.write_text(prompt, encoding="utf-8")
        print(out)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit/grade subscription-surface breadth attempts.")
    ap.add_argument("--selected-model-label", required=True)
    ap.add_argument("--task-id", required=True, choices=["all", *TASKS.keys()])
    ap.add_argument("--phase", default="solo", choices=["solo", "harness"])
    ap.add_argument("--trial", type=int, default=1)
    ap.add_argument("--candidate-file")
    ap.add_argument("--prompt-dir")
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--blocked", action="store_true")
    ap.add_argument("--quota-status", default="")
    args = ap.parse_args()

    if args.prompt_dir:
        return emit_prompts(args)

    if args.task_id == "all":
        raise SystemExit("--task-id all is only valid with --prompt-dir")

    if args.blocked:
        log_subscription_row(
            args.ledger,
            selected_model_label=args.selected_model_label,
            task_id=args.task_id,
            phase=args.phase,
            trial=args.trial,
            outcome="blocked",
            note="subscription model unavailable or quota blocked before candidate generation",
            quota_status=args.quota_status,
        )
        return 0

    if not args.candidate_file:
        raise SystemExit("--candidate-file is required unless --prompt-dir or --blocked is used")
    candidate_text = Path(args.candidate_file).read_text(encoding="utf-8")
    parent = attempt_id(args.task_id, args.phase, args.trial)
    passed, report, canonical_candidate = grade_candidate(args.task_id, candidate_text)
    outcome = "pass" if passed else "fail"
    if report.startswith("GRADER TIMEOUT:") or report.startswith("GRADER ERROR:"):
        outcome = "error"
    log_subscription_row(
        args.ledger,
        selected_model_label=args.selected_model_label,
        task_id=args.task_id,
        phase=f"{args.phase}_grade",
        trial=args.trial,
        outcome=outcome,
        note=report,
        quota_status=args.quota_status,
        parent_attempt_id=parent,
        candidate_text=canonical_candidate,
    )
    print(f"{args.task_id} {args.phase} trial={args.trial}: {outcome.upper()}")
    print(report.splitlines()[0] if report else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
