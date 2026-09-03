#!/usr/bin/env python3
"""Publish the final Astra Stage 2 control-identity release ledger.

This automation waits for the independent successor-scope audit, verifies the
final release and pull-request state from GitHub, publishes the audit and
release objects to issue #172, performs connected readback, and refreshes PR
#187 and issue #172. It does not execute a model, bind an identity, calibrate a
threshold, authorize provider dispatch, or merge any branch.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from astra_stage2.canonical import sha256_object

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "BigBirdReturns/tier-bench")
TOKEN = os.environ["GITHUB_TOKEN"]
API_ROOT = "https://api.github.com"
ISSUE_NUMBER = 172
PULL_REQUEST_NUMBER = 187

BINDER_HEAD = "af03cef494a509ab7ba5df29fa4b4ccba423f1f8"
BINDER_TREE = "519ea2f8f448a464e817a024ad8ed1ac64493931"
IMPORT_RELEASE_HEAD = "125fdc367920960421d1e080900f1806637277f4"
IMPORT_RELEASE_TREE = "ccab08e1192346f9c386b0f41ffaab77bac73194"
RELEASE_HEAD = "46840d9ce0e3732b84cd4ad40e828c42326bcc05"
RELEASE_TREE = "ea4e5ececd37bf440af5c01bfe416cd5df8304a5"
RELEASE_BRANCH = "release/astra-stage2-control-identity-v1-20260903"
RELEASE_RUN = 33800919918
RELEASE_WINDOWS_RECEIPT = (
    "bdc2587ef54aa6713735db3ef1f8aafe0a8b5b60b3b9ee74d0df7a6bb418c35a"
)
QUALIFICATION_PAYLOAD = (
    "bcea66bdaea9fe0b349fc17d738a921e643431c42b7bd4bfec939788bdf4243b"
)
RELEASE_EVIDENCE_ARTIFACT_ID = 9911030201
RELEASE_EVIDENCE_SHA256 = (
    "5ef88d820bc866c1df02015b6b1725fb09f447a450126ada0dfe8eb7896f7a1f"
)
RELEASE_EVIDENCE_BYTES = 17960
PUBLICATION_PAYLOAD = (
    "cfa59f1c9813354900f7715ee978fb642b15e9856e1c5fef1b3cbdb74f0e437c"
)
RELEASE_PUBLICATION_ARTIFACT_ID = 9911030700
RELEASE_PUBLICATION_SHA256 = (
    "c184cc19b3e783bba518ddf05d30236e58fd46ac9a6539aec0ae49a73f59f7bb"
)
RELEASE_PUBLICATION_BYTES = 905
LAUNCHER_SHA256 = (
    "3081af6b3ff3a9026cc5171065c75e6f8d23f1819804a79a88f00b53bd3436e2"
)
BINDER_TEMPLATE_SHA256 = (
    "0292bf17538352f2c27799254bf951418fa517c1ff81f26223c736ea5e89900d"
)

AUDIT_RUN = 33801577736
AUDIT_BRANCH = (
    "audit/astra-stage2-control-identity-successor-scope-4684-20260903"
)
AUDIT_ARTIFACT_PREFIX = (
    "astra-stage2-control-identity-successor-scope-audit-33801577736-"
)
AUDIT_DISPOSITION = (
    "PASS_SUCCESSOR_SCOPE_AND_BINDER_IMPORT_PROVIDER_FREE_RELEASE_ONLY"
)

SCOPE_CLAIM_COMMENT_ID = 5531381933
AUDIT_CLAIM_COMMENT_ID = 5531568622
IMPORT_REPAIR_CLAIM_COMMENT_ID = 5531039258
PRIOR_IMPORT_AUDIT_COMMENT_ID = 5531224635
PRIOR_RELEASE_COMMENT_ID = 5531266463
PRIOR_READBACK_COMMENT_ID = 5531284028

AUDIT_MARKER = "<!-- astra-stage2-control-identity-successor-scope-audit-v1 -->"
RELEASE_MARKER = "<!-- astra-stage2-control-identity-release-v5 -->"
READBACK_MARKER = "<!-- astra-stage2-control-identity-release-v5-readback -->"

REQUIRED_HEAD_WORKFLOWS = {
    "astra-stage2-control-identity-release",
    "breadth-durability",
    "model-waterline",
    "residue-refinery",
    "sovereign-desktop",
    "sovereign-theory",
    "world-experience-atlas",
}
ALLOWED_CONCLUSIONS = {"success", "neutral", "skipped"}


def api_request(
    method: str,
    path_or_url: str,
    payload: dict[str, Any] | None = None,
    *,
    accept: str = "application/vnd.github+json",
) -> bytes:
    url = (
        path_or_url
        if path_or_url.startswith("https://")
        else API_ROOT + path_or_url
    )
    data = None
    headers = {
        "Accept": accept,
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "tier-bench-astra-final-publisher",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API {method} {url} failed with {exc.code}: {detail}"
        ) from exc


def api_json(
    method: str,
    path_or_url: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    raw = api_request(method, path_or_url, payload)
    return json.loads(raw.decode("utf-8")) if raw else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        for info in archive.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError(f"unsafe ZIP member: {info.filename}")
            target = (destination / member).resolve()
            target.relative_to(root)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def verify_sha256_manifest(root: Path) -> None:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise RuntimeError("audit artifact lacks SHA256SUMS")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        relative = relative.strip()
        if relative.startswith("./"):
            relative = relative[2:]
        target = (root / relative).resolve()
        target.relative_to(root.resolve())
        if not target.is_file():
            raise RuntimeError(f"audit manifest member is absent: {relative}")
        observed = sha256_file(target)
        if observed != expected:
            raise RuntimeError(f"audit manifest mismatch: {relative}")


def wait_for_audit() -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    deadline = time.monotonic() + 20 * 60
    while True:
        run = api_json(
            "GET",
            f"/repos/{REPOSITORY}/actions/runs/{AUDIT_RUN}",
        )
        if run.get("status") == "completed":
            if run.get("conclusion") != "success":
                jobs = api_json(
                    "GET",
                    f"/repos/{REPOSITORY}/actions/runs/{AUDIT_RUN}/jobs?per_page=100",
                )
                summary = [
                    {
                        "id": job.get("id"),
                        "name": job.get("name"),
                        "status": job.get("status"),
                        "conclusion": job.get("conclusion"),
                    }
                    for job in jobs.get("jobs", [])
                ]
                raise RuntimeError(
                    "independent successor-scope audit failed: "
                    + json.dumps(summary, sort_keys=True)
                )
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("timed out waiting for independent audit")
        time.sleep(10)

    artifacts = api_json(
        "GET",
        f"/repos/{REPOSITORY}/actions/runs/{AUDIT_RUN}/artifacts?per_page=100",
    ).get("artifacts", [])
    matches = [
        artifact
        for artifact in artifacts
        if artifact.get("name", "").startswith(AUDIT_ARTIFACT_PREFIX)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one successor-scope audit artifact, observed {len(matches)}"
        )
    artifact = matches[0]

    temp_root = Path(tempfile.mkdtemp(prefix="astra-final-publisher-"))
    zip_path = temp_root / "audit.zip"
    zip_path.write_bytes(
        api_request(
            "GET",
            f"/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip",
            accept="application/octet-stream",
        )
    )
    digest = artifact.get("digest", "")
    expected_digest = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    observed_digest = sha256_file(zip_path)
    if expected_digest and observed_digest != expected_digest:
        raise RuntimeError("downloaded audit ZIP differs from GitHub artifact digest")

    extracted = temp_root / "audit"
    safe_extract(zip_path, extracted)
    verify_sha256_manifest(extracted)
    result_path = extracted / "audit-result.json"
    if not result_path.is_file():
        raise RuntimeError("audit artifact lacks audit-result.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return run, artifact, zip_path, result_path


def validate_audit(
    run: dict[str, Any],
    artifact: dict[str, Any],
    zip_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("disposition") != AUDIT_DISPOSITION:
        raise RuntimeError("audit disposition differs from the authorized disposition")
    if result.get("failed_count") != 0:
        raise RuntimeError("audit reports failed attacks")
    if result.get("attack_count") != 7 or result.get("refused_count") != 7:
        raise RuntimeError("audit refusal denominator differs from 7/7")

    target = result.get("target", {})
    expected_target = {
        "binder_head_sha1": BINDER_HEAD,
        "binder_tree_sha1": BINDER_TREE,
        "scope_parent_head_sha1": IMPORT_RELEASE_HEAD,
        "scope_parent_tree_sha1": IMPORT_RELEASE_TREE,
        "release_head_sha1": RELEASE_HEAD,
        "release_tree_sha1": RELEASE_TREE,
        "release_run": RELEASE_RUN,
        "evidence_artifact_id": RELEASE_EVIDENCE_ARTIFACT_ID,
        "publication_artifact_id": RELEASE_PUBLICATION_ARTIFACT_ID,
        "pull_request": PULL_REQUEST_NUMBER,
    }
    if target != expected_target:
        raise RuntimeError("audit target ledger differs from final release coordinates")

    audit = result.get("audit", {})
    if audit.get("head_sha1") != run.get("head_sha"):
        raise RuntimeError("audit-result head differs from workflow run head")
    if not audit.get("tree_sha1"):
        raise RuntimeError("audit-result tree is absent")

    artifacts = result.get("artifacts", {})
    expected_artifact_fields = {
        "release_evidence_zip_sha256": RELEASE_EVIDENCE_SHA256,
        "release_publication_zip_sha256": RELEASE_PUBLICATION_SHA256,
        "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
        "publication_payload_sha256": PUBLICATION_PAYLOAD,
        "release_windows_receipt_sha256": RELEASE_WINDOWS_RECEIPT,
        "independent_binder_template_probe_sha256": BINDER_TEMPLATE_SHA256,
    }
    for key, expected in expected_artifact_fields.items():
        if artifacts.get(key) != expected:
            raise RuntimeError(f"audit artifact field differs: {key}")

    rederived = result.get("rederived", {})
    expected_rederived = {
        "tests_linux": 27,
        "tests_windows": 27,
        "windows_passed": 26,
        "windows_skipped": 1,
        "windows_failed": 0,
        "windows_errors": 0,
        "powershell_parse": "PASS",
        "preflight_schema": "tier-bench/astra-stage2-control-identity-preflight@2",
        "binder_command_import_probe": "PASS",
        "binder_command": "template",
        "caller_is_non_repository": True,
        "predecessor_workflow_successor_scope": True,
        "control_roles": 3,
        "generator_cases": 108,
        "expected_empirical_observations": 648,
        "actual_executable_control_identities": "UNBOUND",
    }
    for key, expected in expected_rederived.items():
        if rederived.get(key) != expected:
            raise RuntimeError(f"audit rederivation differs: {key}")

    authority = result.get("authority", {})
    expected_authority = {
        "provider_or_model_calls": 0,
        "empirical_subject_execution": False,
        "empirical_calibration": "NOT_RUN",
        "numeric_stage2_freeze": "NOT_ISSUED",
        "callable_astra_identity": "UNBOUND",
        "live_provider_dispatch": "PROHIBITED",
        "optional_24_call_block": "DISABLED",
        "benchmark_verdict_authority": "NONE",
        "merge_authority": "NONE",
    }
    if authority != expected_authority:
        raise RuntimeError("audit authority ledger differs")

    artifact_digest = artifact.get("digest", "")
    if artifact_digest.startswith("sha256:"):
        artifact_digest = artifact_digest.split(":", 1)[1]
    if artifact_digest != sha256_file(zip_path):
        raise RuntimeError("audit artifact digest does not rederive")
    result["resolved_artifact"] = {
        "id": int(artifact["id"]),
        "name": artifact["name"],
        "bytes": int(artifact["size_in_bytes"]),
        "sha256": artifact_digest,
    }
    return result


def validate_release_artifacts() -> dict[str, dict[str, Any]]:
    expected = {
        "evidence": (
            RELEASE_EVIDENCE_ARTIFACT_ID,
            RELEASE_EVIDENCE_BYTES,
            RELEASE_EVIDENCE_SHA256,
        ),
        "publication": (
            RELEASE_PUBLICATION_ARTIFACT_ID,
            RELEASE_PUBLICATION_BYTES,
            RELEASE_PUBLICATION_SHA256,
        ),
    }
    resolved: dict[str, dict[str, Any]] = {}
    for label, (artifact_id, byte_count, digest) in expected.items():
        value = api_json(
            "GET",
            f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}",
        )
        observed_digest = value.get("digest", "")
        if observed_digest.startswith("sha256:"):
            observed_digest = observed_digest.split(":", 1)[1]
        if int(value.get("size_in_bytes", -1)) != byte_count:
            raise RuntimeError(f"release {label} artifact size differs")
        if observed_digest != digest:
            raise RuntimeError(f"release {label} artifact digest differs")
        workflow_run = value.get("workflow_run", {})
        if int(workflow_run.get("id", -1)) != RELEASE_RUN:
            raise RuntimeError(f"release {label} artifact run differs")
        if workflow_run.get("head_sha") != RELEASE_HEAD:
            raise RuntimeError(f"release {label} artifact head differs")
        resolved[label] = {
            "id": artifact_id,
            "bytes": byte_count,
            "sha256": digest,
        }
    return resolved


def wait_for_release_head_workflows() -> list[dict[str, Any]]:
    deadline = time.monotonic() + 15 * 60
    while True:
        value = api_json(
            "GET",
            f"/repos/{REPOSITORY}/actions/runs?head_sha={RELEASE_HEAD}&per_page=100",
        )
        runs = value.get("workflow_runs", [])
        names = {run.get("name") for run in runs}
        required_present = REQUIRED_HEAD_WORKFLOWS.issubset(names)
        terminal = all(run.get("status") == "completed" for run in runs)
        if required_present and terminal:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "timed out waiting for final release-head workflows: "
                + json.dumps(
                    [
                        {
                            "id": run.get("id"),
                            "name": run.get("name"),
                            "status": run.get("status"),
                            "conclusion": run.get("conclusion"),
                        }
                        for run in runs
                    ],
                    sort_keys=True,
                )
            )
        time.sleep(10)

    prohibited = [
        run
        for run in runs
        if run.get("name") == "astra-stage2-control-identity"
    ]
    if prohibited:
        raise RuntimeError(
            "predecessor binder workflow still ran against the final successor head"
        )
    failures = [
        run
        for run in runs
        if run.get("conclusion") not in ALLOWED_CONCLUSIONS
    ]
    if failures:
        raise RuntimeError(
            "final release head has non-successful workflows: "
            + json.dumps(
                [
                    {
                        "id": run.get("id"),
                        "name": run.get("name"),
                        "conclusion": run.get("conclusion"),
                    }
                    for run in failures
                ],
                sort_keys=True,
            )
        )
    release_matches = [
        run
        for run in runs
        if run.get("id") == RELEASE_RUN
        and run.get("name") == "astra-stage2-control-identity-release"
        and run.get("conclusion") == "success"
    ]
    if len(release_matches) != 1:
        raise RuntimeError("exact final release qualification run is absent")
    return sorted(
        [
            {
                "id": int(run["id"]),
                "name": run["name"],
                "event": run["event"],
                "status": run["status"],
                "conclusion": run["conclusion"],
                "head_sha": run["head_sha"],
            }
            for run in runs
        ],
        key=lambda item: (item["name"], item["id"]),
    )


def validate_pull_request() -> dict[str, Any]:
    value = api_json(
        "GET",
        f"/repos/{REPOSITORY}/pulls/{PULL_REQUEST_NUMBER}",
    )
    if value.get("state") != "open" or value.get("merged") is True:
        raise RuntimeError("PR #187 is not open and unmerged")
    if value.get("draft") is not True:
        raise RuntimeError("PR #187 unexpectedly lost draft state")
    if value.get("head", {}).get("sha") != RELEASE_HEAD:
        raise RuntimeError("PR #187 head differs from final release")
    if value.get("head", {}).get("ref") != RELEASE_BRANCH:
        raise RuntimeError("PR #187 head branch differs")
    if value.get("base", {}).get("sha") != BINDER_HEAD:
        raise RuntimeError("PR #187 base head differs from exact binder")
    if value.get("base", {}).get("ref") != (
        "joint/astra-stage2-control-identities-20260903"
    ):
        raise RuntimeError("PR #187 base branch differs")
    return {
        "state": value["state"],
        "draft": value["draft"],
        "merged": bool(value.get("merged")),
        "mergeable": value.get("mergeable"),
        "head_sha": value["head"]["sha"],
        "head_ref": value["head"]["ref"],
        "base_sha": value["base"]["sha"],
        "base_ref": value["base"]["ref"],
    }


def list_issue_comments(issue_number: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = api_json(
            "GET",
            f"/repos/{REPOSITORY}/issues/{issue_number}/comments?per_page=100&page={page}",
        )
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


def upsert_comment(issue_number: int, marker: str, body: str) -> dict[str, Any]:
    matches = [
        comment
        for comment in list_issue_comments(issue_number)
        if marker in comment.get("body", "")
    ]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate publication marker: {marker}")
    if matches:
        result = api_json(
            "PATCH",
            f"/repos/{REPOSITORY}/issues/comments/{matches[0]['id']}",
            {"body": body},
        )
    else:
        result = api_json(
            "POST",
            f"/repos/{REPOSITORY}/issues/{issue_number}/comments",
            {"body": body},
        )
    if result.get("body") != body:
        raise RuntimeError(f"comment write/readback differs for marker {marker}")
    return result


def update_pull_request(body: str) -> dict[str, Any]:
    value = api_json(
        "PATCH",
        f"/repos/{REPOSITORY}/pulls/{PULL_REQUEST_NUMBER}",
        {"body": body},
    )
    if value.get("body") != body:
        raise RuntimeError("PR #187 body readback differs")
    if value.get("draft") is not True:
        raise RuntimeError("PR #187 update widened draft authority")
    return value


def update_issue(body: str) -> dict[str, Any]:
    value = api_json(
        "PATCH",
        f"/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        {"body": body},
    )
    if value.get("body") != body:
        raise RuntimeError("issue #172 body readback differs")
    return value


def audit_comment_body(audit: dict[str, Any]) -> str:
    artifact = audit["resolved_artifact"]
    a = audit["audit"]
    ar = audit["artifacts"]
    r = audit["rederived"]
    return f"""{AUDIT_MARKER}
