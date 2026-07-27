from __future__ import annotations

"""Physical local-coding flight for Tier Bench's sealed ``tier run`` boundary.

The command creates a disposable calibration repository whose hidden tests are
outside the model packet, freezes the exact Claude Code and Ollama surfaces into
that repository, runs the same tasks through three local model cartridges, and
emits one comparison report without promoting any model automatically.
"""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import threading
from typing import Any
import uuid

from .adapters.claude_code_ollama import (
    ADAPTER_VERSION,
    SERVER_ATTESTATION_SCHEMA,
    _adapter_source_sha256,
    _api_json,
    _canonical,
    _help_surface,
    _find_model,
    _loopback_base_url,
    _model_digest,
    _server_attestation,
    _sha_bytes,
    _version,
)


REPORT_SCHEMA = "tier-bench/local-coding-flight-report@1"
MIN_OLLAMA_VERSION = (0, 13, 3)
MODEL_SUITE = (
    ("arm_a", "gpt-oss:20b", "medium"),
    ("arm_b", "qwen3-coder:30b", "medium"),
    ("arm_c", "devstral-small-2:24b", "medium"),
)
PROFILE_TASKS = {
    "smoke": ("port-range",),
    "core": ("port-range", "quoted-csv", "cache-key"),
    "adversarial": ("port-range", "quoted-csv", "cache-key", "escaped-class"),
}
PROMPT_TEMPLATE = """You are the implementation worker inside a sealed Tier Bench coding flight.

Make the smallest correct change that satisfies the task. Inspect and edit only the files present in this packet. You have no Git repository, no hidden tests, no shell, no network, and no authority to alter the acceptance command. Do not create instruction files or unrelated artifacts. Finish by leaving the corrected files on disk; prose is not an acceptance signal.

Task:
{{TASK}}

Allowed files:
{{FILES}}

External acceptance command, shown only to bind the operator's verifier:
{{ACCEPTANCE}}

Base commit:
{{BASE_COMMIT}}
"""

TASKS: dict[str, dict[str, Any]] = {
    "port-range": {
        "title": "Port parser boundary repair",
        "task": (
            "Repair parse_port. It must accept integers and surrounding-whitespace decimal "
            "strings only when the resulting port is in 1..65535. It must reject booleans, "
            "signs, decimal notation, empty strings, non-numeric values, zero, and values "
            "above 65535 by raising ValueError. Preserve the public function name."
        ),
        "files": ["src/ports.py"],
        "acceptance": "python -m unittest tests.test_ports -v",
    },
    "quoted-csv": {
        "title": "Quoted record parser repair",
        "task": (
            "Repair parse_records to implement the documented CSV contract. The first row "
            "is the header. Quoted commas, doubled quotes, CRLF input, and trailing empty "
            "fields must work. Empty input returns an empty list. Duplicate headers and any "
            "data row with the wrong field count must raise RecordFormatError."
        ),
        "files": ["src/records.py"],
        "acceptance": "python -m unittest tests.test_records -v",
    },
    "cache-key": {
        "title": "Canonical cache identity repair",
        "task": (
            "Repair action_cache_key so semantically identical mappings produce the same "
            "SHA-256 key regardless of insertion order, list order remains significant, "
            "non-finite floats are rejected with ValueError, and CACHE_KEY_SCHEMA is bound "
            "into every key. Keep the API deterministic and JSON-based."
        ),
        "files": ["src/cache.py", "src/identity.py"],
        "acceptance": "python -m unittest tests.test_cache -v",
    },
    "escaped-class": {
        "title": "Escaped character-class boundary repair",
        "task": (
            "Repair glob_to_regex character-class parsing. Inside [...], a backslash escapes "
            "exactly the next character, so an escaped closing bracket is class data and only "
            "an unescaped closing bracket terminates the class. A dangling escape or unclosed "
            "class must raise GlobSyntaxError. Preserve existing *, ?, slash, and negated-class "
            "behavior."
        ),
        "files": ["src/globs.py"],
        "acceptance": "python -m unittest tests.test_globs -v",
    },
}

