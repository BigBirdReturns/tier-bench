#!/usr/bin/env python3
"""Sealed packet export tests; hidden graders and keys must never enter solver scope."""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import export_solver_packet as exporter  # noqa: E402

MANIFEST = REPO / "tasks/almanac_rule_boundary_001.json"


@contextmanager
def _scratch():
    path = REPO / ".test-tmp" / f"packet-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _export(parent: Path, suffix: str = "one"):
    out = parent / f"solver-{suffix}"
    receipt = parent / f"coordinator-{suffix}.json"
    data = exporter.export_packet(MANIFEST, out, receipt)
    return out, receipt, data


def test_packet_excludes_hidden_and_key_material():
    with _scratch() as parent:
        out, receipt, data = _export(parent)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        names = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
        assert all(name not in names for name in manifest["hidden_files"])
        assert not any(p.name in exporter.FORBIDDEN_NAMES for p in out.rglob("*"))
        assert not any("key" in {part.lower() for part in p.relative_to(out).parts}
                       for p in out.rglob("*") if p.is_file())
        assert receipt.parent == out.parent and receipt not in out.parents
        assert data["peer_conclusions_included"] is False


def test_solver_manifest_is_safe_and_coordinator_receipt_holds_grader_hash():
    with _scratch() as parent:
        out, receipt, data = _export(parent)
        safe = json.loads((out / "PACKET.json").read_text(encoding="utf-8"))
        serialized = json.dumps(safe)
        assert safe["hidden_material_included"] is False
        assert "hidden_tests.py" not in serialized
        assert "hidden_graders" not in serialized
        assert data["hidden_graders"] and data["hidden_graders"][0]["path"].endswith("hidden_tests.py")
        assert json.loads(receipt.read_text(encoding="utf-8")) == data


def test_packet_digest_is_deterministic():
    with _scratch() as parent:
        _, _, first = _export(parent, "one")
        _, _, second = _export(parent, "two")
        assert first["packet_sha256"] == second["packet_sha256"]
        assert first["prompt_sha256"] == second["prompt_sha256"]


def test_export_never_overwrites_solver_or_receipt():
    with _scratch() as parent:
        out, receipt, _ = _export(parent)
        try:
            exporter.export_packet(MANIFEST, out, parent / "new-receipt.json")
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing solver destination should be rejected")
        other = parent / "other-solver"
        try:
            exporter.export_packet(MANIFEST, other, receipt)
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing coordinator receipt should be rejected")
        # The failed receipt check happens after packet construction; no orphan survives.
        assert not other.exists()


def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test(); print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1; print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
