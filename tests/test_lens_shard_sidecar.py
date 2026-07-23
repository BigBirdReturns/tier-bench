#!/usr/bin/env python3
"""Witnesses for CLAUDE-LENS-SHARD-WIN: sidecar verification is cross-platform
portable AND still fails closed on genuine tamper.

Covers the two Windows failure modes found 2026-07-19:
  1. path-separator mismatch (POSIX sidecar keys vs Windows relative_to)
  2. autocrlf CRLF rewrite of sealed LF bytes (must STILL raise — diagnosed,
     never accepted)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from capability_harness.lens_shard import check_sidecar, sidecar_path, write_sidecar  # noqa: E402


def build_shard(root: Path) -> Path:
    shard = root / "shard"
    (shard / "content").mkdir(parents=True)
    (shard / "sig").mkdir()
    (shard / "content" / "source.txt").write_bytes(b"[lens demo]\ninstruction: look\n")
    (shard / "manifest.json").write_bytes(b'{"v":1}')
    (shard / "sig" / "manifest.sig").write_bytes(b"\x00\x01binary\x02")
    return shard


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        shard = build_shard(Path(td))
        write_sidecar(shard)

        # 1. round-trip passes
        assert check_sidecar(shard) is True, "fresh sidecar must verify"

        # 2. sidecar keys are canonical POSIX on every host
        text = sidecar_path(shard).read_text(encoding="utf-8")
        assert "\\" not in text, f"sidecar keys must use '/', got: {text!r}"
        assert "content/source.txt" in text

        # 3. legacy sidecar with backslash keys (written by the pre-fix code on
        #    Windows) still verifies after key normalization
        sidecar_path(shard).write_text(
            text.replace("content/source.txt", "content\\source.txt")
                .replace("sig/manifest.sig", "sig\\manifest.sig"),
            encoding="utf-8")
        assert check_sidecar(shard) is True, "legacy backslash sidecar must verify"
        write_sidecar(shard)  # restore canonical form

        # 4. CRLF rewrite fails closed AND is diagnosed as autocrlf, not tamper
        src = shard / "content" / "source.txt"
        sealed = src.read_bytes()
        src.write_bytes(sealed.replace(b"\n", b"\r\n"))
        try:
            check_sidecar(shard)
            raise AssertionError("CRLF-rewritten shard must NOT verify")
        except ValueError as e:
            assert "autocrlf" in str(e), f"CRLF drift should be diagnosed: {e}"
        src.write_bytes(sealed)

        # 5. genuine single-byte tamper fails closed, with NO autocrlf excuse
        assert check_sidecar(shard) is True
        (shard / "manifest.json").write_bytes(b'{"v":2}')
        try:
            check_sidecar(shard)
            raise AssertionError("tampered shard must NOT verify")
        except ValueError as e:
            assert "manifest.json" in str(e), f"tampered file must be named: {e}"
            assert "autocrlf" not in str(e), f"real tamper must not be excused: {e}"

        # 6. tamper + CRLF drift together: still no autocrlf excuse
        src.write_bytes(sealed.replace(b"\n", b"\r\n"))
        try:
            check_sidecar(shard)
            raise AssertionError("tamper+CRLF shard must NOT verify")
        except ValueError as e:
            assert "autocrlf" not in str(e), f"mixed case must not be excused: {e}"

        # 7. extra file smuggled into the shard fails closed
        src.write_bytes(sealed)
        (shard / "manifest.json").write_bytes(b'{"v":1}')
        assert check_sidecar(shard) is True
        (shard / "content" / "extra.txt").write_bytes(b"smuggled")
        try:
            check_sidecar(shard)
            raise AssertionError("extra file must NOT verify")
        except ValueError as e:
            assert "extra.txt" in str(e)

    # 8. the real committed shard verifies on this host
    real = REPO / "memory" / "lenses" / "shard"
    assert check_sidecar(real) is True, "committed shard must verify post-fix"

    print("PASS test_lens_shard_sidecar: 8/8 witnesses")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL lens_shard_sidecar: {e}")
        raise SystemExit(1)