### AUDIT: final PR #187 binder-import and successor-CI scope

```yaml
claim_comment: {AUDIT_CLAIM_COMMENT_ID}
scope_claim_comment: {SCOPE_CLAIM_COMMENT_ID}
target_pr: {PULL_REQUEST_NUMBER}
release:
  branch: {RELEASE_BRANCH}
  head: {RELEASE_HEAD}
  tree: {RELEASE_TREE}
  parent: {IMPORT_RELEASE_HEAD}
  parent_tree: {IMPORT_RELEASE_TREE}
  parent_delta:
    paths: 2
    additions: 30
    deletions: 0
  qualification_run: {RELEASE_RUN}
  windows_receipt_sha256: {RELEASE_WINDOWS_RECEIPT}
  qualification_payload: {QUALIFICATION_PAYLOAD}
  evidence_artifact:
    id: {RELEASE_EVIDENCE_ARTIFACT_ID}
    bytes: {RELEASE_EVIDENCE_BYTES}
    sha256: {RELEASE_EVIDENCE_SHA256}
  publication_payload: {PUBLICATION_PAYLOAD}
  publication_artifact:
    id: {RELEASE_PUBLICATION_ARTIFACT_ID}
    bytes: {RELEASE_PUBLICATION_BYTES}
    sha256: {RELEASE_PUBLICATION_SHA256}
audit:
  branch: {AUDIT_BRANCH}
  head: {a['head_sha1']}
  tree: {a['tree_sha1']}
  run: {AUDIT_RUN}
  conclusion: success
  artifact:
    id: {artifact['id']}
    bytes: {artifact['bytes']}
    sha256: {artifact['sha256']}
  payload: {audit['payload_sha256']}
windows:
  tests: {r['tests_windows']}
  passed: {r['windows_passed']}
  skipped: {r['windows_skipped']}
  failed: {r['windows_failed']}
  errors: {r['windows_errors']}
  powershell_parse: {r['powershell_parse']}
  caller_working_directory: EMPTY_NON_REPOSITORY_DIRECTORY
  preflight_schema: {r['preflight_schema']}
  binder_command: {r['binder_command']}
  binder_command_import_probe: {r['binder_command_import_probe']}
  binder_template_probe_sha256: {ar['independent_binder_template_probe_sha256']}
  preflight_receipt_sha256: {ar['independent_preflight_receipt_sha256']}
  audit_receipt_sha256: {ar['independent_windows_receipt_sha256']}
linux:
  tests: {r['tests_linux']}
  result: PASS
repository_scope:
  final_release_paths: 5
  final_parent_delta_paths: 2
  predecessor_pull_request_base: joint/astra-stage2-calibration-impl-20260902
  predecessor_push_branch: joint/astra-stage2-control-identities-20260903
  predecessor_run_on_final_pr_head: ABSENT
attacks:
  attempted: {audit['attack_count']}
  refused: {audit['refused_count']}
  failed: {audit['failed_count']}
disposition: {audit['disposition']}
authority:
  actual_executable_control_identities: UNBOUND
  provider_or_model_calls: 0
  empirical_calibration: NOT_RUN
  numeric_stage2_freeze: NOT_ISSUED
  callable_astra_identity: UNBOUND
  live_provider_dispatch: PROHIBITED
  optional_24_call_block: DISABLED
  benchmark_verdict_authority: NONE
  merge_authority: NONE
```

