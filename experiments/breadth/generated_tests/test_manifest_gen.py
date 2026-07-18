# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=tier_runner\manifest.py  mutation_score=3/5
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tier_runner"))

import hashlib
import json
import tempfile
from pathlib import Path

import manifest


def _temp_manifest_path(tmp_dir: Path) -> Path:
    return tmp_dir / "manifest.json"


def _write_manifest(path: Path, data: dict) -> bytes:
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    return raw


def _base_template() -> bytes:
    return b"echo {prompt} for {worktree}\n"


def _base_manifest(template_path: str) -> dict:
    return {
        "schema": manifest.SCHEMA,
        "protocol_commit": "1234567890abcdef1234567890abcdef12345678",
        "isolation": {
            "fresh_session_per_call": True,
            "instruction_files": False,
            "auto_memory": False,
            "conversation_carryover": False,
        },
        "tool_versions": {"planner": "1.0.0"},
        "prompt_templates": {
            template_path: {
                "path": template_path,
                "sha256": hashlib.sha256(_base_template()).hexdigest(),
            }
        },
        "arms": {
            "default": {
                "model_id": "model-1",
                "effort": "low",
                "surface": "cli",
                "cost_basis": "real-billed",
                "account": "acct-1",
                "tier": "standard",
                "prompt_template": template_path,
                "adapter": {
                    "command": [
                        "run",
                        "--prompt",
                        "{prompt}",
                        "--backend-result",
                        "{backend_result}",
                        "--dispatch-receipt",
                        "{dispatch_receipt}",
                        "{worktree}",
                    ]
                },
            }
        },
    }


def test_sha256_bytes_matches_hashlib():
    assert manifest.sha256_bytes(b"manifest") == hashlib.sha256(b"manifest").hexdigest()


def test_sha256_file_reads_bytes():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "artifact.bin"
        path.write_bytes(b"payload")
        assert manifest.sha256_file(path) == hashlib.sha256(b"payload").hexdigest()


def test_canonical_json_stable_compact():
    payload = {"b": 2, "a": 1}
    result = manifest.canonical_json(payload)
    assert result == b'{"a":1,"b":2}\n'


def test_expand_command_replaces_placeholders():
    command = ("echo", "{prompt}", "{worktree}")
    expanded = manifest.expand_command(command, {"prompt": "hi", "worktree": "/tmp/repo"})
    assert expanded == ["echo", "hi", "/tmp/repo"]


def test_expand_command_multiple_values_and_extra_keys():
    command = ("{prompt}:{backend_result}", "{dispatch_receipt}")
    expanded = manifest.expand_command(
        command,
        {
            "prompt": "hello",
            "backend_result": "ok",
            "dispatch_receipt": "r",
            "task_id": "unused",
        },
    )
    assert expanded == ["hello:ok", "r"]


def test_expand_command_unexpanded_raises():
    try:
        manifest.expand_command(("{unknown}",), {"prompt": "x"})
    except manifest.ManifestError as err:
        assert str(err) == "unexpanded command placeholder in '{unknown}'"
    else:
        assert False


def test_load_backend_happy_path():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manifest_path = _temp_manifest_path(root)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        raw = _write_manifest(manifest_path, data)
        loaded = manifest.load_backend(manifest_path, "default")

        assert loaded.arm == "default"
        assert loaded.model_id == "model-1"
        assert loaded.effort == "low"
        assert loaded.surface == "cli"
        assert loaded.cost_basis == "real-billed"
        assert loaded.account == "acct-1"
        assert loaded.tier == "standard"
        assert loaded.command == (
            "run",
            "--prompt",
            "{prompt}",
            "--backend-result",
            "{backend_result}",
            "--dispatch-receipt",
            "{dispatch_receipt}",
            "{worktree}",
        )
        assert loaded.template_name == "template.txt"
        assert loaded.template_path == template_path.resolve()
        assert loaded.template_bytes == _base_template()
        assert loaded.template_sha256 == hashlib.sha256(_base_template()).hexdigest()
        assert loaded.manifest_path == manifest_path.resolve()
        assert loaded.manifest_sha256 == manifest.sha256_bytes(raw)
        assert (
            loaded.protocol_commit
            == "1234567890abcdef1234567890abcdef12345678"
        )
        assert loaded.isolation == data["isolation"]
        assert loaded.tool_versions == {"planner": "1.0.0"}


