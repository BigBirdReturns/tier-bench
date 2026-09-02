from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from estate_lab.floor import load_floor_adapter, load_floor_spec
from estate_lab.production import (
    ProductionError,
    ProductionPolicy,
    atomic_write_json,
    build_release_archive,
    build_support_bundle,
    production_doctor,
    run_bounded_process,
    run_production_conformance,
    sanitized_environment,
    sha256_file,
    strict_load_json,
    verify_pinned_entrypoint,
    verify_release_archive,
    verify_submission_bundle,
)
from estate_lab.production_cli import main as production_main

HERE = Path(__file__).resolve().parents[1]
SPEC = HERE / "fixtures" / "floor" / "floor.example.json"
ADAPTER = HERE / "fixtures" / "floor" / "reference-adapter" / "adapter.json"


class ProductionPrimitiveTests(unittest.TestCase):
    def test_atomic_json_roundtrip_and_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "receipt.json"
            atomic_write_json(path, {"status": "PASS", "value": 7})
            self.assertEqual(strict_load_json(path, max_bytes=1024)["value"], 7)
            with self.assertRaises(ProductionError) as raised:
                strict_load_json(path, max_bytes=1)
            self.assertEqual(raised.exception.reason, "json_size_limit")

    def test_secret_environment_is_not_forwarded(self) -> None:
        environment = sanitized_environment(
            {
                "PATH": os.environ.get("PATH", ""),
                "HOME": "/tmp/example",
                "API_KEY": "must-not-escape",
                "AUTHORIZATION": "must-not-escape",
                "UNRELATED": "also-not-forwarded",
            }
        )
        self.assertIn("PATH", environment)
        self.assertNotIn("API_KEY", environment)
        self.assertNotIn("AUTHORIZATION", environment)
        self.assertNotIn("UNRELATED", environment)
        self.assertEqual(environment["PYTHONHASHSEED"], "0")

    def test_bounded_process_passes_and_hashes_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt, stdout, stderr = run_bounded_process(
                [sys.executable, "-c", "print('ready')"],
                cwd=Path(temp_dir),
                timeout_seconds=5,
                max_capture_bytes=1024,
            )
        self.assertEqual(receipt.exit_code, 0)
        self.assertEqual(stdout, b"ready\n")
        self.assertEqual(stderr, b"")
        self.assertEqual(receipt.stdout_sha256, sha256_file_bytes(stdout))

    def test_bounded_process_refuses_output_flood(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ProductionError) as raised:
                run_bounded_process(
                    [sys.executable, "-c", "import sys; sys.stdout.write('x'*1000000)"],
                    cwd=Path(temp_dir),
                    timeout_seconds=5,
                    max_capture_bytes=1024,
                )
        self.assertEqual(raised.exception.reason, "adapter_output_limit")

    def test_bounded_process_kills_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ProductionError) as raised:
                run_bounded_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=Path(temp_dir),
                    timeout_seconds=1,
                    max_capture_bytes=1024,
                )
        self.assertEqual(raised.exception.reason, "adapter_timeout")


def sha256_file_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


class ProductionConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_floor_spec(SPEC)
        cls.adapter = load_floor_adapter(ADAPTER, cls.spec)

    def test_reference_entrypoint_is_supply_pinned(self) -> None:
        pins = verify_pinned_entrypoint(
            self.adapter,
            [sys.executable, str(self.adapter.source_path.parent / "adapter.py")],
        )
        self.assertEqual(list(pins), ["adapter.py"])
        self.assertEqual(pins["adapter.py"], self.adapter.raw["supply"]["artifacts"][0]["sha256"])

    def test_external_interpreter_symlink_is_outside_supply_boundary(self) -> None:
        from unittest.mock import patch

        original = Path.is_symlink

        def pretend_interpreter_is_symlink(path: Path) -> bool:
            if str(path) == str(Path(sys.executable)):
                return True
            return original(path)

        with patch("pathlib.Path.is_symlink", autospec=True, side_effect=pretend_interpreter_is_symlink):
            pins = verify_pinned_entrypoint(
                self.adapter,
                [sys.executable, str(self.adapter.source_path.parent / "adapter.py")],
            )
        self.assertEqual(list(pins), ["adapter.py"])

    def test_hardened_reference_conformance_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            submission = run_production_conformance(
                self.spec,
                self.adapter,
                output_root=Path(temp_dir),
                policy=ProductionPolicy(timeout_seconds=30),
            )
            bundle = Path(temp_dir) / submission.submission_id
            self.assertTrue((bundle / "submission.json").is_file())
            self.assertTrue((bundle / "CHECKSUMS.sha256").is_file())
            verified = verify_submission_bundle(bundle)
            self.assertEqual(verified["status"], "PASS")
            self.assertGreater(verified["execution_receipts"], 0)
        self.assertEqual(submission.result, "pass")
        self.assertIn("core@1", submission.verified_profiles)
        self.assertEqual(submission.raw["verifier"]["implementation"], "surface-interop-python")
        self.assertEqual(submission.raw["verifier"]["version"], (HERE / "VERSION").read_text().strip())
        self.assertIn("production_policy_sha256", submission.raw["evidence"])

    def test_submission_bundle_tamper_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            submission = run_production_conformance(
                self.spec,
                self.adapter,
                output_root=root,
                policy=ProductionPolicy(timeout_seconds=30),
            )
            bundle = root / submission.submission_id
            path = bundle / "SUMMARY.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "tamper\n",
                encoding="utf-8",
            )
            with self.assertRaises(ProductionError) as raised:
                verify_submission_bundle(bundle)
            self.assertEqual(raised.exception.reason, "submission_checksum_mismatch")

    def test_production_cli_refuses_implicit_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            code = production_main(
                [
                    "conform",
                    str(ADAPTER),
                    "--spec",
                    str(SPEC),
                    "--output",
                    str(Path(temp_dir) / "out"),
                ]
            )
        self.assertEqual(code, 3)


