#!/usr/bin/env python3
"""Run a bounded local edit against a real validator before spending cloud tokens."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MODELS = ("qwen2.5:7b", "qwen3.5:9b-q4_K_M")


@dataclass
class Validation:
    returncode: int
    output: str
    elapsed_seconds: float


def inside_repo(repo: Path, value: str) -> Path:
    path = (repo / value).resolve()
    if os.path.commonpath((str(repo), str(path))) != str(repo):
        raise ValueError(f"path escapes repository: {value}")
    if not path.is_file():
        raise ValueError(f"file does not exist: {value}")
    return path


def run_validator(repo: Path, command: list[str], timeout: int) -> Validation:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        output = completed.stdout + completed.stderr
        return Validation(completed.returncode, output, time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return Validation(124, f"{stdout}{stderr}\nvalidator timed out", time.monotonic() - started)


def ollama_generate(
    url: str,
    model: str,
    prompt: str,
    timeout: int,
    num_predict: int,
) -> dict:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0,
                "seed": 42,
                "num_predict": num_predict,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def codex_generate(
    codex_path: str,
    repo: Path,
    model: str,
    effort: str,
    prompt: str,
    timeout: int,
) -> dict:
    executable = codex_path or shutil.which("codex")
    if not executable:
        raise ValueError("Codex CLI not found; pass --codex-path")
    command = [
        executable,
        "exec",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "browser_use",
        "--disable",
        "image_generation",
        "--disable",
        "goals",
        "--disable",
        "tool_suggest",
        "--disable",
        "multi_agent",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        'web_search="disabled"',
        "-c",
        'history.persistence="none"',
        "-c",
        'approval_policy="never"',
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--cd",
        str(repo),
        "-",
    ]
    with tempfile.TemporaryDirectory(prefix="local-first-") as temp:
        candidate_path = Path(temp) / "candidate.txt"
        command[command.index("--cd"):command.index("--cd")] = [
            "--output-last-message",
            str(candidate_path),
        ]
        completed = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        events = []
        for line in completed.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if completed.returncode != 0:
            raise ValueError(
                f"Codex CLI exited {completed.returncode}: {completed.stderr[-1000:].strip()}"
            )
        tool_items = [
            event
            for event in events
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type")
            in {"command_execution", "file_change"}
        ]
        if tool_items:
            raise ValueError("bounded cloud candidate attempted tool use")
        usage_events = [event for event in events if event.get("type") == "turn.completed"]
        if not usage_events or not candidate_path.is_file():
            raise ValueError("Codex CLI returned no completed usage or candidate")
        return {
            "response": candidate_path.read_text(encoding="utf-8"),
            "usage": usage_events[-1]["usage"],
        }


def clean_candidate(response: str) -> str:
    candidate = response.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    return candidate + "\n" if candidate else ""


def build_prompt(
    task_name: str,
    task: str,
    target_name: str,
    target: str,
    contexts: list[tuple[str, str]],
    baseline: str,
) -> str:
    context_text = "\n\n".join(
        f"--- READ-ONLY {name} ---\n{text}" for name, text in contexts
    )
    return f"""You are a bounded code executor. Do not call tools.
Return the complete replacement content of {target_name} only.
Do not return a Markdown fence, explanation, tests, or any other file.
Implement the task exactly. Do not weaken or edit the validator.

--- {task_name} ---
{task}

--- CURRENT {target_name} ---
{target}

{context_text}

--- OBSERVED VALIDATOR FAILURE ---
{baseline[-12000:]}
"""


def write_fallback_crate(
    repo: Path,
    crate_name: str,
    task_name: str,
    target_name: str,
    context_names: list[str],
    validator: list[str],
    baseline: str,
    attempts: list[dict],
) -> Path:
    crate = (repo / crate_name).resolve()
    if os.path.commonpath((str(repo), str(crate))) != str(repo):
        raise ValueError(f"crate path escapes repository: {crate_name}")
    crate.parent.mkdir(parents=True, exist_ok=True)
    failures = "\n".join(
        f"- `{attempt['model']}`: {attempt['failure']}" for attempt in attempts
    )
    context_lines = "\n".join(f"- `{name}` (read-only)" for name in context_names)
    command = subprocess.list2cmdline(validator)
    crate.write_text(
        f"""# Objective

