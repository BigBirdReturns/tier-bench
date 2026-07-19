#!/usr/bin/env python3
"""Create a breadth crate scaffold."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


INDEX_NAME = "000.000.INDEX.md"
TASK_NAME = "010.100.TASK.md"
ACCEPTANCE_NAME = "020.100.ACCEPTANCE.md"


def build_index(name: str) -> str:
    return f"""# 000.000 Crate index — {name}

Read [010.100.TASK.md](010.100.TASK.md) then [020.100.ACCEPTANCE.md](020.100.ACCEPTANCE.md).

- You may create/edit ONLY: `<ALLOWED_FILE>`
- You may RUN (never edit): `<REFEREE_CMD>`
- Do NOT modify tests/, this crate dir, or git state.
- Iterate until acceptance passes. Reply: DONE + last line of its output.
"""


def build_task(name: str) -> str:
    return f"""# 010.100 Task — {name}

<SPEC>
"""


def build_acceptance() -> str:
    return """# 020.100 Acceptance

<REFEREE_CMD>
Driver-authored, frozen. If it seems wrong, it is not: match [010.100](010.100.TASK.md) exactly.
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=False)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--list", action="store_true", help="List existing crates in --dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.list:
        root = Path(args.dir).resolve()
        if root.exists() and root.is_dir():
            for item in sorted(root.iterdir()):
                if item.is_dir():
                    print(item.name)
        return 0

    if args.name is None:
        print("error: --name is required", file=sys.stderr)
        return 1

    root = Path(args.dir).resolve()
    crate_dir = root / args.name

    if crate_dir.exists():
        print(f"exists: {crate_dir}")
        return 1

    try:
        crate_dir.mkdir(parents=True, exist_ok=False)
        files = {
            crate_dir / INDEX_NAME: build_index(args.name),
            crate_dir / TASK_NAME: build_task(args.name),
            crate_dir / ACCEPTANCE_NAME: build_acceptance(),
        }
        for path, content in files.items():
            path.write_text(content, encoding="utf-8")
    except OSError:
        return 1

    print(f"created: {crate_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
