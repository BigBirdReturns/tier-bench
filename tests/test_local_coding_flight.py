#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tier_runner.adapters.claude_code_ollama import (  # noqa: E402
    ADAPTER_VERSION,
    _adapter_source_sha256,
    BLOCKED_ENV_KEYS,
    CLAUDE_TOOLS,
    REQUIRED_CLAUDE_FLAGS,
    _help_surface,
    _local_env,
    _loopback_base_url,
    _model_digest,
    _run_claude,
    _packet_permission_args,
    _running_attestation,
    _select_model,
    _server_attestation,
    main as adapter_main,
)
from tier_runner.local_coding_flight import (  # noqa: E402
    FIXTURE_FILES,
    MODEL_SUITE,
    PROMPT_TEMPLATE,
    _canonical,
    _create_fixture_repo,
    _gpu_summary,
    _manifest,
    _sha_file,
)


MODEL = "gpt-oss:20b"
DIGEST = "a" * 64
OLLAMA_VERSION = "0.99.0-test"
CLAUDE_VERSION = "claude-fake 1.0"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _server_attestation_file(parent: Path, base_url: str, context: int = 32768) -> Path:
    path = parent / "server-attestation.json"
    payload = {
        "schema": "tier-bench/ollama-server-attestation@1",
        "captured_at": "2026-07-27T00:00:00Z",
        "ollama_host": base_url,
        "ollama_version": OLLAMA_VERSION,
        "server_pid": 12345,
        "executable_path": "C:/Program Files/Ollama/ollama.exe",
        "executable_sha256": "b" * 64,
        "gpu_uuid": "GPU-11111111-2222-3333-4444-555555555555",
        "gpu_name": "NVIDIA GeForce RTX 3090",
        "gpu_memory_total_mib": 24576,
        "context_length": context,
        "launch_environment": {
            "CUDA_VISIBLE_DEVICES": "GPU-11111111-2222-3333-4444-555555555555",
            "OLLAMA_CONTEXT_LENGTH": str(context),
            "OLLAMA_HOST": base_url.removeprefix("http://"),
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_NUM_PARALLEL": "1",
        },
    }
    path.write_bytes(_canonical(payload))
    return path


