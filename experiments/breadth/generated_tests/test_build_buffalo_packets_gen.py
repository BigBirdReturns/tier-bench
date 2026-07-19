# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\build_buffalo_packets.py  mutation_score=4/7
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
#!/usr/bin/env python3


import contextlib
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

import build_buffalo_packets as target


sha256 = target.sha256
build_item = target.build_item
module_main = target.main


def test_sha256_expected_values():
    assert sha256(b"") == hashlib.sha256(b"").hexdigest()
    assert (
        sha256(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_rejects_non_bytes():
    try:
        sha256("abc")  # type: ignore[arg-type]
    except TypeError as err:
        assert "must be encoded" in str(err)
    else:
        raise AssertionError("sha256 should reject string input")


def test_build_item_with_empty_inputs():
    with tempfile.TemporaryDirectory() as tmpdir:
        item = Path(tmpdir) / "item-empty"
        packet = item / "packet"
        packet.mkdir(parents=True)
        (packet / "problem.md").write_text("", encoding="utf-8")
        (packet / "source_excerpt.py").write_text("", encoding="utf-8")

        receipt = build_item(item)
        prompt = (
            target.PREAMBLE
            + "\n## Public problem report\n\n"
            + ""
            + "\n\n## Pinned source excerpt\n\n```python\n"
            + ""
            + "\n```\n"
        )
        prompt_bytes = prompt.encode("utf-8")
        envelope = (
            "<codex_delegation>\n"
            f"  <source_thread_id>{target.SOURCE_THREAD_ID}</source_thread_id>\n"
            f"  <input>{target.html.escape(prompt, quote=False)}</input>\n"
            "</codex_delegation>"
        )
        envelope_bytes = envelope.encode("utf-8")

        assert receipt == {
            "schema": "tier-bench/arc-d-packet-build@1",
            "item_id": item.name,
            "builder": "scripts/build_buffalo_packets.py",
            "problem_sha256": sha256(b""),
            "source_excerpt_sha256": sha256(b""),
            "prompt_sha256": sha256(prompt_bytes),
            "prompt_bytes": len(prompt_bytes),
            "delivered_envelope_sha256": sha256(envelope_bytes),
            "delivered_envelope_bytes": len(envelope_bytes),
            "source_thread_id": target.SOURCE_THREAD_ID,
            "transport_transform": "html.escape(prompt, quote=False)",
            "line_endings": "LF",
        }
        assert (packet / "PROMPT.md").read_bytes() == prompt_bytes
        assert (packet / "delivered_envelope.txt").read_bytes() == envelope_bytes
        assert (
            packet / "build_receipt.json"
        ).read_text(encoding="utf-8") == json.dumps(
            receipt, indent=2, sort_keys=True
        ) + "\n"


def test_build_item_missing_problem_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        item = Path(tmpdir) / "missing-problem"
        packet = item / "packet"
        packet.mkdir(parents=True)
        (packet / "source_excerpt.py").write_text("x = 1", encoding="utf-8")
        try:
            build_item(item)
        except FileNotFoundError as err:
            assert "problem.md" in str(err)
        else:
            raise AssertionError("Expected build_item to raise for missing problem.md")


def test_main_builds_all_items_and_returns_zero():
    with tempfile.TemporaryDirectory() as tmpdir:
        items_root = Path(tmpdir) / "items"
        item1_packet = items_root / "item1" / "packet"
        item2_packet = items_root / "item2" / "packet"
        item1_packet.mkdir(parents=True)
        item2_packet.mkdir(parents=True)

        item1_packet_path = item1_packet
        item2_packet_path = item2_packet
        (item1_packet_path / "problem.md").write_text("first", encoding="utf-8")
        (item1_packet_path / "source_excerpt.py").write_text("alpha", encoding="utf-8")
        (item2_packet_path / "problem.md").write_text("second", encoding="utf-8")
        (item2_packet_path / "source_excerpt.py").write_text("beta", encoding="utf-8")

        original_items = target.ITEMS
        original_argv = sys.argv[:]
        target.ITEMS = items_root
        try:
            sys.argv = ["build_buffalo_packets.py"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                ret = module_main()
            assert ret == 0
            receipts = json.loads(output.getvalue())
            assert [entry["item_id"] for entry in receipts] == ["item1", "item2"]
            assert len(receipts) == 2
            assert receipts[0]["problem_sha256"] == sha256(
                (item1_packet_path / "problem.md").read_bytes()
            )
            assert receipts[1]["problem_sha256"] == sha256(
                (item2_packet_path / "problem.md").read_bytes()
            )
        finally:
            target.ITEMS = original_items
            sys.argv = original_argv


def test_main_empty_items_returns_empty_array():
    with tempfile.TemporaryDirectory() as tmpdir:
        items_root = Path(tmpdir) / "items"
        items_root.mkdir()
        original_items = target.ITEMS
        original_argv = sys.argv[:]
        target.ITEMS = items_root
        try:
            sys.argv = ["build_buffalo_packets.py"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                ret = module_main()
            assert ret == 0
            assert json.loads(output.getvalue()) == []
        finally:
            target.ITEMS = original_items
            sys.argv = original_argv


def test_main_check_detects_drift_and_errors():
    with tempfile.TemporaryDirectory() as tmpdir:
        items_root = Path(tmpdir) / "items"
        packet = items_root / "item1" / "packet"
        packet.mkdir(parents=True)
        problem = packet / "problem.md"
        source = packet / "source_excerpt.py"
        problem.write_text("problem", encoding="utf-8")
        source.write_text("source", encoding="utf-8")

        original_items = target.ITEMS
        original_argv = sys.argv[:]
        target.ITEMS = items_root
        try:
            sys.argv = ["build_buffalo_packets.py"]
            with contextlib.redirect_stdout(io.StringIO()):
                module_main()

            problem.write_text("modified", encoding="utf-8")
            sys.argv = ["build_buffalo_packets.py", "--check"]
            try:
                module_main()
            except SystemExit as err:
                assert err.code != 0
                assert str(err) == "packet drift: item1"
            else:
                raise AssertionError("Expected check mode to fail on drift")

            problem.write_text("problem", encoding="utf-8")
            sys.argv = ["build_buffalo_packets.py"]
            with contextlib.redirect_stdout(io.StringIO()):
                module_main()

            sys.argv = ["build_buffalo_packets.py", "--check"]
            with contextlib.redirect_stdout(io.StringIO()):
                ret = module_main()
            assert ret == 0
        finally:
            target.ITEMS = original_items
            sys.argv = original_argv


def main() -> None:
    test_sha256_expected_values()
    test_sha256_rejects_non_bytes()
    test_build_item_with_empty_inputs()
    test_build_item_missing_problem_raises()
    test_main_builds_all_items_and_returns_zero()
    test_main_empty_items_returns_empty_array()
    test_main_check_detects_drift_and_errors()
    print("OK")


if __name__ == "__main__":
    main()