The independent Windows actor invoked the final release launcher by absolute path while its caller was an empty directory outside every Git checkout. The launcher imported `astra_stage2` from the exact detached `af03cef...` binder root, executed the pinned `template` command, reproduced the frozen template digest, and retained zero-call `UNBOUND` authority. The independent Linux actor downloaded the final release artifacts by immutable ID, rederived their ZIP and member hashes, rederived both canonical payloads, reran the complete 27-test denominator, and refused seven of seven authority substitutions.

The same audit classified the remaining repository defect separately from the launcher. The predecessor binder workflow now accepts pull requests only when their base is its original Stage 2 calibration branch, while its exact candidate push lane remains intact. No predecessor workflow run exists against final PR #187 head `{RELEASE_HEAD}`; the final release workflow retains the scoped predecessor bytes and records that result in both qualification and publication receipts.

**Control question:** Does the estate now consume only final head `{RELEASE_HEAD}`, reproduce the binder import probe, and stop after receipt-bearing `Prepare -SkipDownloads` with all executable identities still `UNBOUND`?"""


def build_release_object(
    audit: dict[str, Any],
    audit_comment_id: int,
    release_artifacts: dict[str, dict[str, Any]],
    head_workflows: list[dict[str, Any]],
    pull_request: dict[str, Any],
) -> dict[str, Any]:
    artifact = audit["resolved_artifact"]
    value: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-release@5",
        "classification": (
            "BINDER_IMPORT_AND_SUCCESSOR_CI_SCOPE_QUALIFIED_"
            "INDEPENDENTLY_AUDITED_ASSETS_PRESERVED_PREPARE_INCOMPLETE_"
            "IDENTITIES_UNBOUND"
        ),
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST_NUMBER,
        "source": {
            "branch": RELEASE_BRANCH,
            "head_sha1": RELEASE_HEAD,
            "tree_sha1": RELEASE_TREE,
            "binder_parent_sha1": BINDER_HEAD,
            "binder_tree_sha1": BINDER_TREE,
            "import_boundary_parent_sha1": IMPORT_RELEASE_HEAD,
            "import_boundary_parent_tree_sha1": IMPORT_RELEASE_TREE,
            "final_parent_delta": {
                "paths": [
                    ".github/workflows/astra-stage2-control-identity-release.yml",
                    ".github/workflows/astra-stage2-control-identity.yml",
                ],
                "additions": 30,
                "deletions": 0,
            },
            "launcher_sha256": LAUNCHER_SHA256,
        },
        "qualification": {
            "run_id": RELEASE_RUN,
            "conclusion": "success",
            "windows": {
                "runner": "windows-2025",
                "tests": 27,
                "passed": 26,
                "skipped": 1,
                "failed": 0,
                "errors": 0,
                "powershell_parse": "PASS",
                "launcher_preflight": "PASS",
                "binder_command_import_probe": "PASS",
                "receipt_sha256": RELEASE_WINDOWS_RECEIPT,
            },
            "linux": {
                "tests": 27,
                "result": "PASS",
                "powershell_parse": "PASS",
            },
            "predecessor_workflow_successor_scope": True,
            "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
            "evidence_artifact": release_artifacts["evidence"],
            "publication_payload_sha256": PUBLICATION_PAYLOAD,
            "publication_artifact": release_artifacts["publication"],
        },
        "independent_audit": {
            "claim_comment_id": AUDIT_CLAIM_COMMENT_ID,
            "result_comment_id": audit_comment_id,
            "branch": AUDIT_BRANCH,
            "head_sha1": audit["audit"]["head_sha1"],
            "tree_sha1": audit["audit"]["tree_sha1"],
            "run_id": AUDIT_RUN,
            "conclusion": "success",
            "artifact": artifact,
            "payload_sha256": audit["payload_sha256"],
            "attacks": audit["attack_count"],
            "refused": audit["refused_count"],
            "failed": audit["failed_count"],
            "disposition": audit["disposition"],
            "binder_template_probe_sha256": BINDER_TEMPLATE_SHA256,
        },
        "pull_request_state": {
            **pull_request,
            "head_workflows": head_workflows,
            "predecessor_workflow_on_final_head": "ABSENT",
        },
        "local_observation": {
            "observed_release_head_sha1": (
                "148484098fae50923e4df6ed013963480734be7f"
            ),
            "observed_release_tree_sha1": (
                "d0c2a9e49b5249018e6003d40f17e06f19b43835"
            ),
            "preflight_receipt_sha256": (
                "dc725b09ff3a57d2776f168b6af2351062064ae0db7394ac7386624e1dfafb42"
            ),
            "asset_custody": {
                "lotus_source_commit_sha1": (
                    "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e"
                ),
                "loopcoder_source_commit_sha1": (
                    "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c"
                ),
                "lotus_checkpoint_gib": 6.0,
                "loopcoder_checkpoint_gib": 14.194,
                "conventional_checkpoint_gib": 6.0,
                "incomplete_download_files": 0,
                "state": "ACQUIRED_PRESERVED_UNRECEIPTED",
            },
            "failure": {
                "command": "probe-hardware",
                "exception": "ModuleNotFoundError: No module named 'astra_stage2'",
                "mechanism": (
                    "pinned binder wrapper executed outside BinderRoot without "
                    "BinderRoot on PYTHONPATH"
                ),
                "hardware_probe_completed": False,
                "prepare_receipt_created": False,
                "private_config_created": False,
                "inventoried_config_created": False,
            },
        },
        "authority": {
            "physical_source_and_checkpoint_assets": (
                "ACQUIRED_PRESERVED_UNRECEIPTED"
            ),
            "official_prepare": "INCOMPLETE",
            "actual_executable_control_identities": "UNBOUND",
            "provider_or_model_calls": 0,
            "empirical_subject_execution": False,
            "empirical_calibration": "NOT_RUN",
            "numeric_stage2_freeze": "NOT_ISSUED",
            "callable_astra_identity": "UNBOUND",
            "live_provider_dispatch": "PROHIBITED",
            "optional_24_call_block": "DISABLED",
            "benchmark_verdict_authority": "NONE",
            "merge_authority": "NONE",
        },
        "claims": {
            "binder_import_repair": IMPORT_REPAIR_CLAIM_COMMENT_ID,
            "successor_ci_scope": SCOPE_CLAIM_COMMENT_ID,
            "final_audit": AUDIT_CLAIM_COMMENT_ID,
        },
        "supersedes": [
            {
                "head_sha1": IMPORT_RELEASE_HEAD,
                "tree_sha1": IMPORT_RELEASE_TREE,
                "release_comment_id": PRIOR_RELEASE_COMMENT_ID,
                "readback_comment_id": PRIOR_READBACK_COMMENT_ID,
                "reason": (
                    "launcher execution evidence remains valid, but final PR "
                    "state required predecessor-workflow scope repair"
                ),
            },
            {
                "head_sha1": (
                    "148484098fae50923e4df6ed013963480734be7f"
                ),
                "reason": (
                    "Preflight did not exercise a binder command and Prepare "
                    "exposed an unbound package import root"
                ),
            },
            {
                "head_sha1": (
                    "0c8be8c26eeceb04850fa54f4e4fadc7b1ff5a58"
                ),
                "reason": (
                    "intermediate array splatting passed literal parameter tokens"
                ),
            },
        ],
        "next_admissible_transaction": (
            "Advance the retained Windows release worktree to exact head "
            f"{RELEASE_HEAD}, verify tree {RELEASE_TREE}, reproduce Preflight "
            "schema @2 and the pinned template import probe, then run Prepare "
            "with -SkipDownloads to reuse preserved assets. Stop at "
            "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND. Bind remains "
            "prohibited until truthful runtime identities and low/high effort "
            "semantics are established for all three controls."
        ),
    }
    value["payload_sha256"] = sha256_object(value)
    return value


def release_comment_body(value: dict[str, Any]) -> str:
    rendered = json.dumps(value, sort_keys=True, indent=2)
    return f"""{RELEASE_MARKER}
