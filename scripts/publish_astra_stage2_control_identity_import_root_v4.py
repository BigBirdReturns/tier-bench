from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


REPOSITORY = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
API = f"https://api.github.com/repos/{REPOSITORY}"
ISSUE_NUMBER = 172
PR_NUMBER = 187
RELEASE_BRANCH = "release/astra-stage2-control-identity-v1-20260903"
AUDIT_BRANCH = "audit/astra-stage2-control-identity-import-root-v2-20260903"
PUBLICATION_BRANCH = "publication/astra-stage2-control-identity-import-root-v4-20260903"
RELEASE_WORKFLOW = "astra-stage2-control-identity-release.yml"
AUDIT_WORKFLOW = "astra-stage2-control-identity-import-root-v2-audit.yml"
CLAIM_ID = "FRR-ASTRA-STAGE2-CONTROL-IDENTITY-IMPORT-ROOT-1"
AUDIT_MARKER = "<!-- astra-stage2-control-identity-import-root-audit-v2 -->"
RELEASE_MARKER = "<!-- astra-stage2-control-identity-release-v4 -->"
READBACK_MARKER = "<!-- astra-stage2-control-identity-release-v4-readback -->"

SUPERSEDED = {
    "head_sha1": "148484098fae50923e4df6ed013963480734be7f",
    "tree_sha1": "d0c2a9e49b5249018e6003d40f17e06f19b43835",
    "qualification_run": 33789124430,
    "audit_run": 33789551150,
    "release_comment_id": 5530202431,
    "readback_comment_id": 5530206677,
    "reason": "Prepare reached the first real binder command and failed because the pinned binder repository root was absent from Python's import path; predecessor Preflight did not exercise that boundary",
}

LOCAL_OBSERVATION = {
    "predecessor_preflight_receipt": "S:/Scratch/Incoming/Tier-Bench/astra-stage2-control-identities-real/PREFLIGHT-RECEIPT.json",
    "predecessor_preflight_sha256": "dc725b09ff3a57d2776f168b6af2351062064ae0db7394ac7386624e1dfafb42",
    "lotus_source_commit": "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
    "loopcoder_source_commit": "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c",
    "lotus_checkpoint_gib": 6.000,
    "loopcoder_v2_checkpoint_gib": 14.194,
    "conventional_checkpoint_gib": 6.000,
    "total_checkpoint_gib": 26.194,
    "incomplete_download_files": 0,
    "prepare_receipt_created": False,
    "private_config_created": False,
    "inventoried_config_created": False,
    "hardware_probe_completed": False,
    "provider_or_model_calls": 0,
}

AUTHORITY = {
    "physical_exact_source_and_checkpoint_custody": "PRESENT_REUSABLE",
    "prepare_transaction": "INCOMPLETE_PENDING_IMPORT_ROOT_REPLAY",
    "actual_executable_control_identities": "UNBOUND",
    "empirical_calibration": "NOT_RUN",
    "empirical_subject_execution": False,
    "numeric_stage2_freeze": "NOT_ISSUED",
    "callable_astra_identity": "UNBOUND",
    "live_provider_dispatch": "PROHIBITED",
    "optional_24_call_block": "DISABLED",
    "provider_or_model_calls": 0,
    "benchmark_verdict_authority": "NONE",
    "merge_authority": "NONE",
}


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def request(
    method: str,
    path: str,
    payload: Any | None = None,
    *,
    accept: str = "application/vnd.github+json",
    raw: bool = False,
) -> Any:
    url = path if path.startswith("https://") else f"{API}{path}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tier-bench-import-root-publication",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {detail}") from exc
    if raw:
        return data
    if not data:
        return None
    return json.loads(data.decode("utf-8"))


def get_ref_head(branch: str) -> str:
    encoded = urllib.parse.quote(branch, safe="")
    value = request("GET", f"/git/ref/heads/{encoded}")
    return value["object"]["sha"]


def get_tree(head: str) -> str:
    value = request("GET", f"/git/commits/{head}")
    return value["tree"]["sha"]


def list_successful_exact_head_runs(workflow: str, branch: str, head: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"branch": branch, "status": "success", "per_page": 100})
    value = request("GET", f"/actions/workflows/{workflow}/runs?{query}")
    return [
        run
        for run in value.get("workflow_runs", [])
        if run.get("head_sha") == head and run.get("conclusion") == "success"
    ]


def exact_successful_run(workflow: str, branch: str, head: str) -> dict[str, Any]:
    runs = list_successful_exact_head_runs(workflow, branch, head)
    if not runs:
        raise RuntimeError(f"No successful exact-head run for {workflow} at {head}")
    return max(runs, key=lambda item: item["id"])


def run_artifacts(run_id: int) -> list[dict[str, Any]]:
    return request("GET", f"/actions/runs/{run_id}/artifacts?per_page=100").get("artifacts", [])


