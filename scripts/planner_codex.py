"""Turn a brief file into work-item JSON by shelling out to the Codex CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from tier_runner.desk_common import hidden_process_kwargs


DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "medium"
FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    stripped = text.strip()
    match = FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_command(model: str, effort: str, last_message_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-o",
        str(last_message_path),
        "-",
    ]


def run_codex(brief_text: str, model: str, effort: str, last_message_path: Path) -> None:
    result = subprocess.run(
        build_command(model, effort, last_message_path),
        input=brief_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_process_kwargs(),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise RuntimeError(f"codex exec exited {result.returncode}: {detail}")


def load_brief(brief_path: Path) -> str:
    return brief_path.read_text(encoding="utf-8")


def parse_last_message(last_message_path: Path) -> dict:
    raw_message = last_message_path.read_text(encoding="utf-8")
    candidate = strip_fences(raw_message)
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("codex output must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("planner_codex: usage: planner_codex.py <brief_path> <out_path>", file=sys.stderr)
        return 2
    brief_path, out_path = Path(args[0]), Path(args[1])
    model = os.environ.get("PLANNER_MODEL", DEFAULT_MODEL)
    effort = os.environ.get("PLANNER_EFFORT", DEFAULT_EFFORT)
    try:
        brief_text = load_brief(brief_path)
    except OSError as exc:
        print(f"planner_codex: cannot read brief: {exc}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        last_message_path = Path(tmp) / "last_message.txt"
        try:
            run_codex(brief_text, model, effort, last_message_path)
        except (RuntimeError, OSError) as exc:
            print(f"planner_codex: {exc}", file=sys.stderr)
            return 2
        try:
            value = parse_last_message(last_message_path)
        except OSError as exc:
            print(f"planner_codex: codex did not produce a last-message file: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"planner_codex: codex output is not valid JSON: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"planner_codex: {exc}", file=sys.stderr)
            return 2
    try:
        out_path.write_text(canonical(value), encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"planner_codex: cannot write output: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