def test_load_backend_rejects_invalid_json():
    with tempfile.TemporaryDirectory() as td:
        manifest_path = _temp_manifest_path(Path(td))
        manifest_path.write_text("{", encoding="utf-8")
        try:
            manifest.load_backend(manifest_path, "default")
        except manifest.ManifestError as err:
            assert err.args[0].startswith("invalid manifest JSON:")
        else:
            assert False


def test_load_backend_rejects_bad_schema():
    with tempfile.TemporaryDirectory() as td:
        manifest_path = _temp_manifest_path(Path(td))
        manifest_path.write_text(
            json.dumps({"schema": "wrong", "arms": {}}, sort_keys=True),
            encoding="utf-8",
        )
        try:
            manifest.load_backend(manifest_path, "default")
        except manifest.ManifestError as err:
            assert str(err) == f"manifest schema must be {manifest.SCHEMA}"
        else:
            assert False

def test_load_backend_rejects_invalid_protocol_commit():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["protocol_commit"] = "ZZ1234567890abcdef1234567890abcdef12345678"
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "protocol_commit must be a full lowercase Git SHA"
        else:
            assert False


def test_load_backend_rejects_invalid_isolation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["isolation"]["fresh_session_per_call"] = False
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "isolation.fresh_session_per_call must be True"
        else:
            assert False


def test_load_backend_rejects_invalid_tool_versions():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["tool_versions"] = {}
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "tool_versions must bind at least one non-empty name/version"
        else:
            assert False


def test_load_backend_rejects_unknown_arm():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "missing")
        except manifest.ManifestError as err:
            assert str(err) == "manifest has no arm 'missing'"
        else:
            assert False


def test_load_backend_rejects_unknown_template_name():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["arms"]["default"]["prompt_template"] = "missing-template"
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "unknown prompt template 'missing-template'"
        else:
            assert False


def test_load_backend_rejects_bad_template_hash():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(b"changed")
        data = _base_manifest("template.txt")
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            expected_hash = hashlib.sha256(_base_template()).hexdigest()
            got_hash = hashlib.sha256(b"changed").hexdigest()
            assert str(err) == (
                f"prompt template hash mismatch: expected {expected_hash}, got {got_hash}"
            )
        else:
            assert False


def test_load_backend_rejects_cost_basis():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["arms"]["default"]["cost_basis"] = "free"
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "unsupported cost_basis 'free'"
        else:
            assert False


def test_load_backend_rejects_command_with_unknown_placeholder():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["arms"]["default"]["adapter"]["command"][1] = "{bogus}"
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "adapter.command has unknown placeholders: ['{bogus}']"
        else:
            assert False


def test_load_backend_rejects_command_missing_placeholder():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template_path = root / "template.txt"
        template_path.write_bytes(_base_template())
        data = _base_manifest("template.txt")
        data["arms"]["default"]["adapter"]["command"] = ["run", "{prompt}", "{worktree}"]
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == (
                "adapter.command is missing placeholders: "
                "['{backend_result}', '{dispatch_receipt}']"
            )
        else:
            assert False


def test_load_backend_template_path_escaping_with_parent_reference():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        data = _base_manifest("../template.txt")
        _write_manifest(_temp_manifest_path(root), data)
        try:
            manifest.load_backend(_temp_manifest_path(root), "default")
        except manifest.ManifestError as err:
            assert str(err) == "prompt template path must stay under the manifest directory"
        else:
            assert False


def main() -> None:
    test_sha256_bytes_matches_hashlib()
    test_sha256_file_reads_bytes()
    test_canonical_json_stable_compact()
    test_expand_command_replaces_placeholders()
    test_expand_command_multiple_values_and_extra_keys()
    test_expand_command_unexpanded_raises()
    test_load_backend_happy_path()
    test_load_backend_rejects_invalid_json()
    test_load_backend_rejects_bad_schema()
    test_load_backend_rejects_invalid_protocol_commit()
    test_load_backend_rejects_invalid_isolation()
    test_load_backend_rejects_invalid_tool_versions()
    test_load_backend_rejects_unknown_arm()
    test_load_backend_rejects_unknown_template_name()
    test_load_backend_rejects_bad_template_hash()
    test_load_backend_rejects_cost_basis()
    test_load_backend_rejects_command_with_unknown_placeholder()
    test_load_backend_rejects_command_missing_placeholder()
    test_load_backend_template_path_escaping_with_parent_reference()
    print("OK")


if __name__ == "__main__":
    main()