### RELEASE: final binder-import and successor-CI-qualified handoff

```json
{rendered}
```

The final release keeps the repaired launcher bytes unchanged and closes the separate repository-level failure that caused the predecessor binder workflow to execute against its own successor PR. The release actor constrained that workflow to its original pull-request base, preserved its exact candidate push lane, retained the scoped workflow bytes in final qualification evidence, and reran the complete Windows and Linux denominator at the exact successor head.

The independent audit actor then reproduced the launcher import boundary from an empty non-repository Windows caller, rederived the final artifacts and canonical payloads on Linux, proved the predecessor workflow was absent from the final PR head, and refused seven of seven authority substitutions. The local estate's 26.194 GiB of source and checkpoint custody remains preserved but unreceipted. Official `Prepare` remains incomplete, and no executable identity, calibration, numeric freeze, provider call, benchmark verdict, merge, or callable Astra authority exists.

**Control question:** Does the estate advance only to `{RELEASE_HEAD}`, verify tree `{RELEASE_TREE}`, reproduce the binder import probe, and stop at receipt-bearing `ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND`?"""


def readback_object(
    release_object: dict[str, Any],
    release_comment_id: int,
    audit_comment_id: int,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-release-readback@5",
        "classification": (
            "CONNECTED_READBACK_VERIFIED_FINAL_BINDER_IMPORT_AND_SUCCESSOR_SCOPE_"
            "RELEASE_ASSETS_PRESERVED_PREPARE_INCOMPLETE_IDENTITIES_UNBOUND"
        ),
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST_NUMBER,
        "release_comment_id": release_comment_id,
        "release_marker": RELEASE_MARKER.strip("<!- >"),
        "release_payload_sha256": release_object["payload_sha256"],
        "audit_comment_id": audit_comment_id,
        "source_head_sha1": RELEASE_HEAD,
        "source_tree_sha1": RELEASE_TREE,
        "qualification_run": RELEASE_RUN,
        "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
        "audit_run": AUDIT_RUN,
        "audit_head_sha1": release_object["independent_audit"]["head_sha1"],
        "audit_tree_sha1": release_object["independent_audit"]["tree_sha1"],
        "audit_payload_sha256": release_object["independent_audit"][
            "payload_sha256"
        ],
        "verified": {
            "release_body_exact_readback": True,
            "release_marker_present": True,
            "release_payload_present": True,
            "source_head_present": True,
            "source_tree_present": True,
            "qualification_present": True,
            "audit_present": True,
            "predecessor_scope_present": True,
            "predecessor_run_on_final_head_absent": True,
            "preserved_asset_state_present": True,
            "official_prepare_incomplete_present": True,
            "zero_call_unbound_boundary_present": True,
        },
        "authority": release_object["authority"],
    }
    value["payload_sha256"] = sha256_object(value)
    return value


def readback_comment_body(value: dict[str, Any]) -> str:
    rendered = json.dumps(value, sort_keys=True, indent=2)
    return f"""{READBACK_MARKER}