class ProductionReleaseTests(unittest.TestCase):
    def test_release_is_reproducible_and_offline_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.zip"
            second = root / "second.zip"
            a = build_release_archive(HERE.parent, first, version="1.0.0")
            b = build_release_archive(HERE.parent, second, version="1.0.0")
            self.assertEqual(a["release_id"], b["release_id"])
            self.assertEqual(sha256_file(first), sha256_file(second))
            verified = verify_release_archive(first)
            self.assertEqual(verified["status"], "PASS")
            with zipfile.ZipFile(first) as archive:
                self.assertIn("pyproject.toml", archive.namelist())
                self.assertIn("SBOM.spdx.json", archive.namelist())
                self.assertIn("CHECKSUMS.sha256", archive.namelist())

    def test_release_tamper_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.zip"
            tampered = root / "tampered.zip"
            build_release_archive(HERE.parent, source, version="1.0.0")
            with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(tampered, "w") as output:
                for info in input_archive.infolist():
                    payload = input_archive.read(info.filename)
                    if info.filename == "README.md":
                        payload += b"tamper"
                    output.writestr(info, payload)
            with self.assertRaises(ProductionError) as raised:
                verify_release_archive(tampered)
            self.assertEqual(raised.exception.reason, "release_checksum_mismatch")

    def test_release_path_traversal_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "escape.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape", b"x")
            with self.assertRaises(ProductionError) as raised:
                verify_release_archive(archive_path)
            self.assertEqual(raised.exception.reason, "release_path_invalid")


    def test_release_rejects_unchecksummed_extra_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.zip"
            expanded = root / "extra.zip"
            build_release_archive(HERE.parent, source, version="1.0.0")
            with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(expanded, "w") as output:
                for info in input_archive.infolist():
                    output.writestr(info, input_archive.read(info.filename))
                output.writestr("unaccounted.txt", b"not in checksums")
            with self.assertRaises(ProductionError) as raised:
                verify_release_archive(expanded)
            self.assertEqual(raised.exception.reason, "release_archive_shape")

    def test_extracted_release_runs_without_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "release.zip"
            extract = root / "extract"
            build_release_archive(HERE.parent, archive_path, version="1.0.0")
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract)
            receipt, stdout, stderr = run_bounded_process(
                [sys.executable, str(extract / "surface-interop.py"), "--version"],
                cwd=extract,
                timeout_seconds=10,
                max_capture_bytes=4096,
            )
            self.assertIn("PYTHONSAFEPATH", receipt.environment_keys)
            self.assertEqual(receipt.exit_code, 0, stderr.decode("utf-8", errors="replace"))
            self.assertEqual(stdout.decode("utf-8").strip(), "1.0.0")

    def test_support_bundle_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "support.json"
            report = Path(temp_dir) / "report.json"
            report.write_text('{"secret":"do-not-copy"}\n', encoding="utf-8")
            result = build_support_bundle(output, source_root=HERE.parent, report_paths=[report])
            text = output.read_text(encoding="utf-8")
            self.assertEqual(result["format"], "surface-interop-support/1")
            self.assertNotIn("do-not-copy", text)
            self.assertIn(sha256_file(report), text)

    def test_doctor_passes_and_cli_version_is_consistent(self) -> None:
        report = production_doctor(HERE.parent)
        self.assertEqual(report["status"], "PASS")
        stream = io.StringIO()
        original = sys.stdout
        try:
            sys.stdout = stream
            code = production_main(["--version"])
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        self.assertEqual(stream.getvalue().strip(), (HERE / "VERSION").read_text().strip())


if __name__ == "__main__":
    unittest.main()
