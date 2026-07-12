#!/usr/bin/env python3
"""Prove committed orchestration receipts survive a fresh Git checkout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[1]
TEST_TMP = REPO / ".test-tmp"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha256(root: Path, commit: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relative}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def assert_hash(root: Path, relative: str, expected: str, label: str) -> None:
    path = root / relative
    assert path.is_file(), f"{label}: missing from fresh clone: {relative}"
    actual = sha256(path)
    assert actual == expected, (
        f"{label}: fresh-clone SHA-256 mismatch for {relative}: "
        f"expected {expected}, got {actual}"
    )


def verify_run_receipts(clone: Path) -> int:
    checked = 0
    run_files = sorted((clone / "data" / "orchestration").glob("*.json"))
    assert run_files, "fresh clone contains no orchestration run files"

    for run_path in run_files:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        source_commit = run["pairing"]["source_commit"]
        for manifest in run["task_manifests"]:
            actual = git_blob_sha256(clone, source_commit, manifest["path"])
            assert actual == manifest["sha256"], (
                f"task manifest: pinned source {source_commit} does not contain "
                f"the declared bytes for {manifest['path']}"
            )
            checked += 1

        for trial in run["trials"]:
            trial_id = trial["trial_id"]
            candidate = trial["candidate"]
            verdict = trial["verdict"]
            provenance = trial["provenance"]
            assert_hash(clone, candidate["path"], candidate["sha256"], trial_id)
            assert_hash(
                clone,
                verdict["hidden_grader_path"],
                verdict["hidden_grader_sha256"],
                trial_id,
            )
            assert_hash(
                clone,
                verdict["grader_output_path"],
                verdict["grader_output_sha256"],
                trial_id,
            )
            assert_hash(
                clone,
                provenance["raw_response_path"],
                provenance["raw_response_sha256"],
                trial_id,
            )
            assert_hash(
                clone,
                provenance["event_stream_path"],
                provenance["event_stream_sha256"],
                trial_id,
            )
            checked += 5
            if "administration_receipt_path" in provenance:
                assert_hash(
                    clone,
                    provenance["administration_receipt_path"],
                    provenance["administration_receipt_sha256"],
                    trial_id,
                )
                checked += 1

    return checked


def verify_packet_receipts(clone: Path) -> int:
    checked = 0
    pattern = "**/packet_receipt.json"
    packet_paths = sorted(
        (clone / "data" / "orchestration" / "runs").glob(pattern)
    )
    assert packet_paths, "fresh clone contains no packet receipts"

    for packet_path in packet_paths:
        label = str(packet_path.relative_to(clone))
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        assert packet["solver_scope"] == "<SOLVER_SCOPE>", (
            f"{label}: solver scope must not expose an absolute workstation path"
        )
        assert_hash(
            clone, packet["manifest_path"], packet["manifest_sha256"], label
        )
        checked += 1
        for grader in packet["hidden_graders"]:
            assert_hash(clone, grader["path"], grader["sha256"], label)
            checked += 1

        grade_path = packet_path.with_name("grade_receipt.json")
        grade = json.loads(grade_path.read_text(encoding="utf-8"))
        for name, field in (
            ("candidate.py", "candidate_sha256"),
            ("raw_response.txt", "raw_response_sha256"),
            ("grader_outputs.json", "grader_output_sha256"),
        ):
            artifact = packet_path.with_name(name)
            assert_hash(
                clone, str(artifact.relative_to(clone)), grade[field], label
            )
            checked += 1

    return checked


def verify_excluded_observations(clone: Path) -> int:
    checked = 0
    exclusions = sorted(
        (clone / "data" / "orchestration" / "excluded").glob("**/exclusion.json")
    )
    for exclusion_path in exclusions:
        exclusion = json.loads(exclusion_path.read_text(encoding="utf-8"))
        assert exclusion["counts_as_trial"] is False
        assert exclusion["counts_toward_broker"] is False
        label = str(exclusion_path.relative_to(clone))
        for prefix in ("raw_response", "thread_snapshot"):
            assert_hash(
                clone,
                exclusion[f"{prefix}_path"],
                exclusion[f"{prefix}_sha256"],
                label,
            )
            checked += 1
    return checked


def main() -> int:
    TEST_TMP.mkdir(exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix="clone-integrity-", dir=TEST_TMP))
    clone = parent / "checkout"
    try:
        subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "clone",
                "--no-local",
                "--quiet",
                str(REPO),
                str(clone),
            ],
            check=True,
        )
        checked = (
            verify_run_receipts(clone)
            + verify_packet_receipts(clone)
            + verify_excluded_observations(clone)
        )
        print(f"OK — {checked} path-backed receipt hashes survive a fresh clone")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