### READBACK: final binder-import and successor-CI-qualified release

```json
{rendered}
```

The final release comment was fetched after publication and matched the exact body submitted by the publisher. Its connected body contains the final head and tree, qualification and audit coordinates, predecessor-workflow scope result, preserved-but-unreceipted asset custody, incomplete official Prepare state, and zero-call `UNBOUND` authority boundary. The remote publication transaction is closed without creating Bind, calibration, numeric-freeze, provider-dispatch, benchmark-verdict, merge, or callable-Astra authority.

**Control question:** Does every subsequent local receipt bind exact final head `{RELEASE_HEAD}` and distinguish preserved physical assets from a completed official Prepare?"""


def pull_request_body(
    audit: dict[str, Any],
    audit_comment_id: int,
    release_object: dict[str, Any],
    release_comment_id: int,
    readback_object_value: dict[str, Any],
    readback_comment_id: int,
) -> str:
    artifact = audit["resolved_artifact"]
    return f"""## Classification

This draft is the final cross-platform, provider-free local execution handoff for the Astra Stage 2 executable-control identity binder. It repairs two independently classified failures. The first was the estate-observed Python import boundary that prevented the pinned binder wrapper from importing `astra_stage2` during `Prepare`. The second was a repository workflow-scope defect that caused the already-qualified predecessor binder workflow to run against PR #187 and reject the successor release's authorized files.

The launcher now executes every pinned binder command with the exact detached binder root as both its working directory and scoped Python import root. The predecessor binder workflow now accepts pull requests only when their base is its original Stage 2 calibration branch, while retaining its original exact-candidate push lane. The final release qualification and an independent audit exercised both mechanisms. The local source and checkpoint assets remain preserved, but official `Prepare` is still incomplete. Actual LOTUS, LoopCoder-v2, and conventional-control executable identities remain `UNBOUND`.

## Exact final coordinate

