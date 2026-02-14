from __future__ import annotations

import os
import shutil
import sys

def main() -> int:
    problems: list[str] = []

    if sys.version_info < (3, 10):
        problems.append("Python 3.10+ required")

    if shutil.which("git") is None:
        problems.append("git not found on PATH")

    if shutil.which("ruff") is None:
        problems.append("ruff not found. Install with: python -m pip install ruff")

    # At least one provider key must exist for actual runs.
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")):
        problems.append("No provider API key found (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY).")

    if problems:
        print("PRECHECK FAILED")
        for p in problems:
            print(f"- {p}")
        return 1

    print("PRECHECK OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