FIXTURE_FILES = {
    "src/__init__.py": "",
    "src/ports.py": '''from __future__ import annotations\n\n\ndef parse_port(value: object) -> int:\n    """Return a valid TCP/UDP port from an integer or decimal string."""\n    if isinstance(value, int):\n        return value\n    if isinstance(value, str) and value.strip().isdigit():\n        return int(value.strip())\n    raise ValueError("invalid port")\n''',
    "src/records.py": '''from __future__ import annotations\n\n\nclass RecordFormatError(ValueError):\n    pass\n\n\ndef parse_records(text: str) -> list[dict[str, str]]:\n    """Parse a small RFC-4180-compatible table into dictionaries."""\n    if not text:\n        return []\n    rows = [line.split(",") for line in text.splitlines() if line]\n    header = rows[0]\n    return [dict(zip(header, row)) for row in rows[1:]]\n''',
    "src/identity.py": '''from __future__ import annotations\n\n\nCACHE_KEY_SCHEMA = "tier-cache-key/v2"\n''',
    "src/cache.py": '''from __future__ import annotations\n\nimport hashlib\nimport json\nfrom typing import Any\n\n\ndef action_cache_key(action: str, inputs: Any, environment: Any) -> str:\n    payload = {\n        "action": action,\n        "inputs": inputs,\n        "environment": environment,\n    }\n    raw = json.dumps(payload).encode("utf-8")\n    return hashlib.sha256(raw).hexdigest()\n''',
    "src/globs.py": r'''from __future__ import annotations

import re


class GlobSyntaxError(ValueError):
    pass


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    pieces = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        elif char == "[":
            closing = pattern.find("]", index + 1)
            if closing < 0:
                raise GlobSyntaxError("unclosed character class")
            body = pattern[index + 1 : closing]
            negate = body.startswith("!")
            if negate:
                body = body[1:]
            escaped: list[str] = []
            body_index = 0
            while body_index < len(body):
                if body[body_index] == "\\":
                    body_index += 1
                    if body_index >= len(body):
                        raise GlobSyntaxError("dangling class escape")
                escaped.append(re.escape(body[body_index]))
                body_index += 1
            pieces.append("[" + ("^" if negate else "") + "".join(escaped) + "]")
            index = closing
        elif char == "\\":
            index += 1
            if index >= len(pattern):
                raise GlobSyntaxError("dangling escape")
            pieces.append(re.escape(pattern[index]))
        else:
            pieces.append(re.escape(char))
        index += 1
    pieces.append("$")
    return re.compile("".join(pieces))
''',
    "tests/__init__.py": "",
    "tests/test_ports.py": '''from __future__ import annotations\n\nimport unittest\n\nfrom src.ports import parse_port\n\n\nclass PortTests(unittest.TestCase):\n    def test_valid_boundaries_and_decimal_strings(self) -> None:\n        self.assertEqual(parse_port(1), 1)\n        self.assertEqual(parse_port(65535), 65535)\n        self.assertEqual(parse_port(" 443 "), 443)\n\n    def test_invalid_values(self) -> None:\n        for value in (True, False, 0, -1, 65536, "+80", "80.0", "", " ", None):\n            with self.subTest(value=value), self.assertRaises(ValueError):\n                parse_port(value)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    "tests/test_records.py": '''from __future__ import annotations\n\nimport unittest\n\nfrom src.records import RecordFormatError, parse_records\n\n\nclass RecordTests(unittest.TestCase):\n    def test_empty_input(self) -> None:\n        self.assertEqual(parse_records(""), [])\n\n    def test_quotes_crlf_and_trailing_empty(self) -> None:\n        text = 'name,note,tail\\r\\nAda,"one, two",""\\r\\nLin,"said ""yes""",x\\r\\n'\n        self.assertEqual(\n            parse_records(text),\n            [\n                {"name": "Ada", "note": "one, two", "tail": ""},\n                {"name": "Lin", "note": 'said "yes"', "tail": "x"},\n            ],\n        )\n\n    def test_duplicate_header_and_wrong_width(self) -> None:\n        with self.assertRaises(RecordFormatError):\n            parse_records("a,a\\n1,2\\n")\n        with self.assertRaises(RecordFormatError):\n            parse_records("a,b\\n1\\n")\n        with self.assertRaises(RecordFormatError):\n            parse_records("a,b\\n1,2,3\\n")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    "tests/test_cache.py": '''from __future__ import annotations\n\nimport math\nimport unittest\n\nfrom src.cache import action_cache_key\nfrom src.identity import CACHE_KEY_SCHEMA\n\n\nclass CacheTests(unittest.TestCase):\n    def test_mapping_order_is_canonical(self) -> None:\n        first = action_cache_key("build", {"b": 2, "a": 1}, {"z": 0, "x": 3})\n        second = action_cache_key("build", {"a": 1, "b": 2}, {"x": 3, "z": 0})\n        self.assertEqual(first, second)\n        self.assertRegex(first, r"^[0-9a-f]{64}$")\n\n    def test_list_order_remains_significant(self) -> None:\n        self.assertNotEqual(\n            action_cache_key("build", [1, 2], {}),\n            action_cache_key("build", [2, 1], {}),\n        )\n\n    def test_non_finite_values_are_rejected(self) -> None:\n        for value in (math.nan, math.inf, -math.inf):\n            with self.subTest(value=value), self.assertRaises(ValueError):\n                action_cache_key("build", {"value": value}, {})\n\n    def test_schema_is_part_of_identity(self) -> None:\n        import importlib\n        import src.cache as cache\n        import src.identity as identity\n        baseline = cache.action_cache_key("build", {}, {})\n        self.assertIsInstance(CACHE_KEY_SCHEMA, str)\n        self.assertTrue(CACHE_KEY_SCHEMA)\n        original = identity.CACHE_KEY_SCHEMA\n        try:\n            identity.CACHE_KEY_SCHEMA = original + "-changed"\n            importlib.reload(cache)\n            changed = cache.action_cache_key("build", {}, {})\n        finally:\n            identity.CACHE_KEY_SCHEMA = original\n            importlib.reload(cache)\n        self.assertNotEqual(baseline, changed)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    "tests/test_globs.py": r'''from __future__ import annotations

import unittest

from src.globs import GlobSyntaxError, glob_to_regex


class GlobTests(unittest.TestCase):
    def test_escaped_closing_bracket_is_class_data(self) -> None:
        regex = glob_to_regex(r"file[a\]]")
        self.assertIsNotNone(regex.fullmatch("filea"))
        self.assertIsNotNone(regex.fullmatch("file]"))
        self.assertIsNone(regex.fullmatch("fileb"))

    def test_negation_and_slash_behavior_are_preserved(self) -> None:
        self.assertIsNotNone(glob_to_regex("[!a]??").fullmatch("b12"))
        self.assertIsNone(glob_to_regex("*").fullmatch("a/b"))
        self.assertIsNotNone(glob_to_regex("a?b").fullmatch("acb"))

    def test_malformed_classes_fail_closed(self) -> None:
        for pattern in ("[abc", r"[a\]", "abc\\"):
            with self.subTest(pattern=pattern), self.assertRaises(GlobSyntaxError):
                glob_to_regex(pattern)


if __name__ == "__main__":
    unittest.main()
''',
    "AGENTS.md": "This file is deliberately outside the model packet.\n",
}


class FlightError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    if not slug:
        raise FlightError("value has no safe filename characters")
    return slug[:100]


def _run(
    argv: list[str], cwd: Path, *, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode:
        raise FlightError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stderr}"
        )
    return result


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], repo, check=check)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _load_attestation(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlightError(f"cannot read server attestation: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SERVER_ATTESTATION_SCHEMA:
        raise FlightError(f"server attestation schema must be {SERVER_ATTESTATION_SCHEMA}")
    return value


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise FlightError(f"cannot parse Ollama semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def _probe_runtime(
    *,
    claude_bin: str,
    ollama_host: str,
    server_attestation: Path,
    context_length: int,
    models: tuple[tuple[str, str, str], ...] = MODEL_SUITE,
) -> dict[str, Any]:
    endpoint = _loopback_base_url(ollama_host)
    claude_version = _version(claude_bin)
    claude_help_sha256 = _help_surface(claude_bin)
    version_payload = _api_json(endpoint, "/api/version")
    ollama_version = version_payload.get("version")
    if not isinstance(ollama_version, str) or not ollama_version:
        raise FlightError("Ollama returned no version")
    if _version_tuple(ollama_version) < MIN_OLLAMA_VERSION:
        required = ".".join(str(part) for part in MIN_OLLAMA_VERSION)
        raise FlightError(
            f"Ollama {ollama_version} is below required {required} for this model suite"
        )
    attestation_sha256 = _sha_file(server_attestation)
    _server_attestation(
        server_attestation,
        attestation_sha256,
        ollama_host=endpoint,
        ollama_version=ollama_version,
        context_length=context_length,
    )
    tags = _api_json(endpoint, "/api/tags")
    resolved: list[dict[str, str]] = []
    missing: list[str] = []
    for arm, model, effort in models:
        row = _find_model(tags, model, "tags")
        if row is None:
            missing.append(model)
            continue
        digest = _model_digest(row)
        resolved.append(
            {"arm": arm, "model_id": model, "effort": effort, "digest": digest}
        )
    return {
        "ollama_host": endpoint,
        "ollama_version": ollama_version,
        "claude_version": claude_version,
        "claude_help_sha256": claude_help_sha256,
        "server_attestation_sha256": attestation_sha256,
        "models": resolved,
        "missing_models": missing,
    }


def _manifest(
    *,
    protocol_commit: str,
    prompt_rel: str,
    prompt_sha256: str,
    runtime: dict[str, Any],
    claude_bin: str,
    server_attestation: Path,
    context_length: int,
    min_gpu_residency: float,
    call_timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    adapter_source_sha256 = _adapter_source_sha256()
    tool_versions = {
        "claude_code": runtime["claude_version"],
        "claude_help_sha256": runtime["claude_help_sha256"],
        "ollama": runtime["ollama_version"],
        "ollama_endpoint": runtime["ollama_host"],
        "ollama_server_attestation_sha256": runtime["server_attestation_sha256"],
        "tier_claude_ollama_adapter": ADAPTER_VERSION,
        "tier_claude_ollama_adapter_sha256": adapter_source_sha256,
    }
    arms: dict[str, Any] = {}
    for model in runtime["models"]:
        arm = model["arm"]
        arms[arm] = {
            "model_id": model["model_id"],
            "effort": model["effort"],
            "surface": "ollama-claude-code-local",
            "cost_basis": "shadow-estimated",
            "account": "local-3090",
            "tier": "local-coding-candidate",
            "prompt_template": "hands",
            "adapter": {
                "command": [
                    sys.executable,
                    "-m",
                    "tier_runner.adapters.claude_code_ollama",
                    "--arm",
                    "{arm}",
                    "--dispatch",
                    "{dispatch_receipt}",
                    "--prompt",
                    "{prompt}",
                    "--result",
                    "{backend_result}",
                    "--worktree",
                    "{worktree}",
                    "--claude-bin",
                    claude_bin,
                    "--claude-version",
                    runtime["claude_version"],
                    "--claude-help-sha256",
                    runtime["claude_help_sha256"],
                    "--adapter-version",
                    ADAPTER_VERSION,
                    "--adapter-source-sha256",
                    adapter_source_sha256,
                    "--model",
                    model["model_id"],
                    "--effort",
                    model["effort"],
                    "--account",
                    "local-3090",
                    "--tier",
                    "local-coding-candidate",
                    "--surface",
                    "ollama-claude-code-local",
                    "--cost-basis",
                    "shadow-estimated",
                    "--ollama-host",
                    runtime["ollama_host"],
                    "--ollama-version",
                    runtime["ollama_version"],
                    "--ollama-model-digest",
                    model["digest"],
                    "--context-length",
                    str(context_length),
                    "--min-gpu-residency",
                    str(min_gpu_residency),
                    "--server-attestation",
                    str(server_attestation.resolve()),
                    "--server-attestation-sha256",
                    runtime["server_attestation_sha256"],
                    "--call-timeout-seconds",
                    str(call_timeout_seconds),
                ]
            },
        }
    return {
        "schema": "tier-bench/pilot-backends@1",
        "protocol_commit": protocol_commit,
        "isolation": {
            "fresh_session_per_call": True,
            "instruction_files": False,
            "auto_memory": False,
            "conversation_carryover": False,
        },
        "tool_versions": tool_versions,
        "prompt_templates": {
            "hands": {"path": prompt_rel, "sha256": prompt_sha256}
        },
        "arms": arms,
    }


def _create_fixture_repo(
    repo: Path,
    *,
    runtime: dict[str, Any],
    claude_bin: str,
    server_attestation: Path,
    context_length: int,
    min_gpu_residency: float,
    call_timeout_seconds: float = 900.0,
) -> tuple[Path, str]:
    if repo.exists() and any(repo.iterdir()):
        raise FlightError(f"fixture repository is not empty: {repo}")
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tier-local-flight@example.invalid")
    _git(repo, "config", "user.name", "Tier Local Coding Flight")
    for relative, content in FIXTURE_FILES.items():
        _write(repo / relative, content)
    prompt_path = repo / ".tier" / "local-coding" / "hands.prompt.txt"
    _write(prompt_path, PROMPT_TEMPLATE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Freeze hidden calibration corpus and prompt")
    protocol_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", protocol_commit):
        raise FlightError("fixture protocol commit is not a full Git SHA")
    prompt_rel = prompt_path.relative_to(repo / ".tier" / "local-coding").as_posix()
    manifest = _manifest(
        protocol_commit=protocol_commit,
        prompt_rel=prompt_rel,
        prompt_sha256=_sha_file(prompt_path),
        runtime=runtime,
        claude_bin=claude_bin,
        server_attestation=server_attestation,
        context_length=context_length,
        min_gpu_residency=min_gpu_residency,
        call_timeout_seconds=call_timeout_seconds,
    )
    manifest_path = repo / ".tier" / "local-coding" / "pilot_backends.json"
    manifest_path.write_bytes(_canonical(manifest))
    _git(repo, "add", manifest_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-q", "-m", "Freeze physical local coding backends")
    return manifest_path, _git(repo, "rev-parse", "HEAD").stdout.strip()


def _parse_number(value: str) -> float | None:
    value = value.strip()
    if not value or value.upper() == "N/A":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _gpu_snapshot(nvidia_smi: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            nvidia_smi,
            "--query-gpu=timestamp,index,uuid,name,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise FlightError(f"nvidia-smi failed: {result.stderr.strip()}")
    rows: list[dict[str, Any]] = []
    for values in csv.reader((result.stdout or "").splitlines()):
        if len(values) != 6:
            continue
        rows.append(
            {
                "driver_timestamp": values[0].strip(),
                "index": int(values[1].strip()),
                "uuid": values[2].strip(),
                "name": values[3].strip(),
                "memory_used_mib": _parse_number(values[4]),
                "utilization_percent": _parse_number(values[5]),
            }
        )
    if not rows:
        raise FlightError("nvidia-smi returned no GPU rows")
    return {"captured_at": _now(), "gpus": rows}


class GpuSampler:
    def __init__(self, path: Path, nvidia_smi: str, interval_seconds: float = 1.0) -> None:
        self.path = path
        self.nvidia_smi = nvidia_smi
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="tier-gpu-sampler", daemon=True)
        self.errors: list[str] = []

    def start(self) -> None:
        if self.interval_seconds <= 0:
            raise FlightError("GPU sample interval must be positive")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        baseline = _gpu_snapshot(self.nvidia_smi)
        self.path.write_bytes(_canonical(baseline))
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(5.0, self.interval_seconds * 4))
        if self.thread.is_alive():
            self.errors.append("GPU sampler did not stop")

    def _loop(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                snapshot = _gpu_snapshot(self.nvidia_smi)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(_canonical(snapshot).decode("utf-8"))
            except Exception as exc:
                self.errors.append(str(exc))


def _gpu_summary(
    path: Path,
    *,
    worker_gpu_uuid: str,
    utility_gpu_uuid: str | None,
    min_worker_delta_mib: float,
    max_utility_delta_mib: float,
    sampler_errors: list[str],
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                samples.append(value)
    by_uuid: dict[str, list[float]] = {}
    for sample in samples:
        for row in sample.get("gpus", []):
            if not isinstance(row, dict):
                continue
            gpu_uuid = row.get("uuid")
            memory = row.get("memory_used_mib")
            if isinstance(gpu_uuid, str) and isinstance(memory, (int, float)):
                by_uuid.setdefault(gpu_uuid, []).append(float(memory))

    def metrics(gpu_uuid: str | None) -> dict[str, Any] | None:
        if not gpu_uuid:
            return None
        values = by_uuid.get(gpu_uuid, [])
        if not values:
            return {"uuid": gpu_uuid, "samples": 0, "baseline_mib": None, "peak_mib": None, "peak_delta_mib": None}
        return {
            "uuid": gpu_uuid,
            "samples": len(values),
            "baseline_mib": values[0],
            "peak_mib": max(values),
            "peak_delta_mib": max(values) - values[0],
        }

    worker = metrics(worker_gpu_uuid)
    utility = metrics(utility_gpu_uuid)
    worker_ok = bool(
        worker
        and isinstance(worker.get("peak_delta_mib"), (int, float))
        and worker["peak_delta_mib"] >= min_worker_delta_mib
    )
    utility_ok = bool(
        utility is None
        or (
            isinstance(utility.get("peak_delta_mib"), (int, float))
            and utility["peak_delta_mib"] <= max_utility_delta_mib
        )
    )
    return {
        "sample_count": len(samples),
        "sampler_errors": sampler_errors,
        "worker": worker,
        "utility": utility,
        "min_worker_delta_mib": min_worker_delta_mib,
        "max_utility_delta_mib": max_utility_delta_mib,
        "worker_active": worker_ok,
        "utility_stable": utility_ok,
        "ok": bool(samples and not sampler_errors and worker_ok and utility_ok),
    }


def _unload_model(ollama_host: str, model: str) -> dict[str, Any]:
    try:
        response = _api_json(
            ollama_host,
            "/api/generate",
            method="POST",
            payload={"model": model, "keep_alive": 0, "stream": False},
            timeout=60.0,
        )
        return {"ok": True, "response": response}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _observation(
    *,
    task_id: str,
    model: dict[str, str],
    run_dir: Path,
    receipt: dict[str, Any] | None,
    verify_errors: list[str],
    invocation_error: str | None,
) -> dict[str, Any]:
    ledger = _read_json(run_dir / "ledger.jsonl")
    postflight = _read_json(run_dir / "ollama-postflight.json")
    receipt_path = run_dir / "receipt.json"
    patch_path = run_dir / "change.patch"
    return {
        "task_id": task_id,
        "task_title": TASKS[task_id]["title"],
        "arm": model["arm"],
        "model_id": model["model_id"],
        "model_digest": model["digest"],
        "state": receipt.get("state") if receipt else "INVOCATION_ERROR",
        "invocation_error": invocation_error,
        "verify_ok": not verify_errors,
        "verify_errors": verify_errors,
        "run_dir": str(run_dir),
        "receipt_sha256": _sha_file(receipt_path) if receipt_path.is_file() else None,
        "patch_sha256": _sha_file(patch_path) if patch_path.is_file() else None,
        "changed_files": (receipt or {}).get("changes", {}).get("files", []),
        "input_tokens": (ledger or {}).get("input_tokens"),
        "output_tokens": (ledger or {}).get("output_tokens"),
        "cache_read_tokens": (ledger or {}).get("cache_read_tokens"),
        "cache_write_tokens": (ledger or {}).get("cache_write_tokens"),
        "latency_ms": (ledger or {}).get("latency_ms"),
        "gpu_residency_ratio": (postflight or {}).get("metrics", {}).get("gpu_residency_ratio"),
        "context_length": (postflight or {}).get("metrics", {}).get("context_length"),
        "attestation_errors": (postflight or {}).get("attestation_errors", []),
    }


def _model_summary(observations: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
    rows = [row for row in observations if row["model_id"] == model_id]
    accepted = [row for row in rows if row["state"] == "ACCEPTED" and row["verify_ok"]]
    latencies = [
        float(row["latency_ms"])
        for row in rows
        if isinstance(row.get("latency_ms"), (int, float))
    ]
    output_tokens = sum(
        int(row["output_tokens"])
        for row in rows
        if isinstance(row.get("output_tokens"), int)
    )
    return {
        "model_id": model_id,
        "attempted": len(rows),
        "accepted_and_verified": len(accepted),
        "rejected": sum(row["state"] == "REJECTED" for row in rows),
        "errors": sum(row["state"] not in {"ACCEPTED", "REJECTED"} for row in rows),
        "success_rate": (len(accepted) / len(rows)) if rows else 0.0,
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "output_tokens": output_tokens,
    }


def run_flight(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.context_length <= 0:
        raise FlightError("context length must be positive")
    if not 0 <= args.min_gpu_residency <= 1:
        raise FlightError("minimum GPU residency must be between zero and one")
    if args.call_timeout_seconds <= 0:
        raise FlightError("call timeout must be positive")
    if args.sample_interval <= 0:
        raise FlightError("GPU sample interval must be positive")
    if args.min_worker_delta_mib < 0 or args.max_utility_delta_mib < 0:
        raise FlightError("GPU memory thresholds must be non-negative")
    attestation = _load_attestation(args.server_attestation)
    worker_gpu_uuid = args.worker_gpu_uuid or attestation.get("gpu_uuid")
    if not isinstance(worker_gpu_uuid, str) or not worker_gpu_uuid:
        raise FlightError("worker GPU UUID is required")
    if attestation.get("gpu_uuid") != worker_gpu_uuid:
        raise FlightError("worker GPU UUID contradicts server attestation")

    runtime = _probe_runtime(
        claude_bin=args.claude_bin,
        ollama_host=args.ollama_host,
        server_attestation=args.server_attestation,
        context_length=args.context_length,
    )
    if runtime["missing_models"]:
        commands = [f"ollama pull {model}" for model in runtime["missing_models"]]
        raise FlightError(
            "required models are missing from the dedicated server: "
            + ", ".join(runtime["missing_models"])
            + "; pull with "
            + " ; ".join(commands)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flight_id = f"local-coding-{args.profile}-{stamp}-{uuid.uuid4().hex[:8]}"
    root = args.output_root.resolve() / flight_id
    root.mkdir(parents=True, exist_ok=False)
    subject = root / "subject"
    manifest_path, subject_base = _create_fixture_repo(
        subject,
        runtime=runtime,
        claude_bin=args.claude_bin,
        server_attestation=args.server_attestation,
        context_length=args.context_length,
        min_gpu_residency=args.min_gpu_residency,
        call_timeout_seconds=args.call_timeout_seconds,
    )

    from .core import run_task, verify_run

    task_ids = PROFILE_TASKS[args.profile]
    observations: list[dict[str, Any]] = []
    unloads: list[dict[str, Any]] = []
    sampler = GpuSampler(root / "gpu-samples.jsonl", args.nvidia_smi, args.sample_interval)
    sampler.start()
    started_at = _now()
    try:
        for model in runtime["models"]:
            for task_id in task_ids:
                task = TASKS[task_id]
                run_dir = root / "runs" / _safe_slug(model["model_id"]) / task_id
                receipt: dict[str, Any] | None = None
                invocation_error: str | None = None
                verify_errors: list[str] = []
                try:
                    receipt = run_task(
                        repo=subject,
                        task_id=f"{task_id}-{_safe_slug(model['model_id'])}",
                        task=task["task"],
                        files=list(task["files"]),
                        acceptance=task["acceptance"],
                        manifest=manifest_path,
                        arm=model["arm"],
                        output_dir=run_dir,
                    )
                    verify_errors = verify_run(run_dir)
                except Exception as exc:
                    invocation_error = str(exc)
                observations.append(
                    _observation(
                        task_id=task_id,
                        model=model,
                        run_dir=run_dir,
                        receipt=receipt,
                        verify_errors=verify_errors,
                        invocation_error=invocation_error,
                    )
                )
            unloads.append(
                {"model_id": model["model_id"], **_unload_model(runtime["ollama_host"], model["model_id"])}
            )
    finally:
        sampler.stop()

    gpu = _gpu_summary(
        root / "gpu-samples.jsonl",
        worker_gpu_uuid=worker_gpu_uuid,
        utility_gpu_uuid=args.utility_gpu_uuid,
        min_worker_delta_mib=args.min_worker_delta_mib,
        max_utility_delta_mib=args.max_utility_delta_mib,
        sampler_errors=sampler.errors,
    )
    model_summaries = [
        _model_summary(observations, model["model_id"]) for model in runtime["models"]
    ]
    all_runs_accepted = bool(observations) and all(
        row["state"] == "ACCEPTED" and row["verify_ok"] for row in observations
    )
    all_runtime_attested = bool(observations) and all(
        isinstance(row.get("gpu_residency_ratio"), (int, float))
        and row["gpu_residency_ratio"] >= args.min_gpu_residency
        and row.get("context_length", 0) >= args.context_length
        and not row.get("attestation_errors")
        for row in observations
        if row["state"] == "ACCEPTED"
    )
    physical_qualification = bool(all_runs_accepted and all_runtime_attested and gpu["ok"])
    report = {
        "schema": REPORT_SCHEMA,
        "flight_id": flight_id,
        "profile": args.profile,
        "started_at": started_at,
        "completed_at": _now(),
        "runtime": {
            **runtime,
            "call_timeout_seconds": args.call_timeout_seconds,
        },
        "server_attestation": {
            "path": str(args.server_attestation.resolve()),
            "sha256": runtime["server_attestation_sha256"],
            "gpu_uuid": attestation.get("gpu_uuid"),
            "gpu_name": attestation.get("gpu_name"),
            "server_pid": attestation.get("server_pid"),
            "context_length": args.context_length,
        },
        "fixture": {
            "repo": str(subject),
            "base_commit": subject_base,
            "manifest": str(manifest_path),
            "manifest_sha256": _sha_file(manifest_path),
            "tasks": list(task_ids),
        },
        "observations": observations,
        "model_summaries": model_summaries,
        "unloads": unloads,
        "gpu": gpu,
        "qualification": {
            "all_runs_accepted_and_verified": all_runs_accepted,
            "all_accepted_runs_runtime_attested": all_runtime_attested,
            "physical_gpu_attestation": gpu["ok"],
            "physical_qualification": physical_qualification,
            "promotion_authorized": False,
            "promotion_note": (
                "This flight qualifies the executable path only. Routing promotion requires "
                "repeated repository-history or shadow-production evidence."
            ),
        },
    }
    report_path = root / "flight-report.json"
    report["report_path"] = str(report_path)
    report_path.write_bytes(_canonical(report))
    output = {**report, "report_sha256": _sha_file(report_path)}
    print(json.dumps(output, indent=2, sort_keys=True))
    return output, 0 if physical_qualification else 1


def freeze_backend(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    repo = Path(_git(args.repo.resolve(), "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    runtime = _probe_runtime(
        claude_bin=args.claude_bin,
        ollama_host=args.ollama_host,
        server_attestation=args.server_attestation,
        context_length=args.context_length,
    )
    if runtime["missing_models"]:
        raise FlightError("cannot freeze missing models: " + ", ".join(runtime["missing_models"]))
    destination = (repo / args.destination).resolve()
    try:
        destination.relative_to(repo)
    except ValueError as exc:
        raise FlightError("destination must stay inside the target repository") from exc
    prompt_path = destination / "hands.prompt.txt"
    manifest_path = destination / "pilot_backends.json"
    if not args.force and (prompt_path.exists() or manifest_path.exists()):
        raise FlightError("local coding backend files already exist; use --force to replace")
    destination.mkdir(parents=True, exist_ok=True)
    _write(prompt_path, PROMPT_TEMPLATE)
    protocol_commit = args.protocol_commit
    if protocol_commit is None:
        source_root = Path(__file__).resolve().parents[1]
        protocol_commit = _git(source_root, "rev-parse", "HEAD").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", protocol_commit):
        raise FlightError("protocol commit must be a full lowercase Git SHA")
    manifest = _manifest(
        protocol_commit=protocol_commit,
        prompt_rel="hands.prompt.txt",
        prompt_sha256=_sha_file(prompt_path),
        runtime=runtime,
        claude_bin=args.claude_bin,
        server_attestation=args.server_attestation,
        context_length=args.context_length,
        min_gpu_residency=args.min_gpu_residency,
        call_timeout_seconds=args.call_timeout_seconds,
    )
    manifest_path.write_bytes(_canonical(manifest))
    result = {
        "ok": True,
        "repo": str(repo),
        "prompt": str(prompt_path),
        "prompt_sha256": _sha_file(prompt_path),
        "manifest": str(manifest_path),
        "manifest_sha256": _sha_file(manifest_path),
        "protocol_commit": protocol_commit,
        "next_command": (
            "git add "
            + str(prompt_path.relative_to(repo)).replace("\\", "/")
            + " "
            + str(manifest_path.relative_to(repo)).replace("\\", "/")
            + " && git commit -m \"Freeze local coding backend\""
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result, 0


def probe(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    runtime = _probe_runtime(
        claude_bin=args.claude_bin,
        ollama_host=args.ollama_host,
        server_attestation=args.server_attestation,
        context_length=args.context_length,
    )
    runtime["ok"] = not runtime["missing_models"]
    runtime["pull_commands"] = [
        f"ollama pull {model}" for model in runtime["missing_models"]
    ]
    print(json.dumps(runtime, indent=2, sort_keys=True))
    return runtime, 0 if runtime["ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tiercode",
        description="Prepare and run sealed local coding flights on a GPU-pinned Ollama server",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--ollama-host", default="http://127.0.0.1:11439")
        target.add_argument("--server-attestation", type=Path, required=True)
        target.add_argument("--claude-bin", default="claude")
        target.add_argument("--context-length", type=int, default=32768)
        target.add_argument("--min-gpu-residency", type=float, default=0.95)
        target.add_argument("--call-timeout-seconds", type=float, default=900.0)

    probe_parser = sub.add_parser("probe", help="verify the frozen local tool and model surfaces")
    common(probe_parser)

    run_parser = sub.add_parser("run", help="run the hidden-graded three-model calibration flight")
    common(run_parser)
    run_parser.add_argument("--profile", choices=sorted(PROFILE_TASKS), default="smoke")
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--worker-gpu-uuid")
    run_parser.add_argument("--utility-gpu-uuid")
    run_parser.add_argument("--nvidia-smi", default="nvidia-smi")
    run_parser.add_argument("--sample-interval", type=float, default=1.0)
    run_parser.add_argument("--min-worker-delta-mib", type=float, default=4096.0)
    run_parser.add_argument("--max-utility-delta-mib", type=float, default=1536.0)

    freeze_parser = sub.add_parser(
        "freeze", help="write a target repository's committed local backend cartridge"
    )
    common(freeze_parser)
    freeze_parser.add_argument("--repo", type=Path, required=True)
    freeze_parser.add_argument(
        "--destination", type=Path, default=Path(".tier/local-coding")
    )
    freeze_parser.add_argument("--protocol-commit")
    freeze_parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "probe":
            return probe(args)[1]
        if args.command == "run":
            return run_flight(args)[1]
        if args.command == "freeze":
            return freeze_backend(args)[1]
    except (FlightError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiercode: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