```text
binder parent                  {BINDER_HEAD}
binder tree                    {BINDER_TREE}
import-boundary parent         {IMPORT_RELEASE_HEAD}
import-boundary parent tree    {IMPORT_RELEASE_TREE}
final release branch           {RELEASE_BRANCH}
final head                     {RELEASE_HEAD}
final tree                     {RELEASE_TREE}
launcher SHA-256               {LAUNCHER_SHA256}
final parent delta             2 paths, +30/-0
final delta from binder        5 paths
```

The final parent delta is limited to:

```text
.github/workflows/astra-stage2-control-identity.yml
.github/workflows/astra-stage2-control-identity-release.yml
```

The predecessor workflow's `pull_request` base is now `joint/astra-stage2-calibration-impl-20260902`. Its push lane remains `joint/astra-stage2-control-identities-20260903`. It is absent from all workflow runs attached to final PR head `{RELEASE_HEAD}`.

## Estate observation and preserved custody

```text
observed failed head           148484098fae50923e4df6ed013963480734be7f
observed failed tree           d0c2a9e49b5249018e6003d40f17e06f19b43835
local Preflight receipt        dc725b09ff3a57d2776f168b6af2351062064ae0db7394ac7386624e1dfafb42
Lotus source                   eb77e2f7909c5006f58ff0ad7cd6629b942caa9e
LoopCoder source               ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c
LOTUS checkpoint               6.000 GiB, complete
LoopCoder-v2 checkpoint        14.194 GiB, complete
conventional checkpoint        6.000 GiB, complete
incomplete download files      0
first failed binder command    probe-hardware
failure                        ModuleNotFoundError: No module named 'astra_stage2'
PREPARE-RECEIPT.json           absent
private configuration          absent
inventoried configuration      absent
provider/model calls           0
```

The acquired assets are admissible preserved custody inputs for `Prepare -SkipDownloads`. They are not evidence that official `Prepare` completed.

## Final exact-head qualification

```text
workflow                       astra-stage2-control-identity-release
run                            {RELEASE_RUN}
conclusion                     success
Windows tests                  27
Windows passed                 26
Windows skipped                1 expected symlink test
Windows failed/errors          0 / 0
Windows PowerShell parser      PASS
Windows launcher Preflight     PASS
binder import probe            PASS
Windows receipt                {RELEASE_WINDOWS_RECEIPT}
Linux tests                    27 / PASS
Linux PowerShell parser        PASS
predecessor workflow scope     PASS
qualification payload          {QUALIFICATION_PAYLOAD}
evidence artifact              {RELEASE_EVIDENCE_ARTIFACT_ID}
evidence ZIP bytes             {RELEASE_EVIDENCE_BYTES}
evidence ZIP SHA-256           {RELEASE_EVIDENCE_SHA256}
publication payload            {PUBLICATION_PAYLOAD}
publication artifact           {RELEASE_PUBLICATION_ARTIFACT_ID}
publication ZIP bytes          {RELEASE_PUBLICATION_BYTES}
publication ZIP SHA-256        {RELEASE_PUBLICATION_SHA256}
```

## Independent final audit

```text
scope claim                    issue #172 comment {SCOPE_CLAIM_COMMENT_ID}
audit claim                    issue #172 comment {AUDIT_CLAIM_COMMENT_ID}
audit result                   issue #172 comment {audit_comment_id}
audit branch                   {AUDIT_BRANCH}
audit head                     {audit['audit']['head_sha1']}
audit tree                     {audit['audit']['tree_sha1']}
audit run                      {AUDIT_RUN}
audit conclusion               success
audit artifact                 {artifact['id']}
audit ZIP bytes                {artifact['bytes']}
audit ZIP SHA-256              {artifact['sha256']}
audit payload                  {audit['payload_sha256']}
independent attacks            7
refused                        7
failed                         0
disposition                    {audit['disposition']}
```

The independent Windows leg invoked the launcher from an empty non-repository caller, reproduced the exact binder template digest `{BINDER_TEMPLATE_SHA256}`, and retained `UNBOUND`. The Linux leg downloaded the final artifacts by immutable ID, rederived all retained hashes and canonical payloads, reran all 27 tests, verified the exact five-path release delta and two-path final parent delta, and confirmed that the predecessor workflow does not run against the final PR head.

## Publication and authority

```text
release v5 comment             {release_comment_id}
release payload                {release_object['payload_sha256']}
release readback comment       {readback_comment_id}
readback payload               {readback_object_value['payload_sha256']}
PR state                       OPEN / DRAFT / UNMERGED
physical assets                ACQUIRED / PRESERVED / UNRECEIPTED
official Prepare               INCOMPLETE
actual executable identities   UNBOUND
provider/model calls           0
empirical calibration          NOT RUN / PROHIBITED
numeric Stage 2 freeze         NOT ISSUED / PROHIBITED
callable Astra identity        UNBOUND
live provider dispatch         PROHIBITED
optional 24-call block         DISABLED
benchmark verdict authority    NONE
merge authority                NONE
```

## Next admissible local transaction

Advance the retained worktree at `S:\Scratch\Worktrees\Tier-Bench\astra-stage2-control-identity-release-b394` to exact final head `{RELEASE_HEAD}` from canonical repository `D:\Projects\Measurement\Tier-Bench\main`. Verify tree `{RELEASE_TREE}`, run current `Preflight`, and require schema `tier-bench/astra-stage2-control-identity-preflight@2`, `binder_command_import_probe = PASS`, `binder_command = template`, template digest `{BINDER_TEMPLATE_SHA256}`, zero calls, and `UNBOUND`.

Only after that reproduces may the estate run `Prepare -SkipDownloads` against `S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities-real`. Success requires `PREPARE-RECEIPT.json`, both private configurations, completed hardware evidence, and terminal state `ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND`. `Bind` remains prohibited until actual installed runtimes and truthful low/high effort semantics are derived for all three controls.

**Control question:** Does the estate begin from exact final head `{RELEASE_HEAD}`, verify tree `{RELEASE_TREE}`, reproduce the binder import probe, reuse preserved assets through `Prepare -SkipDownloads`, and preserve `UNBOUND` until real runtime and effort identities are established?"""


def issue_body(
    audit: dict[str, Any],
    audit_comment_id: int,
    release_object: dict[str, Any],
    release_comment_id: int,
    readback_object_value: dict[str, Any],
    readback_comment_id: int,
) -> str:
    artifact = audit["resolved_artifact"]
    return f"""## Classification

This issue is the authoritative coordination and custody surface for the frontier-fingerprint chain from the qualified observatory through Stage 2 calibration and Astra instrumentation. It grants no provider-call, empirical-execution, spend, numeric-freeze, benchmark-verdict, production, callable-Astra, or merge authority. State moves only through exact `CLAIM`, `AUDIT`, `RELEASE`, and `READBACK` objects bound to remote Git and retained artifacts.

## Current control-identity coordinate

