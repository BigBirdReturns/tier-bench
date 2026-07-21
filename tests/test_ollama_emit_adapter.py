from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.adapters.ollama_emit import AdapterError, _apply_emission, main  # noqa: E402


DIGEST = "a" * 64


class FakeOllama(BaseHTTPRequestHandler):
    emission = {"files": [{"path": "src/example.py", "content": "VALUE = 2"}]}

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"models": [{"name": "qwen-test", "digest": DIGEST}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        assert request["stream"] is False
        assert request["format"]["properties"]["files"]["minItems"] == 1
        body = json.dumps(
            {
                "model": "qwen-test",
                "created_at": "2026-07-20T00:00:00Z",
                "message": {"role": "assistant", "content": json.dumps(self.emission)},
                "prompt_eval_count": 123,
                "eval_count": 17,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_case(root: Path, base_url: str) -> int:
    work = root / "packet"
    (work / "src").mkdir(parents=True)
    (work / "src" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    dispatch = root / "dispatch.json"
    prompt = root / "prompt.txt"
    result = root / "backend-result.json"
    dispatch.write_text(
        json.dumps(
            {
                "task_id": "local-canary",
                "files": ["src/"],
                "backend_manifest_sha256": "b" * 64,
                "prompt_template_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    prompt.write_text("Change VALUE to 2.", encoding="utf-8")
    code = main(
        [
            "--arm", "arm_b",
            "--dispatch", str(dispatch),
            "--prompt", str(prompt),
            "--result", str(result),
            "--worktree", str(work),
            "--model", "qwen-test",
            "--model-digest", DIGEST,
            "--ollama-version", "test",
            "--base-url", base_url,
        ]
    )
    assert (work / "src" / "example.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    backend = json.loads(result.read_text(encoding="utf-8"))
    assert backend["schema"] == "tier-bench/tier-backend-result@1"
    assert backend["calls"][0]["extra"]["telemetry_complete"] is True
    assert backend["calls"][0]["input_tokens"] == 123
    assert {artifact["name"] for artifact in backend["artifacts"]} == {
        "provider_raw", "emission"
    }
    return code


def main_test() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assert run_case(root, f"http://127.0.0.1:{server.server_port}") == 0
            try:
                _apply_emission(
                    root / "packet",
                    ["src/"],
                    {"files": [{"path": "../escape.py", "content": "BAD = True\n"}]},
                )
            except AdapterError as exc:
                assert "unsafe emitted path" in str(exc)
            else:
                raise AssertionError("path traversal should fail closed")
            assert not (root / "escape.py").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("PASS - strict Ollama emission is scoped, receipted, telemetry-bound, and traversal-safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
