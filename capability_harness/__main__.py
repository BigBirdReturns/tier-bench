"""CLI: lift a cheap model's review to the tier above.

    # Anthropic
    python -m capability_harness review mycode.py --model claude-haiku-4-5

    # any OpenAI-compatible endpoint (OpenAI, Together, Groq, OpenRouter, vLLM, Ollama)
    python -m capability_harness review mycode.py --backend openai --model gpt-4.1-mini
    python -m capability_harness review mycode.py --backend openai \
        --model llama3.1 --base-url http://localhost:11434/v1

    # no key, wiring smoke test
    python -m capability_harness review mycode.py --backend echo
"""
import argparse
import sys

from .backends import anthropic_backend, echo_backend, openai_backend
from .uplift import review


def _make_call(a):
    if a.backend == "echo":
        return echo_backend()
    if a.backend == "anthropic":
        return anthropic_backend(a.model, max_tokens=a.max_tokens)
    if a.backend == "openai":
        return openai_backend(a.model, base_url=a.base_url, max_tokens=a.max_tokens)
    raise SystemExit(f"unknown backend: {a.backend}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="capability_harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="multi-lens review sweep of a file")
    r.add_argument("path", help="file to review")
    r.add_argument("--model", default="claude-haiku-4-5")
    r.add_argument("--backend", default="anthropic", choices=["anthropic", "openai", "echo"])
    r.add_argument("--base-url", default=None, help="for OpenAI-compatible hosts")
    r.add_argument("--max-tokens", type=int, default=2000)
    a = ap.parse_args(argv)

    target = open(a.path, encoding="utf-8").read()
    call = _make_call(a)
    res = review(target, call)
    print(f"# capability_harness review — {a.path}")
    print(f"# {res.calls} lens passes, model={a.model}, backend={a.backend}\n")
    print(res.merged_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
