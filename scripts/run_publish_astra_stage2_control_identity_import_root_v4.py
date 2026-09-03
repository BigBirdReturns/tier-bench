from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import publish_astra_stage2_control_identity_import_root_v4 as publication


def assert_exact_release(
    release_head: str,
    release_tree: str,
    release_run: dict[str, Any],
    qualification: dict[str, Any],
    publication_index: dict[str, Any],
    audit_head: str,
    audit_tree: str,
    audit_run: dict[str, Any],
    audit_result: dict[str, Any],
) -> None:
    source = qualification.get("source", {})
    conformance = qualification.get("conformance", {})
    actual = qualification.get("actual_binding", {})
    authority = qualification.get("authority", {})

    expected_source = {
        "head_sha1": release_head,
        "tree_sha1": release_tree,
        "binder_head_sha1": "af03cef494a509ab7ba5df29fa4b4ccba423f1f8",
        "binder_tree_sha1": "519ea2f8f448a464e817a024ad8ed1ac64493931",
    }
    for key, expected in expected_source.items():
        if source.get(key) != expected:
            raise RuntimeError(f"Qualification source field {key} mismatch")
    if qualification.get("run_id") != release_run["id"]:
        raise RuntimeError("Qualification run does not match exact workflow run")

    expected_conformance = {
        "tests": 27,
        "binder_tests": 20,
        "release_tests": 7,
        "linux_tests": 27,
        "linux_skipped": 0,
        "windows_tests": 27,
        "windows_skipped": 1,
        "control_roles": 3,
        "generator_cases": 108,
        "expected_empirical_observations": 648,
    }
    for key, expected in expected_conformance.items():
        if conformance.get(key) != expected:
            raise RuntimeError(f"Qualification conformance field {key} mismatch")
    for key in (
        "powershell_parse_linux",
        "powershell_parse_windows",
        "windows_preflight_executed",
    ):
        if conformance.get(key) is not True:
            raise RuntimeError(f"Qualification did not prove {key}")

    if actual.get("state") != "UNBOUND" or actual.get("bound_controls") != 0:
        raise RuntimeError("Qualification widened executable identity authority")
    if actual.get("empirical_observations") != 0:
        raise RuntimeError("Qualification widened empirical execution authority")
    if authority.get("provider_or_model_calls") != 0:
        raise RuntimeError("Qualification widened provider/model call authority")
    if authority.get("empirical_subject_execution") is not False:
        raise RuntimeError("Qualification widened empirical subject authority")
    if authority.get("numeric_stage2_freeze") != "NOT_ISSUED":
        raise RuntimeError("Qualification widened numeric-freeze authority")
    if authority.get("callable_astra_identity") != "UNBOUND":
        raise RuntimeError("Qualification widened Astra identity authority")
    if authority.get("live_provider_dispatch") != "PROHIBITED":
        raise RuntimeError("Qualification widened dispatch authority")
    if authority.get("optional_24_call_block") != "DISABLED":
        raise RuntimeError("Qualification widened optional-call authority")
    if authority.get("benchmark_verdict_authority") != "NONE":
        raise RuntimeError("Qualification widened verdict authority")
    if authority.get("merge_authority") != "NONE":
        raise RuntimeError("Qualification widened merge authority")

    if publication_index.get("source_head_sha1") != release_head:
        raise RuntimeError("Publication head mismatch")
    if publication_index.get("source_tree_sha1") != release_tree:
        raise RuntimeError("Publication tree mismatch")
    if publication_index.get("workflow_run_id") != release_run["id"]:
        raise RuntimeError("Publication run mismatch")
    if publication_index.get("qualification_payload_sha256") != qualification.get("payload_sha256"):
        raise RuntimeError("Publication qualification payload mismatch")
    if publication_index.get("actual_control_identities") != "UNBOUND":
        raise RuntimeError("Publication widened executable identity authority")
    if publication_index.get("provider_or_model_calls") != 0:
        raise RuntimeError("Publication widened provider/model call authority")
    if publication_index.get("numeric_stage2_freeze") != "NOT_ISSUED":
        raise RuntimeError("Publication widened numeric-freeze authority")
    if publication_index.get("live_provider_dispatch") != "PROHIBITED":
        raise RuntimeError("Publication widened dispatch authority")
    if publication_index.get("merge_authority") != "NONE":
        raise RuntimeError("Publication widened merge authority")

    target = audit_result.get("target", {})
    rederived = audit_result.get("rederived", {})
    audit_authority = audit_result.get("authority", {})
    if target.get("release_head_sha1") != release_head:
        raise RuntimeError("Audit target head mismatch")
    if target.get("release_tree_sha1") != release_tree:
        raise RuntimeError("Audit target tree mismatch")
    if target.get("qualification_run") != release_run["id"]:
        raise RuntimeError("Audit qualification run mismatch")
    if audit_result.get("failed_count") != 0:
        raise RuntimeError("Independent audit contains failures")
    if audit_result.get("refused_count") != audit_result.get("attack_count"):
        raise RuntimeError("Independent audit did not refuse all attacks")
    if audit_result.get("disposition") != "PASS_CROSS_PLATFORM_BINDER_IMPORT_ROOT_RELEASE_ONLY":
        raise RuntimeError("Independent audit disposition mismatch")
    if rederived.get("binder_import_smoke") != "PASS":
        raise RuntimeError("Independent audit did not reproduce binder import smoke")
    if rederived.get("binder_execution_cwd") != "PINNED_BINDER_ROOT":
        raise RuntimeError("Independent audit did not prove binder working directory")
    if rederived.get("binder_pythonpath") != "PINNED_BINDER_ROOT":
        raise RuntimeError("Independent audit did not prove binder Python root")
    if rederived.get("non_binder_cwd_preflight") != "PASS":
        raise RuntimeError("Independent audit did not prove non-binder caller Preflight")
    if rederived.get("actual_executable_control_identities") != "UNBOUND":
        raise RuntimeError("Independent audit widened executable identity authority")
    if audit_authority.get("provider_or_model_calls") != 0:
        raise RuntimeError("Independent audit widened provider/model call authority")
    if audit_authority.get("actual_executable_control_identities") != "UNBOUND":
        raise RuntimeError("Independent audit widened executable identity authority")
    if audit_run.get("head_sha") != audit_head:
        raise RuntimeError("Audit workflow head mismatch")
    if publication.get_tree(audit_head) != audit_tree:
        raise RuntimeError("Audit tree mismatch")


def main() -> int:
    publication.assert_exact_release = assert_exact_release
    result = publication.main()

    record_path = Path(publication.os.environ.get("PUBLICATION_OUT", "publication-record.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    release_comment_id = int(record["release_comment_id"])
    issue = publication.request("GET", f"/issues/{publication.ISSUE_NUMBER}")
    body = issue.get("body", "")
    old = "release v4                     comment pending publication in this transaction"
    new = f"release v4                     comment {release_comment_id}"
    if old in body:
        body = body.replace(old, new, 1)
        publication.request(
            "PATCH",
            f"/issues/{publication.ISSUE_NUMBER}",
            {"body": body},
        )
    refreshed = publication.request("GET", f"/issues/{publication.ISSUE_NUMBER}")
    if new not in refreshed.get("body", ""):
        raise RuntimeError("Issue body did not retain the exact release comment ID")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PUBLICATION_WRAPPER_FAILED: {exc}", file=sys.stderr)
        raise