```text
control-identity binder        PR #186
binder head                    {BINDER_HEAD}
binder tree                    {BINDER_TREE}
binder state                   QUALIFIED IMPLEMENTATION

current local handoff          PR #187
release branch                 {RELEASE_BRANCH}
final head                     {RELEASE_HEAD}
final tree                     {RELEASE_TREE}
import-boundary parent         {IMPORT_RELEASE_HEAD}
import-boundary parent tree    {IMPORT_RELEASE_TREE}
launcher SHA-256               {LAUNCHER_SHA256}
final parent delta             2 paths, +30/-0
final release paths            5

qualification run              {RELEASE_RUN}
Windows tests                  27 / 26 pass / 1 expected skip / 0 fail / 0 error
Linux tests                    27 / PASS
PowerShell parser              PASS
Windows launcher Preflight     PASS
binder import probe            PASS
predecessor workflow scope     PASS
Windows receipt                {RELEASE_WINDOWS_RECEIPT}
qualification payload          {QUALIFICATION_PAYLOAD}
evidence artifact              {RELEASE_EVIDENCE_ARTIFACT_ID}
  ZIP bytes                    {RELEASE_EVIDENCE_BYTES}
  ZIP SHA-256                  {RELEASE_EVIDENCE_SHA256}
publication payload            {PUBLICATION_PAYLOAD}
publication artifact           {RELEASE_PUBLICATION_ARTIFACT_ID}
  ZIP bytes                    {RELEASE_PUBLICATION_BYTES}
  ZIP SHA-256                  {RELEASE_PUBLICATION_SHA256}

audit claim                    {AUDIT_CLAIM_COMMENT_ID}
audit result                   {audit_comment_id}
audit branch                   {AUDIT_BRANCH}
audit head                     {audit['audit']['head_sha1']}
audit tree                     {audit['audit']['tree_sha1']}
audit run                      {AUDIT_RUN}
audit artifact                 {artifact['id']}
  ZIP bytes                    {artifact['bytes']}
  ZIP SHA-256                  {artifact['sha256']}
audit payload                  {audit['payload_sha256']}
audit attacks                  7 / 7 refused / 0 failed
audit disposition              {audit['disposition']}

release v5                     {release_comment_id}
release payload                {release_object['payload_sha256']}
release readback               {readback_comment_id}
readback payload               {readback_object_value['payload_sha256']}

PR state                       OPEN / DRAFT / UNMERGED
head workflow failures         0
predecessor run on final head  ABSENT
physical source assets         ACQUIRED / PRESERVED / UNRECEIPTED
physical checkpoint assets     ACQUIRED / PRESERVED / UNRECEIPTED
official Prepare               INCOMPLETE
actual executable identities   UNBOUND
empirical local calibration    NOT RUN / PROHIBITED
numeric Stage 2 freeze         NOT ISSUED / PROHIBITED
Astra instrumentation          NOT IMPLEMENTED
callable Astra identity        UNBOUND
live subject calls             0 / PROHIBITED
optional K×R block             DISABLED
benchmark verdict authority    NONE
merge authority                NONE
```

## Failure chain and repair classification

The estate first rejected head `b3948e62...` for a Windows parser failure and POSIX-only qualification. It then reproduced head `148484098fae50923e4df6ed013963480734be7f`, acquired the exact Lotus and LoopCoder source checkouts plus all three complete checkpoints, and reached the first real binder command. `probe-hardware` failed because the pinned wrapper executed outside the binder worktree without that worktree on `PYTHONPATH`. No official Prepare receipt, private configuration, inventoried configuration, completed hardware probe, model call, provider call, binding, calibration, or freeze resulted.

Head `{IMPORT_RELEASE_HEAD}` repaired the execution boundary by routing every pinned binder operation through one named-parameter invocation boundary that enters the exact binder root, prepends that root to `PYTHONPATH`, invokes the wrapper, checks exit status, and restores the caller environment. Preflight began executing the pinned binder `template` command and retaining a hashed import probe. The cross-platform release and an independent audit reproduced that mechanism.

The remaining PR failure was separate. The predecessor binder workflow's broad pull-request trigger admitted PR #187 and then correctly rejected files that were outside the predecessor candidate's own path law. Final head `{RELEASE_HEAD}` constrains that workflow to pull requests whose base is `joint/astra-stage2-calibration-impl-20260902`, preserves its push qualification on `joint/astra-stage2-control-identities-20260903`, retains the resulting workflow bytes in final release evidence, and records the scope result in qualification and publication receipts. The predecessor workflow is absent from final-head PR runs, while all applicable final-head workflows completed successfully.

## Next local transaction

The retained local release worktree remains:

```text
S:\Scratch\Worktrees\Tier-Bench\astra-stage2-control-identity-release-b394
```

The canonical repository and private custody roots remain:

```text
D:\Projects\Measurement\Tier-Bench\main
S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities-real
```

The estate must fetch and detach the retained worktree at exact final head `{RELEASE_HEAD}`, verify tree `{RELEASE_TREE}`, and run the current `Preflight`. It must return `PREFLIGHT_PASS`, schema `tier-bench/astra-stage2-control-identity-preflight@2`, `binder_command_import_probe = PASS`, `binder_command = template`, template digest `{BINDER_TEMPLATE_SHA256}`, zero model/provider calls, and `actual_executable_control_identities = UNBOUND`.

Only after that reproduces may the estate run `Prepare -SkipDownloads`. The switch is required because the exact public assets are already preserved. A successful official Prepare must complete hardware probing and checkpoint inventory and produce:

```text
PREPARE-RECEIPT.json
astra-stage2-control-identities.private.json
astra-stage2-control-identities.inventoried.private.json
```

Its terminal state must be `ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND`. That state does not authorize `Bind`. Truthful executable runtime identity and low/high effort semantics for LOTUS, LoopCoder-v2, and the conventional negative control must be derived from the actual installed runtimes before executable identities can be bound.

## Ordered queue

- [x] Qualify and publish the measurement substrate and Stage 1 law.
- [x] Build and independently audit the provider-free Stage 2 scaffold.
- [x] Build and qualify the executable-control binder.
- [x] Reject the first Windows-defective release candidate.
- [x] Acquire exact Lotus, LoopCoder, and three checkpoint assets.
- [x] Detect the binder import failure before a hardware receipt or configuration existed.
- [x] Repair and independently audit the binder import boundary.
- [x] Detect the predecessor-workflow scope defect on PR #187.
- [x] Scope the predecessor workflow to its original PR base while preserving its push lane.
- [x] Pass the complete 27-test suite on Windows Server 2025 and Ubuntu 24.04 at final head `{RELEASE_HEAD}`.
- [x] Independently reproduce the final binder import boundary from an empty non-repository Windows caller.
- [x] Independently verify the five-path release, two-path final parent delta, and absence of the predecessor workflow from the final PR head.
- [x] Refuse seven of seven independent authority substitutions.
- [x] Publish release v5 and connected readback.
- [ ] Reproduce `preflight@2` on the local Windows estate at exact head `{RELEASE_HEAD}`.
- [ ] Run official `Prepare -SkipDownloads` and obtain the receipt and both configurations.
- [ ] Derive truthful runtime and low/high effort mappings for all three controls.
- [ ] Bind and verify all three executable identities.
- [ ] Execute the complete 648-observation local calibration denominator.
- [ ] Publish either `EMPIRICAL_CALIBRATION_CANDIDATE` or `CALIBRATION_INCONCLUSIVE`.
- [ ] Freeze numeric thresholds only through a separate authority-bearing transaction.
- [ ] Implement and provider-free qualify Astra streaming instrumentation.
- [ ] Bind a callable Astra identity in a private live-disabled manifest.
- [ ] Allow the waterline to earn any subject call; keep the optional 24-call block disabled absent separate authorization.