Execute the task in `{task_name}`.

# Observed failure

```text
{baseline[-6000:].rstrip()}
```

# Allowed edits

- `{target_name}`

# Repository pointers

- `{task_name}` (read-only)
{context_lines}

# Local attempts

{failures}

# Acceptance

```powershell
{command}
```
""",
        encoding="utf-8",
        newline="\n",
    )
    return crate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run validator-gated local and bounded cloud edits before a full agent."
    )
    parser.add_argument("--repo", required=True, help="Repository root")
    parser.add_argument("--task", required=True, help="Task file relative to repo")
    parser.add_argument("--target", required=True, help="Single editable file relative to repo")
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        help="Read-only context file relative to repo; repeat as needed",
    )
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Comma-separated Ollama models in attempt order",
    )
    parser.add_argument(
        "--skip-local",
        action="store_true",
        help="Do not contact Ollama; continue to the explicitly selected cloud or crate path",
    )
    parser.add_argument(
        "--cloud-candidate",
        action="store_true",
        help="After local skip/failure, explicitly run bounded Codex refinement before writing a crate",
    )
    parser.add_argument("--cloud-model", default="gpt-5.3-codex-spark")
    parser.add_argument("--cloud-effort", default="low")
    parser.add_argument(
        "--cloud-attempts",
        type=int,
        default=3,
        help="Maximum validator-driven bounded cloud attempts; stops on first pass",
    )
    parser.add_argument("--cloud-timeout", type=int, default=180)
    parser.add_argument("--codex-path", default="")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model-timeout", type=int, default=180)
    parser.add_argument("--validator-timeout", type=int, default=120)
    parser.add_argument("--num-predict", type=int, default=2000)
    parser.add_argument("--crate", default=".cart0/plan.md")
    parser.add_argument(
        "validator",
        nargs=argparse.REMAINDER,
        help="Validator command after --, for example: -- python -m unittest -v",
    )
    args = parser.parse_args()
    if args.validator and args.validator[0] == "--":
        args.validator = args.validator[1:]
    if not args.validator:
        parser.error("validator command is required after --")
    if args.cloud_attempts < 1:
        parser.error("--cloud-attempts must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise ValueError(f"repository does not exist: {repo}")

    task_path = inside_repo(repo, args.task)
    target_path = inside_repo(repo, args.target)
    context_paths = [inside_repo(repo, name) for name in args.context]
    original = target_path.read_bytes()

    baseline = run_validator(repo, args.validator, args.validator_timeout)
    print(
        f"baseline exit={baseline.returncode} elapsed={baseline.elapsed_seconds:.3f}s",
        file=sys.stderr,
    )
    if baseline.returncode == 0:
        print(json.dumps({"status": "already_passing", "cloud_tokens": 0}))
        return 0

    task_text = task_path.read_text(encoding="utf-8")
    target_text = original.decode("utf-8")
    contexts = [
        (name, path.read_text(encoding="utf-8"))
        for name, path in zip(args.context, context_paths)
    ]
    prompt = build_prompt(
        args.task,
        task_text,
        args.target,
        target_text,
        contexts,
        baseline.output,
    )

    attempts: list[dict] = []
    if args.skip_local:
        attempts.append({"model": "local execution", "failure": "skipped by --skip-local"})
        print("local execution skipped", file=sys.stderr)
    else:
        for model in (item.strip() for item in args.models.split(",") if item.strip()):
            target_path.write_bytes(original)
            print(f"local model={model}", file=sys.stderr)
            try:
                response = ollama_generate(
                    args.ollama_url,
                    model,
                    prompt,
                    args.model_timeout,
                    args.num_predict,
                )
                candidate = clean_candidate(response.get("response", ""))
                if not candidate:
                    raise ValueError(
                        f"empty candidate; done_reason={response.get('done_reason', 'unknown')}"
                    )
                target_path.write_text(candidate, encoding="utf-8", newline="\n")
                validation = run_validator(repo, args.validator, args.validator_timeout)
                attempt = {
                    "model": model,
                    "prompt_tokens": response.get("prompt_eval_count", 0),
                    "generated_tokens": response.get("eval_count", 0),
                    "validator_exit": validation.returncode,
                    "validator_seconds": round(validation.elapsed_seconds, 3),
                }
                if validation.returncode == 0:
                    attempt.update({"status": "passed", "cloud_tokens": 0})
                    print(json.dumps(attempt, indent=2))
                    return 0
                attempt["failure"] = validation.output[-2000:].strip()
                attempts.append(attempt)
                print(f"validator still fails for {model}", file=sys.stderr)
            except (OSError, ValueError, urllib.error.URLError) as exc:
                attempts.append({"model": model, "failure": str(exc)})
                print(f"local attempt failed for {model}: {exc}", file=sys.stderr)

    if args.cloud_candidate:
        target_path.write_bytes(original)
        cloud_name = f"cloud:{args.cloud_model}"
        print(f"bounded cloud model={args.cloud_model}", file=sys.stderr)
        cloud_prompt = prompt
        cloud_input = 0
        cloud_cached = 0
        cloud_output = 0
        for cloud_try in range(1, args.cloud_attempts + 1):
            print(
                f"bounded cloud attempt={cloud_try}/{args.cloud_attempts}",
                file=sys.stderr,
            )
            try:
                response = codex_generate(
                    args.codex_path,
                    repo,
                    args.cloud_model,
                    args.cloud_effort,
                    cloud_prompt,
                    args.cloud_timeout,
                )
                candidate = clean_candidate(response["response"])
                if not candidate:
                    raise ValueError("empty bounded cloud candidate")
                usage = response["usage"]
                cloud_input += usage.get("input_tokens", 0)
                cloud_cached += usage.get("cached_input_tokens", 0)
                cloud_output += usage.get("output_tokens", 0)
                target_path.write_text(candidate, encoding="utf-8", newline="\n")
                validation = run_validator(repo, args.validator, args.validator_timeout)
                attempt = {
                    "model": cloud_name,
                    "refinement_attempt": cloud_try,
                    "input_tokens": cloud_input,
                    "cached_input_tokens": cloud_cached,
                    "output_tokens": cloud_output,
                    "validator_exit": validation.returncode,
                    "validator_seconds": round(validation.elapsed_seconds, 3),
                    "cloud_tokens": cloud_input + cloud_output,
                }
                if validation.returncode == 0:
                    attempt["status"] = "passed"
                    print(json.dumps(attempt, indent=2))
                    return 0
                attempt["failure"] = validation.output[-2000:].strip()
                attempts.append(attempt)
                cloud_prompt = build_prompt(
                    args.task,
                    task_text,
                    args.target,
                    candidate,
                    contexts,
                    "Previous bounded candidate failed the validator:\n"
                    + validation.output,
                )
                print("bounded candidate failed; refining from validator output", file=sys.stderr)
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                attempts.append(
                    {
                        "model": cloud_name,
                        "refinement_attempt": cloud_try,
                        "failure": str(exc),
                    }
                )
                print(f"bounded cloud attempt failed: {exc}", file=sys.stderr)

    target_path.write_bytes(original)
    crate = write_fallback_crate(
        repo,
        args.crate,
        args.task,
        args.target,
        args.context,
        args.validator,
        baseline.output,
        attempts,
    )
    print(
        json.dumps(
            {
                "status": "needs_cloud_executor",
                "local_skipped": args.skip_local,
                "source_restored": True,
                "crate": str(crate),
                "attempts": attempts,
            },
            indent=2,
        )
    )
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"local-first: {exc}", file=sys.stderr)
        raise SystemExit(3)
