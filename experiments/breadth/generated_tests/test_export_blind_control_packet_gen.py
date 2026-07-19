# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\export_blind_control_packet.py  mutation_score=2/6
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
"""Characterization tests for export_blind_control_packet.py.

These tests assert the module's current behavior with concrete values.
"""


import hashlib
import hmac
import io
import json
import random
import contextlib
import sys
from pathlib import Path

import export_blind_control_packet as mod


def _write_jsonl(path: Path, rows):
    text = "\n".join(json.dumps(row) for row in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def _run_main_capture(argv: list[str]) -> tuple[str, int | None]:
    original = sys.argv[:]
    sys.argv = ["export_blind_control_packet.py"] + argv
    capture = io.StringIO()
    try:
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            try:
                mod.main()
                return capture.getvalue(), None
            except SystemExit as exc:  # argparse exits on invalid flags/values
                return capture.getvalue(), exc.code
    finally:
        sys.argv = original


def test_source_commit_happy_and_fallback():
    original = mod.subprocess.check_output
    mod.subprocess.check_output = lambda *args, **kwargs: "abc123\n"
    try:
        assert mod.source_commit() == "abc123"
    finally:
        mod.subprocess.check_output = original

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    mod.subprocess.check_output = boom
    try:
        assert mod.source_commit() == "UNKNOWN"
    finally:
        mod.subprocess.check_output = original


def test_administration_id_prefers_admin_run_or_fallback():
    p = Path("/tmp/control-admin-id.jsonl")
    assert mod.administration_id(p, {"administration_id": "admin_1", "run_id": "run_2"}) == "admin_1"
    assert mod.administration_id(p, {"run_id": "run_2"}) == "run_2"
    assert mod.administration_id(p, {}) == p.stem


def test_load_jsonl_parses_rows_and_enforces_meta():
    p = Path("tmp_load_jsonl.jsonl")
    _write_jsonl(p, [
        {"_meta": {"administration_id": "adm"}},
        {"probe_id": "P1"},
        {"probe_id": "P2"},
    ])
    meta, rows = mod.load_jsonl(p)
    assert meta == {"_meta": {"administration_id": "adm"}}
    assert len(rows) == 2
    assert rows[0]["probe_id"] == "P1"
    assert rows[1]["probe_id"] == "P2"

    empty_path = Path("tmp_load_jsonl_empty.jsonl")
    empty_path.write_text("", encoding="utf-8")
    try:
        mod.load_jsonl(empty_path)
    except ValueError as exc:
        assert str(exc) == f"{empty_path}: missing _meta row"
    else:
        raise AssertionError("expected ValueError for missing _meta")

    missing_meta = Path("tmp_load_jsonl_missing_meta.jsonl")
    missing_meta.write_text('{"probe_id":"P1"}\n', encoding="utf-8")
    try:
        mod.load_jsonl(missing_meta)
    except ValueError as exc:
        assert str(exc) == f"{missing_meta}: missing _meta row"
    else:
        raise AssertionError("expected ValueError for missing _meta")


def test_secret_commitment_and_opaque_id():
    assert (
        mod.secret_commitment("id-salt", "abc")
        == hashlib.sha256("id-salt\0abc".encode("utf-8")).hexdigest()
    )
    expected = hmac.new(
        "salt-value".encode("utf-8"),
        "SRC\0adm\0P1\0answer".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    assert mod.opaque_id("salt-value", "SRC", "adm", "P1", "answer") == expected


def test_build_packet_sorting_and_shuffle():
    data_dir = Path("tmp_build_packet_data")
    data_dir.mkdir(exist_ok=True)
    file_a = data_dir / "a.jsonl"
    file_b = data_dir / "b.jsonl"
    _write_jsonl(file_a, [
        {"_meta": {"administration_id": "admin-a", "model": "mA", "effort": "low", "contributor": "uA", "date": "2026-01-01"}},
        {"probe_id": "P2", "probe_shape": "shape2", "prompt_surface": "prompt2", "response": "resp2", "score": 1, "grader": "gA"},
        {"probe_id": "P1", "probe_shape": "shape1", "prompt_surface": "prompt1", "response": "resp1", "score": 2, "grader": "gA"},
    ])
    _write_jsonl(file_b, [
        {"_meta": {"run_id": "admin-b"}},
        {"probe_id": "P3", "probe_shape": "shape3", "prompt_surface": "prompt3", "response": "resp3", "score": 3, "grader": "gB"},
    ])
    rubric = Path("tmp_build_packet_rubric.md")
    rubric.write_text("RUBRIC-TEXT", encoding="utf-8")
    packet, key = mod.build_packet(data_dir, rubric, "source-commit", "seed-123456789012", "id_salt_value_id_salt_value_32__")

    expected_pre_shuffle = []
    for probe_id, probe_shape, prompt_surface, response in [
        ("P1", "shape1", "prompt1", "resp1"),
        ("P2", "shape2", "prompt2", "resp2"),
        ("P3", "shape3", "prompt3", "resp3"),
    ]:
        expected_pre_shuffle.append({
            "id": mod.opaque_id("id_salt_value_id_salt_value_32__", "source-commit", file_a.name[0] if probe_id in {"P1", "P2"} else file_b.name[0], probe_id, response),
            "probe_id": probe_id,
            "probe_shape": probe_shape,
            "prompt_surface": prompt_surface,
            "response": response,
        })
    random.Random("seed-123456789012").shuffle(expected_pre_shuffle)
    assert packet["_meta"]["packet_schema"] == "tier-bench.control_blind_packet.v2"
    assert packet["_meta"]["source_commit"] == "source-commit"
    assert packet["_meta"]["item_count"] == 3
    assert packet["items"] == expected_pre_shuffle
    assert packet["rubric"] == "RUBRIC-TEXT"
    assert len(packet["items"]) == 3

    for item in packet["items"]:
        mapping = key[item["id"]]
        expected_source = str(file_a) if item["probe_id"] in {"P1", "P2"} else str(file_b)
        expected_admin = "a" if item["probe_id"] in {"P1", "P2"} else "b"
        expected_model = None
        expected_effort = None
        expected_contributor = None
        expected_date = None
        expected_score = 2 if item["probe_id"] == "P1" else 1 if item["probe_id"] == "P2" else 3
        expected_grader = "gA" if item["probe_id"] in {"P1", "P2"} else "gB"
        assert mapping["source_file"] == expected_source
        assert mapping["administration_id"] == expected_admin
        assert mapping["model"] == expected_model
        assert mapping["effort"] == expected_effort
        assert mapping["contributor"] == expected_contributor
        assert mapping["date"] == expected_date
        assert mapping["probe_id"] == item["probe_id"]
        assert mapping["baseline_score"] == expected_score
        assert mapping["baseline_grader"] == expected_grader


def test_build_packet_empty_and_bad_probe_id_errors():
    empty_data = Path("tmp_empty_data_dir")
    empty_data.mkdir(exist_ok=True)
    rubric = Path("tmp_build_packet_rubric_empty.md")
    rubric.write_text("empty", encoding="utf-8")
    packet, key = mod.build_packet(empty_data, rubric, "source", "seed-123456789012", "id_salt_value_id_salt_value_32__")
    assert packet["items"] == []
    assert packet["_meta"]["item_count"] == 0
    assert key == {}

    bad_data = Path("tmp_bad_data_dir")
    bad_data.mkdir(exist_ok=True)
    bad_file = bad_data / "bad.jsonl"
    _write_jsonl(bad_file, [
        {"_meta": {"administration_id": "adm"}},
        {"probe_id": "P12", "probe_shape": "shape", "prompt_surface": "prompt", "response": "answer"},
    ])
    try:
        mod.build_packet(bad_data, rubric, "source", "seed-123456789012", "id_salt_value_id_salt_value_32__")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown probe id")


def test_write_json_and_sha256_file():
    path = Path("tmp_nested/output.json")
    obj = {"a": 1, "b": [2, 3]}
    mod.write_json(path, obj)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed == obj
    assert mod.sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_load_private_secrets():
    top = Path("tmp_private_top.json")
    top.write_text(json.dumps({"id_salt": "salt-top", "permutation_seed": "seed-top-123456789"}), encoding="utf-8")
    assert mod.load_private_secrets(top) == ("salt-top", "seed-top-123456789")

    nested = Path("tmp_private_nested.json")
    nested.write_text(json.dumps({"_meta": {"id_salt": "salt-nested", "permutation_seed": "seed-nested-123456789"}}), encoding="utf-8")
    assert mod.load_private_secrets(nested) == ("salt-nested", "seed-nested-123456789")

    bad = Path("tmp_private_missing.json")
    bad.write_text(json.dumps({"_meta": {"permutation_seed": "seed"}}), encoding="utf-8")
    try:
        mod.load_private_secrets(bad)
    except ValueError as exc:
        assert "missing private secret 'id_salt'" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing id_salt")


def test_load_id_salt_formats_and_errors():
    plain = Path("tmp_id_salt_plain.txt")
    plain.write_text("   salt-characters-are-here-12345   ", encoding="utf-8")
    assert mod.load_id_salt(plain) == "salt-characters-are-here-12345"

    json_path = Path("tmp_id_salt_obj.json")
    json_path.write_text(json.dumps({"id_salt": "json-salt-value"}), encoding="utf-8")
    assert mod.load_id_salt(json_path) == "json-salt-value"

    json_meta_path = Path("tmp_id_salt_meta.json")
    json_meta_path.write_text(json.dumps({"_meta": {"id_salt": "meta-salt-value"}}), encoding="utf-8")
    assert mod.load_id_salt(json_meta_path) == "meta-salt-value"

    empty = Path("tmp_id_salt_empty.txt")
    empty.write_text("   ", encoding="utf-8")
    try:
        mod.load_id_salt(empty)
    except ValueError as exc:
        assert str(exc) == f"{empty}: empty id salt"
    else:
        raise AssertionError("expected ValueError for empty id salt")

    json_missing = Path("tmp_id_salt_json_missing.json")
    json_missing.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    try:
        mod.load_id_salt(json_missing)
    except ValueError as exc:
        assert str(exc) == f"{json_missing}: empty id salt"
    else:
        raise AssertionError("expected ValueError for missing id_salt")


def test_main_happy_path_and_errors():
    data_dir = Path("tmp_main_data")
    data_dir.mkdir(exist_ok=True)
    _write_jsonl(data_dir / "run.jsonl", [
        {"_meta": {"administration_id": "admin-main", "model": "model", "effort": "full", "contributor": "alice", "date": "2026-01-02"}},
        {"probe_id": "P1", "probe_shape": "shape1", "prompt_surface": "prompt1", "response": "response1", "score": 7, "grader": "auto"},
    ])
    rubric = Path("tmp_main_rubric.md")
    rubric.write_text("main-rubric", encoding="utf-8")
    secret_file = Path("tmp_main_secrets.json")
    secret_file.write_text(
        json.dumps({
            "id_salt": "main-id-salt-value-1234567890-abcdefghij",
            "permutation_seed": "main-permutation-seed-1234",
        }),
        encoding="utf-8",
    )
    packet_path = Path("tmp_main_packet.json")
    key_path = Path("tmp_main_key.json")
    out, exit_code = _run_main_capture([
        "--data", str(data_dir),
        "--rubric", str(rubric),
        "--packet", str(packet_path),
        "--key", str(key_path),
        "--secrets-from-key", str(secret_file),
        "--source-commit", "SRC-MAIN",
    ])
    assert exit_code is None
    assert "wrote packet" in out
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    assert packet["_meta"]["source_commit"] == "SRC-MAIN"
    assert packet["_meta"]["item_count"] == 1
    item = packet["items"][0]
    expected_id = mod.opaque_id("main-id-salt-value-1234567890-abcdefghij", "SRC-MAIN", "run", "P1", "response1")
    assert item["id"] == expected_id
    assert item["probe_id"] == "P1"
    assert item["probe_shape"] == "shape1"
    assert key["_meta"]["id_salt"] == "main-id-salt-value-1234567890-abcdefghij"
    assert key["_meta"]["permutation_seed"] == "main-permutation-seed-1234"
    assert key["items"][item["id"]] == {
        "source_file": str(data_dir / "run.jsonl"),
        "administration_id": "run",
        "model": None,
        "effort": None,
        "contributor": None,
        "date": None,
        "probe_id": "P1",
        "baseline_score": 7,
        "baseline_grader": "auto",
    }

    out, exit_code = _run_main_capture([
        "--data", str(data_dir),
        "--rubric", str(rubric),
        "--packet", str(packet_path),
        "--key", str(key_path),
        "--secrets-from-key", str(secret_file),
        "--seed", "shortseed",
    ])
    assert exit_code == 2
    assert "--secrets-from-key cannot be combined with --seed or --id-salt-file" in out

    salt_path = Path("tmp_main_id_salt_short.txt")
    salt_path.write_text("short-salt", encoding="utf-8")
    out, exit_code = _run_main_capture([
        "--data", str(data_dir),
        "--rubric", str(rubric),
        "--packet", str(packet_path),
        "--key", str(key_path),
        "--id-salt-file", str(salt_path),
        "--seed", "1234567890",
        "--source-commit", "SRC-MAIN",
    ])
    assert exit_code == 2
    assert "id salt must contain at least 32 characters" in out


def main():
    test_source_commit_happy_and_fallback()
    test_administration_id_prefers_admin_run_or_fallback()
    test_load_jsonl_parses_rows_and_enforces_meta()
    test_secret_commitment_and_opaque_id()
    test_build_packet_sorting_and_shuffle()
    test_build_packet_empty_and_bad_probe_id_errors()
    test_write_json_and_sha256_file()
    test_load_private_secrets()
    test_load_id_salt_formats_and_errors()
    test_main_happy_path_and_errors()
    print("OK")


if __name__ == "__main__":
    main()
