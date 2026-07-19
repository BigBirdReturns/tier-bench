#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / ".monster-wrangler-transfer"
ARCHIVE_DIR = TRANSFER / "archive"
EXPECTED_SHA256 = "cd55973f767ba12d0e664b264d90afd2703488d27a7aa6875ece1ce0f045e634"
EXPECTED_PATHS = {
    ".github/workflows/breadth-durability.yml",
    "docs/monster-wrangler.md",
    "pyproject.toml",
    "tests/test_monster_wrangler.py",
    "tier_runner/cli.py",
    "tier_runner/desk.py",
    "tier_runner/desk_ui.py",
}
TEMP_WORKFLOW = ROOT / ".github" / "workflows" / "monster-wrangler-assemble.yml"


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"monster-wrangler assembly refused: {message}")


def run(*argv: str) -> None:
    completed = subprocess.run(argv, cwd=ROOT, text=True)
    if completed.returncode:
        fail(f"command exited {completed.returncode}: {' '.join(argv)}")


def member_name(member: tarfile.TarInfo) -> str:
    raw = member.name.replace("\\", "/")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != raw:
        fail(f"unsafe archive path: {member.name!r}")
    return pure.as_posix()


def main() -> int:
    chunks = sorted(ARCHIVE_DIR.glob("*.b64"))
    if not chunks:
        fail("no archive chunks were found")
    expected_names = [f"{index:03d}.b64" for index in range(len(chunks))]
    if [path.name for path in chunks] != expected_names:
        fail("archive chunks are not a contiguous zero-based sequence")

    encoded = "".join(path.read_text(encoding="ascii").strip() for path in chunks)
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        fail(f"invalid base64 archive: {exc}")
    digest = hashlib.sha256(compressed).hexdigest()
    if digest != EXPECTED_SHA256:
        fail(f"archive sha256 mismatch: expected {EXPECTED_SHA256}, got {digest}")

    with tempfile.TemporaryDirectory(prefix="monster-wrangler-assemble-") as temp_raw:
        archive = Path(temp_raw) / "source.tar.xz"
        archive.write_bytes(compressed)
        with tarfile.open(archive, mode="r:xz") as handle:
            members = handle.getmembers()
            names = [member_name(member) for member in members]
            if len(names) != len(set(names)):
                fail("archive contains duplicate paths")
            if set(names) != EXPECTED_PATHS:
                missing = sorted(EXPECTED_PATHS - set(names))
                extra = sorted(set(names) - EXPECTED_PATHS)
                fail(f"archive path set mismatch; missing={missing}, extra={extra}")
            for member, name in zip(members, names):
                if not member.isfile():
                    fail(f"archive member is not a regular file: {name}")
                source = handle.extractfile(member)
                if source is None:
                    fail(f"archive member has no readable bytes: {name}")
                target = ROOT.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())

    run(sys.executable, "-m", "py_compile", "tier_runner/desk.py", "tier_runner/desk_ui.py", "tier_runner/cli.py", "tests/test_monster_wrangler.py")
    run(sys.executable, "tests/test_monster_wrangler.py")

    html = (ROOT / "tier_runner" / "desk_ui.py").read_text(encoding="utf-8")
    start = html.find("<script>")
    end = html.rfind("</script>")
    if start < 0 or end <= start:
        fail("could not locate the embedded browser script")
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(html[start + len("<script>"):end])
            js_path = Path(handle.name)
        try:
            run(node, "--check", str(js_path))
        finally:
            js_path.unlink(missing_ok=True)

    shutil.rmtree(TRANSFER)
    TEMP_WORKFLOW.unlink(missing_ok=True)
    print(f"Monster Wrangler source assembled and verified: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
