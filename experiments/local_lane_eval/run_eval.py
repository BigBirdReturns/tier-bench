#!/usr/bin/env python3
"""Evaluate a local Ollama model against schema-constrained extraction tasks."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate local Ollama model on schema-constrained extraction"
    )
    parser.add_argument("--model", required=True, help="Ollama model tag (e.g., qwen3.5:9b)")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:11434",
        help="Ollama base URL"
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).parent / "cases.json",
        help="Path to cases.json"
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output results JSON file (optional)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Request timeout in seconds"
    )
    args = parser.parse_args(argv)
    args.base_url = args.base_url.rstrip("/")
    args.cases = args.cases.resolve()
    if args.out:
        args.out = args.out.resolve()
    return args


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load and validate test cases."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load cases from {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise RuntimeError("Cases must be a JSON array")
    for case in raw:
        if not isinstance(case, dict):
            raise RuntimeError("Each case must be an object")
        required = {"id", "prompt", "schema", "expect"}
        if not required.issubset(set(case)):
            raise RuntimeError(f"Case {case.get('id')} missing required fields: {required}")
    return raw


def post_chat(
    base_url: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    timeout: float,
) -> tuple[dict[str, Any], float]:
    """POST to Ollama /api/chat endpoint and return response + latency."""
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": prompt}],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    latency_ms = (time.monotonic() - start) * 1000
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc
    return result, latency_ms


def extract_content(response: dict[str, Any]) -> str | None:
    """Extract assistant content from Ollama response."""
    message = response.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def exact_match(parsed: Any, expected: Any) -> bool:
    """Check if parsed exactly matches expected (order-insensitive for dicts)."""
    if type(parsed) != type(expected):
        return False
    if isinstance(parsed, dict):
        if set(parsed.keys()) != set(expected.keys()):
            return False
        return all(exact_match(parsed[k], expected[k]) for k in parsed)
    if isinstance(parsed, list):
        if len(parsed) != len(expected):
            return False
        return all(exact_match(p, e) for p, e in zip(parsed, expected))
    return parsed == expected


def grade_case(
    case: dict[str, Any],
    response: dict[str, Any],
    latency_ms: float,
) -> dict[str, Any]:
    """Grade a single case and return result object."""
    case_id = case["id"]
    expect = case["expect"]
    prompt_eval = response.get("prompt_eval_count", 0)
    eval_count = response.get("eval_count", 0)

    content = extract_content(response)
    if content is None:
        return {
            "id": case_id,
            "ok": False,
            "error": "No content in response",
            "parsed": None,
            "prompt_eval_count": prompt_eval,
            "eval_count": eval_count,
            "latency_ms": latency_ms,
        }

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return {
            "id": case_id,
            "ok": False,
            "error": f"JSON parse error: {exc}",
            "parsed": None,
            "prompt_eval_count": prompt_eval,
            "eval_count": eval_count,
            "latency_ms": latency_ms,
        }

    ok = exact_match(parsed, expect)
    result = {
        "id": case_id,
        "ok": ok,
        "parsed": parsed,
        "prompt_eval_count": prompt_eval,
        "eval_count": eval_count,
        "latency_ms": latency_ms,
    }
    if not ok:
        result["expected"] = expect
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        cases = load_cases(args.cases)
    except RuntimeError as exc:
        print(f"Error loading cases: {exc}", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    passed = 0
    latencies: list[float] = []
    total_prompt_tokens = 0
    total_eval_tokens = 0

    for case in cases:
        case_id = case["id"]
        prompt = case["prompt"]
        schema = case["schema"]

        try:
            response, latency_ms = post_chat(
                args.base_url,
                args.model,
                prompt,
                schema,
                args.timeout,
            )
        except RuntimeError as exc:
            print(f"{case_id}: TRANSPORT FAILURE", file=sys.stderr)
            print(f"Error: {exc}", file=sys.stderr)
            return 2

        result = grade_case(case, response, latency_ms)
        results.append(result)

        status = "ok" if result["ok"] else "FAIL"
        print(f"{case_id}: {status}")

        if result["ok"]:
            passed += 1

        latencies.append(latency_ms)
        total_prompt_tokens += result.get("prompt_eval_count", 0)
        total_eval_tokens += result.get("eval_count", 0)

    print()
    median_latency_ms = statistics.median(latencies) if latencies else 0
    total_tokens = total_prompt_tokens + total_eval_tokens

    print(f"SCORE {passed}/{len(cases)}")
    print(f"Median latency: {median_latency_ms:.1f}ms")
    print(f"Total tokens: {total_tokens} (prompt: {total_prompt_tokens}, output: {total_eval_tokens})")

    if args.out:
        output = {
            "model": args.model,
            "base_url": args.base_url,
            "cases_file": str(args.cases),
            "score": passed,
            "total": len(cases),
            "passed": passed == len(cases),
            "median_latency_ms": median_latency_ms,
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "output_tokens": total_eval_tokens,
            "results": results,
        }
        try:
            args.out.write_text(
                json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"Warning: Failed to write results to {args.out}: {exc}", file=sys.stderr)

    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"run_eval: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