def test_json_schemas_bind_report_and_attestation_authority(parent: Path) -> None:
    del parent
    report = json.loads(
        (REPO / "schemas" / "local_coding_flight_report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    attestation = json.loads(
        (REPO / "schemas" / "ollama_server_attestation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["properties"]["schema"]["const"] == (
        "tier-bench/local-coding-flight-report@1"
    )
    assert attestation["properties"]["schema"]["const"] == (
        "tier-bench/ollama-server-attestation@1"
    )
    assert report["properties"]["qualification"]["properties"][
        "promotion_authorized"
    ]["const"] is False


def test_loopback_and_environment_fail_closed(parent: Path) -> None:
    del parent
    assert _loopback_base_url("http://127.0.0.1:11439") == "http://127.0.0.1:11439"
    assert _loopback_base_url("http://[::1]:11439") == "http://[::1]:11439"
    for value in (
        "https://127.0.0.1:11439",
        "http://localhost:11439",
        "http://192.168.1.10:11439",
        "http://127.0.0.1",
        "http://127.0.0.1:11439/api",
        "http://user:pass@127.0.0.1:11439",
    ):
        try:
            _loopback_base_url(value)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"unsafe Ollama endpoint was accepted: {value}")

    source = {
        "PATH": "kept",
        "SystemRoot": "kept",
        "ANTHROPIC_API_KEY": "cloud-secret",
        "ANTHROPIC_BASE_URL": "https://example.invalid",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription-secret",
        "CLAUDE_CODE_SESSION_ID": "parent-session",
        "AWS_ACCESS_KEY_ID": "cloud-secret",
        "HTTP_PROXY": "http://proxy.invalid",
        "TIER_RUN_DIR": "must-not-leak",
    }
    clean = _local_env(source, "http://127.0.0.1:11439")
    assert clean["PATH"] == "kept"
    assert clean["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert clean["ANTHROPIC_API_KEY"] == ""
    assert clean["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:11439"
    assert clean["NO_PROXY"] == "127.0.0.1,::1,localhost"
    assert not any(key in clean for key in BLOCKED_ENV_KEYS - {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"})
    assert "AWS_ACCESS_KEY_ID" not in clean
    assert "HTTP_PROXY" not in clean
    assert "TIER_RUN_DIR" not in clean


def test_model_and_runtime_attestation(parent: Path) -> None:
    del parent
    tags = {
        "models": [
            {"name": "gpt-oss:20b", "model": "gpt-oss:20b", "digest": DIGEST}
        ]
    }
    selected = _select_model(tags, MODEL, "tags")
    assert _model_digest(selected) == DIGEST
    hostile = {"models": [{"name": [MODEL], "model": {"bad": True}}]}
    try:
        _select_model(hostile, MODEL, "tags")
    except RuntimeError as exc:
        assert "no exact model" in str(exc)
    else:
        raise AssertionError("non-string model identity was accepted")
    metrics = _running_attestation(
        {"size": 1000, "size_vram": 980, "context_length": 32768},
        expected_context=32768,
        min_gpu_residency=0.95,
    )
    assert metrics["gpu_residency_ratio"] == 0.98
    for row, message in (
        ({"size": 1000, "size_vram": 900, "context_length": 32768}, "resident"),
        ({"size": 1000, "size_vram": 1000, "context_length": 16384}, "context"),
    ):
        try:
            _running_attestation(row, expected_context=32768, min_gpu_residency=0.95)
        except RuntimeError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid runtime attestation was accepted")


def test_server_attestation_is_hash_and_launch_bound(parent: Path) -> None:
    base = "http://127.0.0.1:11439"
    path = _server_attestation_file(parent, base)
    digest = _sha_file(path)
    value = _server_attestation(
        path,
        digest,
        ollama_host=base,
        ollama_version=OLLAMA_VERSION,
        context_length=32768,
    )
    assert value["gpu_name"].endswith("RTX 3090")
    raw = path.read_bytes()
    path.write_bytes(raw + b" ")
    try:
        _server_attestation(
            path,
            digest,
            ollama_host=base,
            ollama_version=OLLAMA_VERSION,
            context_length=32768,
        )
    except RuntimeError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered server attestation was accepted")


def test_manifest_binds_models_tools_packet_and_server(parent: Path) -> None:
    base = "http://127.0.0.1:11439"
    attestation = _server_attestation_file(parent, base)
    runtime = {
        "claude_version": CLAUDE_VERSION,
        "claude_help_sha256": "c" * 64,
        "ollama_version": OLLAMA_VERSION,
        "ollama_host": base,
        "server_attestation_sha256": _sha_file(attestation),
        "models": [
            {"arm": arm, "model_id": model, "effort": effort, "digest": chr(97 + index) * 64}
            for index, (arm, model, effort) in enumerate(MODEL_SUITE)
        ],
    }
    manifest = _manifest(
        protocol_commit="f" * 40,
        prompt_rel="hands.prompt.txt",
        prompt_sha256="d" * 64,
        runtime=runtime,
        claude_bin="claude",
        server_attestation=attestation,
        context_length=32768,
        min_gpu_residency=0.95,
    )
    assert set(manifest["arms"]) == {"arm_a", "arm_b", "arm_c"}
    assert manifest["tool_versions"]["ollama_server_attestation_sha256"] == _sha_file(attestation)
    assert manifest["tool_versions"]["tier_claude_ollama_adapter_sha256"] == _adapter_source_sha256()
    for arm, backend in manifest["arms"].items():
        command = backend["adapter"]["command"]
        assert "{dispatch_receipt}" in command
        assert "{backend_result}" in command
        assert "{worktree}" in command
        assert "--server-attestation-sha256" in command
        assert "--adapter-source-sha256" in command
        assert "--call-timeout-seconds" in command
        assert command[command.index("--model") + 1] == backend["model_id"]
        assert command[command.index("--arm") + 1] == "{arm}"
        assert backend["surface"] == "ollama-claude-code-local"
        assert backend["cost_basis"] == "shadow-estimated"


def _solution_files() -> dict[str, str]:
    return {
        "src/ports.py": '''from __future__ import annotations\n\n\ndef parse_port(value: object) -> int:\n    if isinstance(value, bool):\n        raise ValueError("invalid port")\n    if isinstance(value, int):\n        port = value\n    elif isinstance(value, str):\n        text = value.strip()\n        if not text or not text.isascii() or not text.isdecimal():\n            raise ValueError("invalid port")\n        port = int(text)\n    else:\n        raise ValueError("invalid port")\n    if not 1 <= port <= 65535:\n        raise ValueError("invalid port")\n    return port\n''',
        "src/records.py": '''from __future__ import annotations\n\nimport csv\nimport io\n\n\nclass RecordFormatError(ValueError):\n    pass\n\n\ndef parse_records(text: str) -> list[dict[str, str]]:\n    if not text:\n        return []\n    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))\n    if not rows:\n        return []\n    header = rows[0]\n    if len(header) != len(set(header)):\n        raise RecordFormatError("duplicate header")\n    result = []\n    for row in rows[1:]:\n        if len(row) != len(header):\n            raise RecordFormatError("wrong field count")\n        result.append(dict(zip(header, row)))\n    return result\n''',
        "src/cache.py": '''from __future__ import annotations\n\nimport hashlib\nimport json\nfrom typing import Any\n\nfrom .identity import CACHE_KEY_SCHEMA\n\n\ndef action_cache_key(action: str, inputs: Any, environment: Any) -> str:\n    payload = {\n        "schema": CACHE_KEY_SCHEMA,\n        "action": action,\n        "inputs": inputs,\n        "environment": environment,\n    }\n    raw = json.dumps(\n        payload, sort_keys=True, separators=(",", ":"), allow_nan=False\n    ).encode("utf-8")\n    return hashlib.sha256(raw).hexdigest()\n''',
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
            cursor = index + 1
            negate = cursor < len(pattern) and pattern[cursor] == "!"
            if negate:
                cursor += 1
            chars: list[str] = []
            while cursor < len(pattern):
                current = pattern[cursor]
                if current == "]":
                    break
                if current == "\\":
                    cursor += 1
                    if cursor >= len(pattern):
                        raise GlobSyntaxError("dangling class escape")
                    current = pattern[cursor]
                chars.append(re.escape(current))
                cursor += 1
            if cursor >= len(pattern) or pattern[cursor] != "]":
                raise GlobSyntaxError("unclosed character class")
            pieces.append("[" + ("^" if negate else "") + "".join(chars) + "]")
            index = cursor
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
    }


def test_fixture_is_hidden_graded_and_solvable(parent: Path) -> None:
    fixture = parent / "fixture"
    fixture.mkdir()
    for relative, content in FIXTURE_FILES.items():
        _write(fixture / relative, content)
    failures = 0
    for module in ("tests.test_ports", "tests.test_records", "tests.test_cache", "tests.test_globs"):
        result = subprocess.run(
            [sys.executable, "-m", "unittest", module, "-v"],
            cwd=fixture,
            capture_output=True,
            text=True,
        )
        failures += result.returncode != 0
    assert failures == 4
    for relative, content in _solution_files().items():
        _write(fixture / relative, content)
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=fixture,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fixture_repo_freezes_prompt_manifest_and_hidden_tests(parent: Path) -> None:
    base = "http://127.0.0.1:11439"
    attestation = _server_attestation_file(parent, base)
    runtime = {
        "claude_version": CLAUDE_VERSION,
        "claude_help_sha256": "c" * 64,
        "ollama_version": OLLAMA_VERSION,
        "ollama_host": base,
        "server_attestation_sha256": _sha_file(attestation),
        "models": [
            {"arm": arm, "model_id": model, "effort": effort, "digest": chr(97 + index) * 64}
            for index, (arm, model, effort) in enumerate(MODEL_SUITE)
        ],
    }
    manifest_path, head = _create_fixture_repo(
        parent / "subject",
        runtime=runtime,
        claude_bin="claude",
        server_attestation=attestation,
        context_length=32768,
        min_gpu_residency=0.95,
    )
    assert len(head) == 40
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompt = manifest_path.with_name("hands.prompt.txt")
    assert prompt.read_text(encoding="utf-8") == PROMPT_TEMPLATE
    assert manifest["prompt_templates"]["hands"]["sha256"] == _sha_file(prompt)
    assert (parent / "subject" / "tests" / "test_ports.py").is_file()
    assert (parent / "subject" / "AGENTS.md").is_file()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=parent / "subject",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""


def test_gpu_summary_requires_worker_load_and_utility_stability(parent: Path) -> None:
    worker = "GPU-worker"
    utility = "GPU-utility"
    path = parent / "gpu.jsonl"
    samples = [
        {"captured_at": "a", "gpus": [
            {"uuid": worker, "memory_used_mib": 500.0},
            {"uuid": utility, "memory_used_mib": 1000.0},
        ]},
        {"captured_at": "b", "gpus": [
            {"uuid": worker, "memory_used_mib": 15000.0},
            {"uuid": utility, "memory_used_mib": 1200.0},
        ]},
    ]
    path.write_bytes(b"".join(_canonical(sample) for sample in samples))
    summary = _gpu_summary(
        path,
        worker_gpu_uuid=worker,
        utility_gpu_uuid=utility,
        min_worker_delta_mib=4096,
        max_utility_delta_mib=1536,
        sampler_errors=[],
    )
    assert summary["ok"] is True
    assert summary["worker"]["peak_delta_mib"] == 14500.0
    assert summary["utility"]["peak_delta_mib"] == 200.0


def test_claude_process_timeout_is_bounded(parent: Path) -> None:
    sleeper = parent / "sleeper.py"
    sleeper.write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    started = __import__("time").monotonic()
    returncode, stdout, stderr, timed_out = _run_claude(
        [sys.executable, str(sleeper)],
        cwd=parent,
        prompt="ignored",
        environment=dict(os.environ),
        timeout_seconds=0.2,
    )
    elapsed = __import__("time").monotonic() - started
    assert returncode == 124
    assert timed_out is True
    assert stdout == ""
    assert stderr == ""
    assert elapsed < 10


class _FakeOllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        if self.path == "/api/version":
            payload = {"version": OLLAMA_VERSION}
        elif self.path == "/api/tags":
            payload = {"models": [{
                "name": MODEL,
                "model": MODEL,
                "digest": DIGEST,
                "size": 1000,
                "details": {"quantization_level": "MXFP4"},
            }]}
        elif self.path == "/api/ps":
            payload = {"models": [{
                "name": MODEL,
                "model": MODEL,
                "digest": DIGEST,
                "size": 1000,
                "size_vram": 1000,
                "context_length": 32768,
                "details": {"quantization_level": "MXFP4"},
            }]}
        else:
            self.send_error(404)
            return
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_adapter_emits_bound_local_receipt(parent: Path) -> None:
    if os.name == "nt":
        return
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        attestation = _server_attestation_file(parent, base)
        fake = parent / "fake-claude"
        flags = " ".join(sorted(REQUIRED_CLAUDE_FLAGS))
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            f"VERSION = {CLAUDE_VERSION!r}\n"
            f"HELP = {flags!r}\n"
            "if '--version' in sys.argv:\n"
            "    print(VERSION)\n"
            "    raise SystemExit(0)\n"
            "if '--help' in sys.argv:\n"
            "    print(HELP)\n"
            "    raise SystemExit(0)\n"
            "model = sys.argv[sys.argv.index('--model') + 1]\n"
            "pathlib.Path('child-env.json').write_text(json.dumps(dict(os.environ), sort_keys=True))\n"
            "print(json.dumps({\n"
            "  'session_id': 'fresh-local-session',\n"
            "  'modelUsage': {model: {}},\n"
            "  'usage': {\n"
            "    'input_tokens': 11, 'output_tokens': 7,\n"
            "    'cache_read_input_tokens': 5, 'cache_creation_input_tokens': 3\n"
            "  },\n"
            "  'total_cost_usd': 0\n"
            "}))\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        help_hash = _help_surface(str(fake))
        packet = parent / "packet"
        packet.mkdir()
        _write(packet / "app.py", "value = 1\n")
        dispatch = parent / "dispatch.json"
        dispatch.write_bytes(_canonical({
            "task_id": "local-adapter-test",
            "files": ["app.py"],
            "backend_manifest_sha256": "b" * 64,
            "prompt_template_sha256": "c" * 64,
        }))
        prompt = parent / "prompt.txt"
        _write(prompt, "repair app.py\n")
        result = parent / "backend-result.json"
        old = dict(os.environ)
        os.environ.update({
            "ANTHROPIC_API_KEY": "must-not-leak",
            "CLAUDE_CODE_OAUTH_TOKEN": "must-not-leak",
            "AWS_ACCESS_KEY_ID": "must-not-leak",
            "TIER_RUN_DIR": "must-not-leak",
        })
        try:
            rc = adapter_main([
                "--arm", "arm_a",
                "--dispatch", str(dispatch),
                "--prompt", str(prompt),
                "--result", str(result),
                "--worktree", str(packet),
                "--claude-bin", str(fake),
                "--claude-version", CLAUDE_VERSION,
                "--claude-help-sha256", help_hash,
                "--adapter-version", ADAPTER_VERSION,
                "--adapter-source-sha256", _adapter_source_sha256(),
                "--model", MODEL,
                "--effort", "medium",
                "--account", "local-3090",
                "--ollama-host", base,
                "--ollama-version", OLLAMA_VERSION,
                "--ollama-model-digest", DIGEST,
                "--context-length", "32768",
                "--min-gpu-residency", "0.95",
                "--server-attestation", str(attestation),
                "--server-attestation-sha256", _sha_file(attestation),
                "--call-timeout-seconds", "5",
            ])
        finally:
            os.environ.clear()
            os.environ.update(old)
        assert rc == 0
        backend = json.loads(result.read_text(encoding="utf-8"))
        call = backend["calls"][0]
        assert call["outcome"] == "pass"
        assert call["extra"]["telemetry_complete"] is True
        assert call["extra"]["runtime_model_id"] == MODEL
        assert call["extra"]["ollama_gpu_residency_ratio"] == 1.0
        assert call["extra"]["ollama_context_length"] == 32768
        assert set(CLAUDE_TOOLS.split(",")) == {"Read", "Edit", "Write", "Glob", "Grep"}
        env = json.loads((packet / "child-env.json").read_text(encoding="utf-8"))
        assert env["ANTHROPIC_BASE_URL"] == base
        assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert "AWS_ACCESS_KEY_ID" not in env
        assert "TIER_RUN_DIR" not in env
        names = {artifact["name"] for artifact in backend["artifacts"]}
        assert names == {
            "provider_raw",
            "provider_stderr",
            "ollama_preflight",
            "ollama_postflight",
            "ollama_server_attestation",
        }
        permissions = _packet_permission_args(packet, ["app.py"])
        assert permissions[:3] == ["--permission-mode", "dontAsk", "--allowedTools"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="tier-local-coding-flight-"))
    tests = [
        test_json_schemas_bind_report_and_attestation_authority,
        test_loopback_and_environment_fail_closed,
        test_model_and_runtime_attestation,
        test_server_attestation_is_hash_and_launch_bound,
        test_manifest_binds_models_tools_packet_and_server,
        test_fixture_is_hidden_graded_and_solvable,
        test_fixture_repo_freezes_prompt_manifest_and_hidden_tests,
        test_gpu_summary_requires_worker_load_and_utility_stability,
        test_claude_process_timeout_is_bounded,
        test_adapter_emits_bound_local_receipt,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(
            f"OK: {len(tests)}/{len(tests)} local-coding-flight tests passed; "
            "zero real model calls"
        )
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