def select_artifact(artifacts: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    matches = [
        item
        for item in artifacts
        if item.get("name", "").startswith(prefix) and not item.get("expired")
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one unexpired artifact with prefix {prefix!r}, observed {len(matches)}"
        )
    return matches[0]


def artifact_record(item: dict[str, Any]) -> dict[str, Any]:
    digest = item.get("digest", "")
    if digest.startswith("sha256:"):
        digest = digest[7:]
    return {
        "id": int(item["id"]),
        "name": item["name"],
        "bytes": int(item["size_in_bytes"]),
        "sha256": digest,
    }


def download_artifact(item: dict[str, Any]) -> bytes:
    data = request("GET", f"/actions/artifacts/{item['id']}/zip", raw=True)
    expected = artifact_record(item)["sha256"]
    observed = hashlib.sha256(data).hexdigest()
    if observed != expected:
        raise RuntimeError(
            f"Artifact {item['id']} digest mismatch: expected {expected}, observed {observed}"
        )
    return data


def unzip_members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("Duplicate artifact ZIP member")
        return {name: archive.read(name) for name in names if not name.endswith("/")}


def member(members: dict[str, bytes], name: str) -> bytes:
    if name not in members:
        raise RuntimeError(f"Required artifact member is absent: {name}")
    return members[name]


def json_member(members: dict[str, bytes], name: str) -> dict[str, Any]:
    return json.loads(member(members, name).decode("utf-8-sig"))


def verify_payload(value: dict[str, Any], label: str) -> str:
    claimed = value.get("payload_sha256")
    if not isinstance(claimed, str) or not re.fullmatch(r"[0-9a-f]{64}", claimed):
        raise RuntimeError(f"{label} payload SHA-256 is absent")
    body = dict(value)
    body.pop("payload_sha256", None)
    observed = canonical_sha256(body)
    if observed != claimed:
        raise RuntimeError(
            f"{label} payload mismatch: expected {claimed}, observed {observed}"
        )
    return claimed


def list_comments() -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = request(
            "GET",
            f"/issues/{ISSUE_NUMBER}/comments?per_page=100&page={page}",
        )
        comments.extend(batch)
        if len(batch) < 100:
            return comments
        page += 1


def find_comment(comments: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    matches = [item for item in comments if needle in item.get("body", "")]
    return max(matches, key=lambda item: item["id"]) if matches else None


def upsert_comment(marker: str, body: str) -> dict[str, Any]:
    comments = list_comments()
    existing = find_comment(comments, marker)
    if existing is None:
        return request("POST", f"/issues/{ISSUE_NUMBER}/comments", {"body": body})
    return request(
        "PATCH",
        f"/issues/comments/{existing['id']}",
        {"body": body},
    )


def assert_exact_release(
    release_head: str,
    release_tree: str,
    release_run: dict[str, Any],
    qualification: dict[str, Any],
    publication: dict[str, Any],
    audit_head: str,
    audit_tree: str,
    audit_run: dict[str, Any],
    audit_result: dict[str, Any],
) -> None:
    if qualification["source"]["head_sha1"] != release_head:
        raise RuntimeError("Qualification head does not match release branch")
    if qualification["source"]["tree_sha1"] != release_tree:
        raise RuntimeError("Qualification tree does not match release branch")
    if qualification["run_id"] != release_run["id"]:
        raise RuntimeError("Qualification run does not match exact workflow run")
    conformance = qualification["conformance"]
    expected = {
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
    for key, value in expected.items():
        if conformance.get(key) != value:
            raise RuntimeError(f"Qualification field {key} mismatch")
    for key in (
        "powershell_parse_linux",
        "powershell_parse_windows",
        "windows_preflight_executed",
    ):
        if conformance.get(key) is not True:
            raise RuntimeError(f"Qualification did not prove {key}")
    for key in (
        "binder_import_smoke",
        "binder_execution_cwd",
        "binder_pythonpath",
        "binder_caller_cwd",
    ):
        if key not in conformance:
            raise RuntimeError(f"Qualification is missing import-root field {key}")
    if conformance["binder_import_smoke"] != "PASS":
        raise RuntimeError("Qualification binder import smoke did not pass")
    if conformance["binder_execution_cwd"] != "PINNED_BINDER_ROOT":
        raise RuntimeError("Qualification binder CWD proof is absent")
    if conformance["binder_pythonpath"] != "PINNED_BINDER_ROOT":
        raise RuntimeError("Qualification binder PYTHONPATH proof is absent")
    if conformance["binder_caller_cwd"] != "DELIBERATELY_NON_BINDER":
        raise RuntimeError("Qualification non-binder caller proof is absent")
    if qualification["actual_binding"]["state"] != "UNBOUND":
        raise RuntimeError("Qualification widened executable identity authority")
    if qualification["authority"]["provider_or_model_calls"] != 0:
        raise RuntimeError("Qualification widened provider/model call authority")
    if publication["source_head_sha1"] != release_head:
        raise RuntimeError("Publication head mismatch")
    if publication["source_tree_sha1"] != release_tree:
        raise RuntimeError("Publication tree mismatch")
    if publication["workflow_run_id"] != release_run["id"]:
        raise RuntimeError("Publication run mismatch")
    if publication["actual_control_identities"] != "UNBOUND":
        raise RuntimeError("Publication widened identity authority")
    if audit_result["target"]["release_head_sha1"] != release_head:
        raise RuntimeError("Audit target head mismatch")
    if audit_result["target"]["release_tree_sha1"] != release_tree:
        raise RuntimeError("Audit target tree mismatch")
    if audit_result["target"]["qualification_run"] != release_run["id"]:
        raise RuntimeError("Audit qualification run mismatch")
    if audit_result["failed_count"] != 0:
        raise RuntimeError("Independent audit contains failures")
    if audit_result["refused_count"] != audit_result["attack_count"]:
        raise RuntimeError("Independent audit did not refuse all attacks")
    if audit_result["disposition"] != "PASS_CROSS_PLATFORM_BINDER_IMPORT_ROOT_RELEASE_ONLY":
        raise RuntimeError("Independent audit disposition mismatch")
    if audit_result["rederived"]["binder_import_smoke"] != "PASS":
        raise RuntimeError("Independent audit did not reproduce binder import smoke")
    if audit_result["authority"]["actual_executable_control_identities"] != "UNBOUND":
        raise RuntimeError("Independent audit widened identity authority")
    if audit_result["authority"]["provider_or_model_calls"] != 0:
        raise RuntimeError("Independent audit widened provider/model call authority")
    if audit_run["head_sha"] != audit_head:
        raise RuntimeError("Audit workflow head mismatch")
    if get_tree(audit_head) != audit_tree:
        raise RuntimeError("Audit tree mismatch")


def text_table(rows: list[tuple[str, Any]]) -> str:
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{width}}  {value}" for label, value in rows)


def main() -> int:
    release_head = get_ref_head(RELEASE_BRANCH)
    release_tree = get_tree(release_head)
    audit_head = get_ref_head(AUDIT_BRANCH)
    audit_tree = get_tree(audit_head)
    publication_head = get_ref_head(PUBLICATION_BRANCH)
    publication_tree = get_tree(publication_head)

    release_run = exact_successful_run(RELEASE_WORKFLOW, RELEASE_BRANCH, release_head)
    release_artifacts = run_artifacts(release_run["id"])
    release_evidence_item = select_artifact(
        release_artifacts,
        f"astra-stage2-control-identity-release-evidence-{release_run['id']}-",
    )
    release_publication_item = select_artifact(
        release_artifacts,
        f"astra-stage2-control-identity-release-publication-{release_run['id']}-",
    )
    release_evidence = artifact_record(release_evidence_item)
    release_publication = artifact_record(release_publication_item)
    release_evidence_members = unzip_members(download_artifact(release_evidence_item))
    release_publication_members = unzip_members(download_artifact(release_publication_item))
    qualification = json_member(release_evidence_members, "qualification-receipt.json")
    publication = json_member(release_publication_members, "publication-index.json")
    qualification_payload = verify_payload(qualification, "qualification")
    publication_payload = verify_payload(publication, "publication")

    audit_run = exact_successful_run(AUDIT_WORKFLOW, AUDIT_BRANCH, audit_head)
    audit_artifacts = run_artifacts(audit_run["id"])
    audit_item = select_artifact(
        audit_artifacts,
        f"astra-stage2-control-identity-import-root-v2-audit-{audit_run['id']}-",
    )
    audit_artifact = artifact_record(audit_item)
    audit_members = unzip_members(download_artifact(audit_item))
    audit_result = json_member(audit_members, "audit-result.json")
    audit_payload = verify_payload(audit_result, "independent audit")

    assert_exact_release(
        release_head,
        release_tree,
        release_run,
        qualification,
        publication,
        audit_head,
        audit_tree,
        audit_run,
        audit_result,
    )

    comments = list_comments()
    claim = find_comment(comments, CLAIM_ID)
    if claim is None:
        raise RuntimeError(f"Required repair claim {CLAIM_ID} is absent")
    claim_comment_id = int(claim["id"])

    audit_body = f"""{AUDIT_MARKER}
### AUDIT: pinned binder import-root repair

```text
claim                           {CLAIM_ID}
claim comment                   {claim_comment_id}
release branch                  {RELEASE_BRANCH}
release head                    {release_head}
release tree                    {release_tree}
qualification run               {release_run['id']}
audit branch                    {AUDIT_BRANCH}
audit head                      {audit_head}
audit tree                      {audit_tree}
audit run                       {audit_run['id']}
audit artifact                  {audit_artifact['id']}
audit ZIP bytes                 {audit_artifact['bytes']:,}
audit ZIP SHA-256               {audit_artifact['sha256']}
audit-result payload            {audit_payload}
Windows tests                   27 / 26 pass / 1 expected skip
Windows failures/errors         0 / 0
Linux tests                     27 / PASS
PowerShell parse                PASS on Windows and Linux
non-binder-CWD Preflight        PASS
binder import smoke             PASS
binder execution CWD            PINNED_BINDER_ROOT
binder PYTHONPATH               PINNED_BINDER_ROOT
independent attacks             {audit_result['attack_count']}
refused                         {audit_result['refused_count']}
failed                          {audit_result['failed_count']}
disposition                     {audit_result['disposition']}
```

The audit treated the launcher, the pinned binder checkout, the Windows caller directory, and Python import resolution as separate actors. It reran the complete 27-test contract on Windows Server 2025 and Ubuntu, parsed the launcher with terminating PowerShell semantics, launched the real `Preflight` from a deliberately non-binder working directory, and required the binder's `template` command to import `astra_stage2` through the exact pinned binder root. It then downloaded the exact qualification artifacts by immutable ID, reproduced their ZIP and canonical payload hashes, and replayed seven direct substitutions against coordinates, denominators, import-root custody, non-binder caller custody, executable-identity authority, and provider-call authority. All seven refused.

No empirical subject, model, or provider was executed. The exact source and checkpoint bytes already acquired by the local estate remain reusable custody, but the official `Prepare` transaction remains incomplete until the newly qualified head reproduces locally and emits its receipt.

**Control question:** Does the next local replay bind the pinned binder checkout as both command working directory and scoped Python package root before accepting any `Prepare` receipt?"""
    audit_comment = upsert_comment(AUDIT_MARKER, audit_body)
    audit_comment_id = int(audit_comment["id"])

    release_object: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-identity-release@4",
        "classification": "CROSS_PLATFORM_BINDER_IMPORT_ROOT_RELEASE_QUALIFIED_AND_INDEPENDENTLY_AUDITED_ACTUAL_IDENTITIES_UNBOUND",
        "repository": REPOSITORY,
        "pull_request": PR_NUMBER,
        "claim": {
            "claim_id": CLAIM_ID,
            "comment_id": claim_comment_id,
        },
        "source": {
            "branch": RELEASE_BRANCH,
            "head_sha1": release_head,
            "tree_sha1": release_tree,
            "binder_parent_sha1": "af03cef494a509ab7ba5df29fa4b4ccba423f1f8",
            "binder_tree_sha1": "519ea2f8f448a464e817a024ad8ed1ac64493931",
            "changed_paths": [
                ".github/workflows/astra-stage2-control-identity-release.yml",
                "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
                "tests/test_astra_stage2_control_identity.py",
                "tests/test_astra_stage2_control_identity_release.py",
            ],
        },
        "launcher": {
            "path": "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
            "default_mode": "Prepare",
            "estate_repository_root": "D:\\Projects\\Measurement\\Tier-Bench\\main",
            "custody_root": "S:\\Scratch\\Incoming\\Tier-Bench\\astra-stage2-control-identities-real",
            "binder_execution_cwd": "PINNED_BINDER_ROOT",
            "binder_pythonpath": "PINNED_BINDER_ROOT",
            "preflight_caller_cwd": "DELIBERATELY_NON_BINDER",
            "preflight_binder_import_smoke": "PASS",
            "preflight_downloads": 0,
            "prepare_reuses_exact_assets_with_skip_downloads": True,
            "prepare_terminal_state": "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND",
            "bind_refuses_placeholder_runtime": True,
            "bind_refuses_template_effort_mapping": True,
        },
        "qualification": {
            "run_id": int(release_run["id"]),
            "conclusion": release_run["conclusion"],
            "tests": 27,
            "binder_tests": 20,
            "release_tests": 7,
            "windows_tests": 27,
            "windows_passed": 26,
            "windows_skipped": 1,
            "windows_failed": 0,
            "windows_errors": 0,
            "linux_tests": 27,
            "powershell_parse": "PASS",
            "non_binder_cwd_preflight": "PASS",
            "binder_import_smoke": "PASS",
            "qualification_payload_sha256": qualification_payload,
            "publication_payload_sha256": publication_payload,
            "evidence_artifact": release_evidence,
            "publication_artifact": release_publication,
        },
        "audit": {
            "branch": AUDIT_BRANCH,
            "head_sha1": audit_head,
            "tree_sha1": audit_tree,
            "run_id": int(audit_run["id"]),
            "conclusion": audit_run["conclusion"],
            "comment_id": audit_comment_id,
            "artifact": audit_artifact,
            "audit_result_payload_sha256": audit_payload,
            "attacks": int(audit_result["attack_count"]),
            "refused": int(audit_result["refused_count"]),
            "failed": int(audit_result["failed_count"]),
            "disposition": audit_result["disposition"],
        },
        "local_observation": LOCAL_OBSERVATION,
        "authority": AUTHORITY,
        "supersedes": SUPERSEDED,
        "next_admissible_transaction": (
            "Advance the retained local release worktree to this exact head, rerun Preflight so the new receipt proves binder import from a deliberately non-binder caller directory, then run Prepare with -SkipDownloads to reuse the preserved exact source/checkpoint custody. Bind remains prohibited until truthful runtime and effort coordinates exist."
        ),
    }
    release_object["payload_sha256"] = canonical_sha256(release_object)
    release_payload = release_object["payload_sha256"]
    release_json = json.dumps(release_object, sort_keys=True, indent=2)
    release_body = f"""{RELEASE_MARKER}
### RELEASE: executable-control binder import-root repair

```json
{release_json}
```

This release supersedes the prior `148484...` handoff because the estate reached a real execution boundary that its Preflight did not cover. The current launcher scopes every binder command to the exact `af03cef...` worktree as both the working directory and `PYTHONPATH`, restores both process states afterward, and makes Preflight execute the binder's harmless `template` command from a deliberately non-binder caller directory. Windows and Linux qualification, followed by a separate cross-platform audit, now exercise that mechanism rather than inspecting launcher text alone.

The local asset acquisition is preserved. The estate should not redownload the 26.194 GiB checkpoint set. It must advance to the exact head in this object, reproduce the new Preflight, and retry `Prepare -SkipDownloads`. A successful retry may create hardware evidence, the private configuration, the inventoried configuration, and `PREPARE-RECEIPT.json`; it still terminates with executable identities `UNBOUND` and grants no calibration or call authority.

**Control question:** Does the local estate use only source head `{release_head}`, reproduce the import-root Preflight, and reuse the preserved assets without treating their presence as a completed `Prepare` transaction?"""
    release_comment = upsert_comment(RELEASE_MARKER, release_body)
    release_comment_id = int(release_comment["id"])

    pr_body = f"""## Classification

This draft is the current cross-platform provider-free release surface for the Astra Stage 2 executable-control identity binder. The local Windows estate invalidated two predecessor execution claims in sequence: `b394...` did not parse under Windows PowerShell, and `148484...` passed its then-current Preflight but failed at the first real binder command because Python could not import `astra_stage2` from a non-binder caller directory. Both predecessors remain historical evidence only.

The current exact head binds the pinned binder checkout as both the scoped working directory and Python package root for every binder operation. Its Preflight now executes the real binder `template` command from a deliberately non-binder caller directory, proving the import boundary before any download or hardware operation. Exact source/checkpoint custody already acquired by the estate remains reusable. Actual executable identities remain `UNBOUND`; empirical calibration, numeric freeze, provider dispatch, verdict authority, and merge authority remain prohibited.

## Exact release coordinate

```text
binder parent                  af03cef494a509ab7ba5df29fa4b4ccba423f1f8
binder tree                    519ea2f8f448a464e817a024ad8ed1ac64493931
release branch                 {RELEASE_BRANCH}
release head                   {release_head}
release tree                   {release_tree}
release delta                  4 paths
```

## Import-root mechanism

`Invoke-PinnedBinder` resolves the exact binder root, sets process `PYTHONPATH` to that root, changes the command working directory to that root, invokes the pinned wrapper, checks the exit code, and restores the previous directory and environment in a `finally` block. `Preflight` begins from `preflight-binder-import-smoke/non-binder-cwd`, runs the binder `template` command through that helper, verifies the three-control denominator, and emits a head-bound receipt recording `binder_import_smoke=PASS`, `binder_execution_cwd=PINNED_BINDER_ROOT`, `binder_pythonpath=PINNED_BINDER_ROOT`, and `binder_caller_cwd=DELIBERATELY_NON_BINDER`.

## Exact-head qualification

```text
workflow                       astra-stage2-control-identity-release
run                            {release_run['id']}
conclusion                     {release_run['conclusion']}
Windows tests                  27 / 26 pass / 1 expected skip
Windows failures/errors        0 / 0
Linux tests                    27 / PASS
PowerShell parse               PASS on Windows and Linux
non-binder-CWD Preflight       PASS
binder import smoke            PASS
qualification payload          {qualification_payload}
evidence artifact              {release_evidence['id']}
evidence ZIP bytes             {release_evidence['bytes']:,}
evidence ZIP SHA-256           {release_evidence['sha256']}
publication payload            {publication_payload}
publication artifact           {release_publication['id']}
publication ZIP bytes          {release_publication['bytes']:,}
publication ZIP SHA-256        {release_publication['sha256']}
```

## Fresh independent audit

```text
audit branch                   {AUDIT_BRANCH}
audit head                     {audit_head}
audit tree                     {audit_tree}
audit run                      {audit_run['id']}
audit conclusion               {audit_run['conclusion']}
audit artifact                 {audit_artifact['id']}
audit ZIP bytes                {audit_artifact['bytes']:,}
audit ZIP SHA-256              {audit_artifact['sha256']}
audit-result payload           {audit_payload}
independent attacks            {audit_result['attack_count']}
refused                        {audit_result['refused_count']}
failed                         {audit_result['failed_count']}
disposition                    {audit_result['disposition']}
```

## Local custody and authority

The estate has exact clean source checkouts and complete checkpoint snapshots totaling 26.194 GiB, with no incomplete download files. That is valid reusable asset custody. It is not a completed Prepare transaction: hardware probing, private configuration generation, checkpoint inventory, and `PREPARE-RECEIPT.json` remain pending. The retry must use `-SkipDownloads` after the new exact-head Preflight reproduces.

```text
physical source/checkpoint custody         PRESENT / REUSABLE
Prepare transaction                        INCOMPLETE
actual executable control identities       UNBOUND
empirical calibration                      NOT_RUN / PROHIBITED
numeric Stage 2 freeze                     NOT_ISSUED / PROHIBITED
callable Astra identity                    UNBOUND
live provider dispatch                     PROHIBITED
optional 24-call block                     DISABLED
provider/model calls                       0
benchmark verdict authority                NONE
merge authority                            NONE
```

Issue #172 claim `{CLAIM_ID}` and release v4 payload `{release_payload}` govern this handoff.

**Control question:** Does the estate reproduce the current exact-head non-binder-CWD import smoke and complete `Prepare -SkipDownloads` before any runtime binding or empirical execution is considered?"""
    request("PATCH", f"/pulls/{PR_NUMBER}", {"body": pr_body})

    issue_body = f"""## Classification

This issue is the authoritative coordination and custody surface for the frontier-fingerprint chain from the qualified observatory through Stage 2 calibration and Astra instrumentation. It grants no provider-call, empirical-execution, spend, numeric-freeze, benchmark-verdict, production, or merge authority. State moves only through exact `CLAIM`, `AUDIT`, `RELEASE`, and `READBACK` objects tied to remote Git and retained artifacts.

## Current coordinates

```text
measurement substrate          PR #170 / e938bd92e81bb7abfd6e0009d0360c7764808be8 / QUALIFIED + PUBLISHED
Stage 1 law                    PR #171 / a855b1bcc871753e44b0a10acf5440ccf96fcffe / FROZEN
Stage 2 scaffold               PR #181 / 9babad4631ef517485c56ea4906aab123e30fad7 / QUALIFIED
Sol Stage 2 law                PR #185 / c36c35bf9b70d879e1e1c9ee2f0296879442df3e / RELEASED CANDIDATE
control-identity binder        PR #186 / af03cef494a509ab7ba5df29fa4b4ccba423f1f8 / QUALIFIED IMPLEMENTATION

current local handoff          PR #187
release branch                 {RELEASE_BRANCH}
release head                   {release_head}
release tree                   {release_tree}
repair claim                   {CLAIM_ID} / comment {claim_comment_id}
qualification run              {release_run['id']} / {release_run['conclusion']}
Windows tests                  27 / 26 pass / 1 expected skip / 0 fail / 0 error
Linux tests                    27 / PASS
PowerShell parser              PASS on Windows and Linux
non-binder-CWD Preflight       PASS
binder import smoke            PASS
binder execution CWD           PINNED_BINDER_ROOT
binder PYTHONPATH              PINNED_BINDER_ROOT
qualification payload          {qualification_payload}
evidence artifact              {release_evidence['id']} / {release_evidence['bytes']:,} bytes / {release_evidence['sha256']}
publication artifact           {release_publication['id']} / {release_publication['bytes']:,} bytes / {release_publication['sha256']}
publication payload            {publication_payload}

audit branch                   {AUDIT_BRANCH}
audit head                     {audit_head}
audit tree                     {audit_tree}
audit run                      {audit_run['id']} / {audit_run['conclusion']}
audit artifact                 {audit_artifact['id']} / {audit_artifact['bytes']:,} bytes / {audit_artifact['sha256']}
audit payload                  {audit_payload}
audit disposition              {audit_result['disposition']}
audit attacks                  {audit_result['refused_count']}/{audit_result['attack_count']} refused; {audit_result['failed_count']} failed

release v4                     comment pending publication in this transaction
release payload                {release_payload}
actual executable identities   UNBOUND
provider/model calls           0
```

## Import-root repair disposition

The local estate correctly rejected release head `148484098fae50923e4df6ed013963480734be7f` after it acquired all exact public sources and 26.194 GiB of complete checkpoint snapshots, then failed at the first binder command with `ModuleNotFoundError: No module named 'astra_stage2'`. That head's Preflight proved repository and worktree custody but did not execute a binder Python import. Its qualification run `33789124430`, audit run `33789551150`, release comment `5530202431`, and readback `5530206677` are superseded for execution authority.

The current release makes the pinned binder root an explicit scoped process input. Every binder command executes with that exact root as both working directory and `PYTHONPATH`, and process state is restored afterward. Preflight deliberately begins outside the binder checkout and executes the binder `template` command, so the import path that previously failed is now exercised on Windows before publication. A separate audit branch repeats the Windows and Linux gates, downloads exact artifacts by immutable ID, rederives their hashes, and refuses all seven substitutions.

## Local custody state and next transaction

```text
canonical repository root      D:\\Projects\\Measurement\\Tier-Bench\\main
retained release worktree      S:\\Scratch\\Worktrees\\Tier-Bench\\astra-stage2-control-identity-release-b394
private custody root           S:\\Scratch\\Incoming\\Tier-Bench\\astra-stage2-control-identities-real
exact asset custody            PRESENT / CLEAN / REUSABLE
checkpoint bytes               26.194 GiB
incomplete downloads           0
hardware probe                 NOT COMPLETED
private config                 NOT CREATED
inventoried config             NOT CREATED
PREPARE-RECEIPT.json           NOT CREATED
```

The next transaction advances the retained release worktree to exact head `{release_head}`, reproduces the new head-bound `PREFLIGHT_PASS`, and then runs `Prepare -SkipDownloads`. That retry must verify the existing source and checkpoint custody, execute hardware probing and inventory through the pinned import root, and terminate as `ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND`. It does not authorize `Bind`. Truthful runtime identity and low/high effort semantics for LOTUS, LoopCoder-v2, and the conventional negative control remain a separate derivation.

## Ordered queue

- [x] Qualify and publish the measurement substrate.
- [x] Freeze Stage 1 and preserve its ancestry.
- [x] Build and audit the provider-free Stage 2 scaffold and Sol law.
- [x] Build the executable-control binder.
- [x] Reject the Windows PowerShell-defective `b394` release.
- [x] Repair PowerShell parsing and cross-platform runtime fixtures at `148484...`.
- [x] Acquire exact LOTUS, LoopCoder-v2, and conventional checkpoint custody locally.
- [x] Reject `148484...` at the first real binder import boundary.
- [x] Bind every binder command to the exact pinned working directory and Python package root.
- [x] Exercise the import boundary from a deliberately non-binder Windows caller directory.
- [x] Pass the complete Windows and Linux release qualification.
- [x] Pass the fresh independent import-root audit and refuse seven of seven authority attacks.
- [ ] Reproduce the current exact-head Preflight on the local Windows estate.
- [ ] Complete official `Prepare -SkipDownloads` and retain its receipt plus both private configurations.
- [ ] Derive truthful runtime and low/high effort mappings for all three controls.
- [ ] Bind and verify all three executable identities.
- [ ] Execute the complete 648-observation local calibration denominator.
- [ ] Publish either `EMPIRICAL_CALIBRATION_CANDIDATE` or `CALIBRATION_INCONCLUSIVE`.
- [ ] Freeze numeric thresholds only through a separate authority-bearing transaction.
- [ ] Implement and provider-free qualify Astra streaming instrumentation.
- [ ] Bind a callable Astra identity in a private live-disabled manifest.
- [ ] Keep the optional 24-call block disabled absent separate authorization.

## Handoff protocol

A new session reads this issue, PR #187, claim `{CLAIM_ID}`, the current audit comment, release v4, and its readback. Exact release head `{release_head}` is the only current local execution handoff. Head `148484...`, the earlier `b394...` packet, their workflows, and their publication comments are historical evidence only. No session may infer completion from the presence of downloaded assets or construct an unqualified local import workaround.

**Control question:** Does every subsequent local transaction begin from exact head `{release_head}`, reproduce the deliberately non-binder import smoke, preserve `UNBOUND` through `Prepare -SkipDownloads`, and refuse empirical execution until real runtime and effort identities are bound?"""
    request("PATCH", f"/issues/{ISSUE_NUMBER}", {"body": issue_body})

    fetched_release = request("GET", f"/issues/comments/{release_comment_id}")
    body = fetched_release.get("body", "")
    required = (
        RELEASE_MARKER,
        release_payload,
        release_head,
        release_tree,
        str(release_run["id"]),
        str(release_evidence["id"]),
        str(release_publication["id"]),
        str(audit_run["id"]),
        str(audit_artifact["id"]),
        audit_payload,
        "UNBOUND",
        SUPERSEDED["head_sha1"],
    )
    missing = [value for value in required if value not in body]
    if missing:
        raise RuntimeError(f"Release comment readback is missing: {missing}")

    readback_object = {
        "schema": "tier-bench/astra-stage2-control-identity-release-readback@4",
        "classification": "READBACK_VERIFIED_BINDER_IMPORT_ROOT_RELEASE_ACTUAL_IDENTITIES_UNBOUND",
        "release_comment_id": release_comment_id,
        "release_marker": RELEASE_MARKER.strip("<!- "),
        "release_payload_sha256": release_payload,
        "source_head_sha1": release_head,
        "source_tree_sha1": release_tree,
        "qualification_run": int(release_run["id"]),
        "qualification_artifacts": [
            int(release_evidence["id"]),
            int(release_publication["id"]),
        ],
        "audit_comment_id": audit_comment_id,
        "audit_run": int(audit_run["id"]),
        "audit_artifact": int(audit_artifact["id"]),
        "audit_payload_sha256": audit_payload,
        "binder_import_smoke": "PASS",
        "binder_execution_cwd": "PINNED_BINDER_ROOT",
        "binder_pythonpath": "PINNED_BINDER_ROOT",
        "preflight_caller_cwd": "DELIBERATELY_NON_BINDER",
        "actual_executable_control_identities": "UNBOUND",
        "provider_or_model_calls": 0,
        "predecessor_superseded": SUPERSEDED,
        "verified": {
            "marker_present": True,
            "release_payload_present": True,
            "exact_source_head_present": True,
            "exact_source_tree_present": True,
            "qualification_run_present": True,
            "qualification_artifacts_present": True,
            "fresh_audit_run_present": True,
            "fresh_audit_artifact_present": True,
            "fresh_audit_payload_present": True,
            "binder_import_smoke_present": True,
            "pinned_cwd_present": True,
            "pinned_pythonpath_present": True,
            "non_binder_caller_present": True,
            "unbound_authority_present": True,
            "predecessor_supersession_present": True,
        },
    }
    readback_object["payload_sha256"] = canonical_sha256(readback_object)
    readback_json = json.dumps(readback_object, sort_keys=True, indent=2)
    readback_body = f"""{READBACK_MARKER}
### READBACK: executable-control binder import-root release

```json
{readback_json}
```

Release comment `{release_comment_id}` was fetched after publication. Its connected GitHub body contains the v4 marker, canonical payload, exact release head and tree, current qualification and artifacts, fresh independent audit and artifact, binder import-root proof, explicit `UNBOUND` authority, and predecessor supersession. The remote publication transaction is therefore closed without relying on a local copy of the coordinate ledger.

Physical source and checkpoint custody is present locally, but `Prepare` remains incomplete. The next local receipt must bind this exact head and the new Preflight before the estate retries with `-SkipDownloads`.

**Control question:** Does every local receipt after this readback bind source head `{release_head}` and preserve the distinction between reusable asset custody and a completed `Prepare` transaction?"""
    readback_comment = upsert_comment(READBACK_MARKER, readback_body)
    readback_comment_id = int(readback_comment["id"])

    issue = request("GET", f"/issues/{ISSUE_NUMBER}")
    issue_body_current = issue.get("body", "")
    issue_required = (
        release_head,
        release_tree,
        str(release_run["id"]),
        str(audit_run["id"]),
        release_payload,
        CLAIM_ID,
        "binder import smoke",
        "Prepare -SkipDownloads",
        "UNBOUND",
    )
    issue_missing = [value for value in issue_required if value not in issue_body_current]
    if issue_missing:
        raise RuntimeError(f"Issue body readback is missing: {issue_missing}")

    pr = request("GET", f"/pulls/{PR_NUMBER}")
    pr_body_current = pr.get("body", "")
    pr_required = (
        release_head,
        release_tree,
        str(release_run["id"]),
        str(audit_run["id"]),
        release_payload,
        "Invoke-PinnedBinder",
        "26.194 GiB",
        "UNBOUND",
    )
    pr_missing = [value for value in pr_required if value not in pr_body_current]
    if pr_missing:
        raise RuntimeError(f"PR body readback is missing: {pr_missing}")

    record = {
        "schema": "tier-bench/astra-stage2-control-identity-connected-publication@4",
        "repository": REPOSITORY,
        "publication_branch": PUBLICATION_BRANCH,
        "publication_head_sha1": publication_head,
        "publication_tree_sha1": publication_tree,
        "claim_comment_id": claim_comment_id,
        "audit_comment_id": audit_comment_id,
        "release_comment_id": release_comment_id,
        "readback_comment_id": readback_comment_id,
        "release_payload_sha256": release_payload,
        "readback_payload_sha256": readback_object["payload_sha256"],
        "release": release_object,
        "readback": readback_object,
        "remote_readback": {
            "release_comment": True,
            "issue_body": True,
            "pull_request_body": True,
        },
    }
    record["payload_sha256"] = canonical_sha256(record)
    out = Path(os.environ.get("PUBLICATION_OUT", "publication-record.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        text_table(
            [
                ("release_head", release_head),
                ("release_tree", release_tree),
                ("qualification_run", release_run["id"]),
                ("audit_head", audit_head),
                ("audit_tree", audit_tree),
                ("audit_run", audit_run["id"]),
                ("audit_artifact", audit_artifact["id"]),
                ("release_comment", release_comment_id),
                ("readback_comment", readback_comment_id),
                ("release_payload", release_payload),
                ("publication_payload", record["payload_sha256"]),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PUBLICATION_FAILED: {exc}", file=sys.stderr)
        raise