## Handoff protocol

A new session reads this issue, PR #187, scope claim `{SCOPE_CLAIM_COMMENT_ID}`, audit claim `{AUDIT_CLAIM_COMMENT_ID}`, audit result `{audit_comment_id}`, release v5 `{release_comment_id}`, and readback `{readback_comment_id}`. It treats exact final head `{RELEASE_HEAD}` and tree `{RELEASE_TREE}` as the only current local execution handoff. Heads `b394...`, `148484...`, `0c8be8...`, and `{IMPORT_RELEASE_HEAD}` remain historical evidence and are superseded for current local execution authority.

**Control question:** Does every local control-identity transaction begin from exact final head `{RELEASE_HEAD}`, verify tree `{RELEASE_TREE}`, reproduce the binder import probe, reuse preserved assets through `Prepare -SkipDownloads`, and preserve `UNBOUND` until real runtime and effort identities are established?"""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    run, artifact, zip_path, result_path = wait_for_audit()
    audit = validate_audit(run, artifact, zip_path, result_path)
    release_artifacts = validate_release_artifacts()
    head_workflows = wait_for_release_head_workflows()
    pull_request = validate_pull_request()

    audit_body = audit_comment_body(audit)
    audit_comment = upsert_comment(
        ISSUE_NUMBER,
        AUDIT_MARKER,
        audit_body,
    )
    audit_comment_id = int(audit_comment["id"])

    release_object = build_release_object(
        audit,
        audit_comment_id,
        release_artifacts,
        head_workflows,
        pull_request,
    )
    release_body = release_comment_body(release_object)
    release_comment = upsert_comment(
        ISSUE_NUMBER,
        RELEASE_MARKER,
        release_body,
    )
    release_comment_id = int(release_comment["id"])

    connected_release = api_json(
        "GET",
        f"/repos/{REPOSITORY}/issues/comments/{release_comment_id}",
    )
    if connected_release.get("body") != release_body:
        raise RuntimeError("connected release comment readback differs")
    for required in (
        RELEASE_MARKER,
        release_object["payload_sha256"],
        RELEASE_HEAD,
        RELEASE_TREE,
        audit["payload_sha256"],
        str(audit["resolved_artifact"]["id"]),
        "ACQUIRED_PRESERVED_UNRECEIPTED",
        '"official_prepare": "INCOMPLETE"',
        '"actual_executable_control_identities": "UNBOUND"',
        '"provider_or_model_calls": 0',
    ):
        if required not in connected_release["body"]:
            raise RuntimeError(f"connected release readback lacks: {required}")

    readback_value = readback_object(
        release_object,
        release_comment_id,
        audit_comment_id,
    )
    readback_body = readback_comment_body(readback_value)
    readback_comment = upsert_comment(
        ISSUE_NUMBER,
        READBACK_MARKER,
        readback_body,
    )
    readback_comment_id = int(readback_comment["id"])
    connected_readback = api_json(
        "GET",
        f"/repos/{REPOSITORY}/issues/comments/{readback_comment_id}",
    )
    if connected_readback.get("body") != readback_body:
        raise RuntimeError("connected readback comment differs")

    pr_body = pull_request_body(
        audit,
        audit_comment_id,
        release_object,
        release_comment_id,
        readback_value,
        readback_comment_id,
    )
    updated_pr = update_pull_request(pr_body)

    coordination_body = issue_body(
        audit,
        audit_comment_id,
        release_object,
        release_comment_id,
        readback_value,
        readback_comment_id,
    )
    updated_issue = update_issue(coordination_body)

    publication_root = Path(
        os.environ.get(
            "PUBLICATION_ROOT",
            str(Path(tempfile.gettempdir()) / "astra-final-publication"),
        )
    )
    if publication_root.exists():
        shutil.rmtree(publication_root)
    publication_root.mkdir(parents=True)
    shutil.copy2(result_path, publication_root / "audit-result.json")
    write_json(publication_root / "release-object.json", release_object)
    write_json(publication_root / "readback-object.json", readback_value)
    write_json(publication_root / "head-workflows.json", head_workflows)
    write_json(publication_root / "pull-request-state.json", pull_request)
    (publication_root / "audit-comment.md").write_text(
        audit_body + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (publication_root / "release-comment.md").write_text(
        release_body + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (publication_root / "readback-comment.md").write_text(
        readback_body + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (publication_root / "pull-request-body.md").write_text(
        pr_body + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (publication_root / "issue-body.md").write_text(
        coordination_body + "\n",
        encoding="utf-8",
        newline="\n",
    )

    publication_record: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-final-publication@1",
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST_NUMBER,
        "issue": ISSUE_NUMBER,
        "source_head_sha1": RELEASE_HEAD,
        "source_tree_sha1": RELEASE_TREE,
        "qualification_run": RELEASE_RUN,
        "qualification_payload_sha256": QUALIFICATION_PAYLOAD,
        "audit_run": AUDIT_RUN,
        "audit_head_sha1": audit["audit"]["head_sha1"],
        "audit_tree_sha1": audit["audit"]["tree_sha1"],
        "audit_artifact": audit["resolved_artifact"],
        "audit_payload_sha256": audit["payload_sha256"],
        "audit_comment_id": audit_comment_id,
        "release_comment_id": release_comment_id,
        "release_payload_sha256": release_object["payload_sha256"],
        "readback_comment_id": readback_comment_id,
        "readback_payload_sha256": readback_value["payload_sha256"],
        "pr_body_updated_at": updated_pr.get("updated_at"),
        "issue_body_updated_at": updated_issue.get("updated_at"),
        "authority": release_object["authority"],
    }
    publication_record["payload_sha256"] = sha256_object(publication_record)
    write_json(publication_root / "publication-record.json", publication_record)

    manifest_lines = []
    for path in sorted(item for item in publication_root.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        manifest_lines.append(
            f"{sha256_file(path)}  {path.relative_to(publication_root).as_posix()}"
        )
    (publication_root / "SHA256SUMS").write_text(
        "\n".join(manifest_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"publication_root={publication_root}\n")
            handle.write(f"audit_comment_id={audit_comment_id}\n")
            handle.write(f"release_comment_id={release_comment_id}\n")
            handle.write(f"readback_comment_id={readback_comment_id}\n")
            handle.write(
                f"release_payload={release_object['payload_sha256']}\n"
            )
            handle.write(
                f"readback_payload={readback_value['payload_sha256']}\n"
            )
            handle.write(f"audit_payload={audit['payload_sha256']}\n")

    print(json.dumps(publication_record, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
