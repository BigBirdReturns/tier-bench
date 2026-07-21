from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from .desk_common import DeskError, hidden_process_kwargs
from .benchmark_report import REPORT_PATH, ReportError, is_benchmark_intent, requested_count


LOCAL_BENCHMARK_MODEL = "qwen3.5:9b-q4_K_M"


def _title(intent: str) -> str:
    first_line = next((line.strip() for line in intent.splitlines() if line.strip()), "")
    sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0]
    value = sentence.rstrip(".!?").strip()
    if len(value) <= 80:
        return value
    return value[:77].rstrip() + "..."


_AUTO_SCOPE_EXCLUDES = {
    ".claude",
    ".codex",
    ".github",
    ".tier",
    "AGENTS.md",
    "CLAUDE.md",
    "pilot_backends.json",
}
_DESK_INTENT_HINTS = {
    "dashboard",
    "desk",
    "gauge",
    "graph",
    "receipt",
    "scheduler",
    "theme",
    "worker",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower().replace("_", "-"))
        if len(token) > 2
    }


def _tracked_root_scopes(repo: Path, intent: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo,
            capture_output=True,
            timeout=5,
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeskError(f"could not read the managed project scope: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise DeskError(f"could not read the managed project scope: {detail or 'git failed'}")
    tracked = [
        raw
        for raw in result.stdout.decode("utf-8", errors="strict").split("\0")
        if raw
    ]
    normalized_intent = intent.replace("\\", "/").lower()
    named = [
        raw
        for raw in tracked
        if raw.lower() in normalized_intent
        and PurePosixPath(raw).parts[0] not in _AUTO_SCOPE_EXCLUDES
    ]
    if named:
        return sorted(named)

    roots: dict[str, list[str]] = {}
    for raw in tracked:
        first = PurePosixPath(raw).parts[0]
        if first == ".git" or first in _AUTO_SCOPE_EXCLUDES:
            continue
        scope = first + "/" if (repo / first).is_dir() else first
        roots.setdefault(scope, []).append(raw)
    if not roots:
        raise DeskError("the managed project has no committed files to bound this work")
    if len(roots) > 100:
        raise DeskError("the managed project has too many top-level areas for an automatic safe scope")

    intent_tokens = _tokens(intent)
    scored = {
        scope: max((len(intent_tokens & _tokens(path)) for path in paths), default=0)
        for scope, paths in roots.items()
    }
    if intent_tokens & _DESK_INTENT_HINTS:
        selected = {
            scope
            for scope in roots
            if scope.rstrip("/") in {"tier_runner", "tests", "docs", "site"}
        }
    else:
        selected = {scope for scope, score in scored.items() if score > 0}
    if not selected:
        selected.update(
            scope
            for scope in roots
            if scope.rstrip("/")
            in {"app", "lib", "src", "tests", "tier_runner", "packages"}
        )
    if not selected:
        raise DeskError(
            "I could not infer a narrow editable area from that request. "
            "Name one code area or file; the desk will keep the rest outside model scope."
        )
    return sorted(selected)


def _acceptance(repo: Path, intent: str, files: list[str]) -> tuple[str, str]:
    insertion_check = ""
    lowered = intent.lower()
    if (
        len(files) == 1
        and not files[0].endswith("/")
        and "add one" in lowered
        and ("preserve the rest" in lowered or "preserve every other" in lowered)
    ):
        insertion_check = subprocess.list2cmdline(
            [
                "python",
                "-m",
                "tier_runner.intent_acceptance",
                "insertion",
                "--path",
                files[0],
                "--max-added-lines",
                "2",
            ]
        ) + " && "
    desk_test = repo / "tests" / "test_tier_desk.py"
    if desk_test.is_file():
        return (
            insertion_check + "python -B tests/test_tier_desk.py",
            (
                "an insertion-only preservation check plus the project's dedicated Tier Desk test suite"
                if insertion_check
                else "the project's dedicated Tier Desk test suite"
            ),
        )
    if (repo / "pyproject.toml").is_file() and (repo / "tests").is_dir():
        return insertion_check + "python -m pytest -q", "the Python test suite already present in the project"
    package = repo / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, dict) else None
        if isinstance(scripts, dict) and scripts.get("test"):
            return insertion_check + "npm test", "the test script declared by this project"
    if (repo / "Cargo.toml").is_file():
        return insertion_check + "cargo test", "the Rust test suite declared by this project"
    if (repo / "go.mod").is_file():
        return insertion_check + "go test ./...", "the Go test suite declared by this project"
    if (repo / "Makefile").is_file():
        return insertion_check + "make test", "the project's conventional test target"
    raise DeskError(
        "I could not find a trustworthy proof command in this project. "
        "Open Change technical details and tell the desk how to prove the result."
    )


def plan_intent(repo: Path, payload: dict[str, Any]) -> dict[str, Any]:
    intent = str(payload.get("intent", "")).strip()
    if not intent or len(intent) > 12000:
        raise DeskError("tell the desk what should happen in 1 to 12,000 characters")
    if is_benchmark_intent(intent):
        try:
            count = requested_count(intent)
        except (ReportError, ValueError) as exc:
            raise DeskError(str(exc)) from exc
        return {
            "title": _title(intent),
            "task": intent,
            "files": ["data/"],
            "acceptance": (
                "python -m tier_runner.benchmark_report verify "
                f"--path {REPORT_PATH} --expected-count {count} "
                f"--expected-model {LOCAL_BENCHMARK_MODEL}"
            ),
            "manifest": "pilot_backends.json",
            "arm": "benchmark_local",
            "priority": 50,
            "depends_on": [],
            "why": {
                "scope": (
                    f"This is an observation run, so the only repository output is the "
                    f"{count}-row benchmark report under data/. Source tasks and fixtures "
                    "remain read-only."
                ),
                "acceptance": (
                    f"The report verifier requires exactly {count} distinct benchmark rows, "
                    "the frozen local model, provider token telemetry, and totals that equal "
                    "the underlying rows."
                ),
                "worker": (
                    "The installed local Qwen model runs the existing Tier-Bench tasks "
                    "sequentially. Each call gets its own ledger receipt; no cloud budget is used."
                ),
            },
        }
    files = _tracked_root_scopes(repo, intent)
    acceptance, acceptance_reason = _acceptance(repo, intent, files)
    title = _title(intent)
    return {
        "title": title,
        "task": intent,
        "files": files,
        "acceptance": acceptance,
        "manifest": "pilot_backends.json",
        "arm": "arm_b",
        "priority": 50,
        "depends_on": [],
        "why": {
            "scope": (
                f"The desk recognized {len(files)} committed files named in your request; "
                "instruction files, .git, and paths outside the project stay forbidden."
                if all(not value.endswith("/") for value in files)
                else f"The desk inferred {len(files)} committed top-level code areas "
                "from your request; instruction files, .git, and paths outside "
                "the project stay forbidden."
            ),
            "acceptance": f"The desk selected {acceptance_reason}.",
            "worker": (
                "Local Qwen is the only Start-ready file hand. Scope, acceptance, "
                "and receipts are enforced outside the model; cloud hands remain "
                "gated until fresh writer canaries pass."
            ),
        },
    }
