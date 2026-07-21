from __future__ import annotations

import argparse
import difflib
from pathlib import Path, PurePosixPath
import subprocess


class AcceptanceError(RuntimeError):
    pass


def verify_insertion(path: str, max_added_lines: int, repo: Path | None = None) -> int:
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise AcceptanceError("acceptance path must stay inside the repository")
    root = (repo or Path.cwd()).resolve()
    candidate = root.joinpath(*pure.parts)
    if not candidate.is_file():
        raise AcceptanceError(f"candidate file is missing: {pure.as_posix()}")
    base = subprocess.run(
        ["git", "show", f"HEAD:{pure.as_posix()}"],
        cwd=root,
        capture_output=True,
    )
    if base.returncode:
        raise AcceptanceError(f"base file is not committed at HEAD: {pure.as_posix()}")
    before = base.stdout.decode("utf-8").splitlines(keepends=True)
    after = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
    added = 0
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
        None, before, after, autojunk=False
    ).get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag != "equal":
            raise AcceptanceError("candidate changed or removed existing lines")
    if added < 1 or added > max_added_lines:
        raise AcceptanceError(
            f"candidate added {added} lines; expected 1 to {max_added_lines}"
        )
    print(
        f"PASS - {pure.as_posix()} preserves every existing line and adds {added} line(s)"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Deterministic intent-shaped acceptance checks")
    commands = result.add_subparsers(dest="command", required=True)
    insertion = commands.add_parser("insertion")
    insertion.add_argument("--path", required=True)
    insertion.add_argument("--max-added-lines", type=int, default=1)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "insertion":
        if args.max_added_lines < 1:
            raise AcceptanceError("max-added-lines must be positive")
        return verify_insertion(args.path, args.max_added_lines)
    raise AcceptanceError(f"unknown acceptance command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AcceptanceError, OSError, UnicodeDecodeError) as exc:
        print(f"tier intent acceptance: {exc}")
        raise SystemExit(1)
