#!/usr/bin/env python3
"""Generate machine-derived qualification receipts for frontier fingerprint CI."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

QUALIFICATION_SCHEMA = "tier-bench/frontier-fingerprint-qualification@1"
INDEX_SCHEMA = "tier-bench/frontier-fingerprint-qualification-index@1"
MANIFEST_SCHEMA = "tier-bench/frontier-fingerprint-manifest@1"
COMMENT_MARKER = "<!-- frontier-fingerprint-qualification -->"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TEST_RE = re.compile(r"^Ran\s+(\d+)\s+tests?\s+in\s+", re.MULTILINE)
FORBIDDEN_PUBLIC_TEXT = (
    b"SENSITIVE_CANARY",
    b"AXM_ANCHOR_",
    b"Reply with",
)
PROVIDER_CREDENTIAL_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
)


class QualificationError(ValueError):
    """Raised when a claimed qualification cannot be derived from the inputs."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, canonical_bytes(value).decode("utf-8"))


def _require_sha(value: str, *, name: str, width: int) -> str:
    pattern = SHA1_RE if width == 40 else SHA256_RE
    normalized = value.strip().lower()
    if not pattern.fullmatch(normalized):
        raise QualificationError(f"{name} must be a {width}-character lowercase hex digest")
    return normalized


def _optional_sha(value: str | None, *, name: str, width: int) -> str | None:
    if value is None or not value.strip():
        return None
    return _require_sha(value, name=name, width=width)


def parse_test_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    matches = TEST_RE.findall(text)
    if len(matches) != 1:
        raise QualificationError(
            f"{path}: expected exactly one unittest count, observed {len(matches)}"
        )
    count = int(matches[0])
    if count <= 0:
        raise QualificationError(f"{path}: test count must be positive")
    return {
        "path": path.name,
        "count": count,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_nul_paths(path: Path) -> list[str]:
    raw = path.read_bytes()
    values = [part.decode("utf-8") for part in raw.split(b"\0") if part]
    normalized = sorted(set(values))
    if not normalized:
        raise QualificationError("changed-path inventory is empty")
    for value in normalized:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise QualificationError(f"unsafe changed path: {value}")
    return normalized


def inspect_public_file(path: Path, *, label: str) -> dict[str, Any]:
    data = path.read_bytes()
    for marker in FORBIDDEN_PUBLIC_TEXT:
        if marker in data:
            raise QualificationError(
                f"{label} retains forbidden public text marker {marker.decode('ascii')}"
            )
    return {
        "label": label,
        "path": path.name,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }



def recognized_provider_credentials_present(
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    source = os.environ if environ is None else environ
    return [name for name in PROVIDER_CREDENTIAL_ENV_NAMES if source.get(name)]


def inspect_manifest(path: Path) -> dict[str, Any]:
    manifest = load_json(path)
    if not isinstance(manifest, dict):
        raise QualificationError(f"{path}: manifest must be an object")
    execution = manifest.get("execution")
    subject = manifest.get("subject")
    if not isinstance(execution, dict) or not isinstance(subject, dict):
        raise QualificationError(f"{path}: missing execution or subject object")
    allow_live = execution.get("allow_live")
    ceiling = execution.get("max_estimated_usd")
    if allow_live is not False or ceiling != 0:
        raise QualificationError(
            f"{path}: committed qualification manifests must disable live dispatch and price"
        )
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "campaign_id": manifest.get("campaign_id"),
        "provider": subject.get("provider"),
        "adapter": subject.get("adapter"),
        "allow_live": allow_live,
        "max_estimated_usd": ceiling,
    }



def discover_manifests(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise QualificationError(f"manifest root is not a directory: {root}")
    manifests: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        value = load_json(path)
        if isinstance(value, dict) and value.get("schema") == MANIFEST_SCHEMA:
            manifests.append(inspect_manifest(path))
    if not manifests:
        raise QualificationError(f"no {MANIFEST_SCHEMA} objects found under {root}")
    return manifests


def _int_field(value: dict[str, Any], field: str) -> int:
    observed = value.get(field)
    if isinstance(observed, bool) or not isinstance(observed, int):
        raise QualificationError(f"verification.{field} must be an integer")
    if observed < 0:
        raise QualificationError(f"verification.{field} must be non-negative")
    return observed


def validate_campaign(
    run_result: dict[str, Any], verification: dict[str, Any], receipts_path: Path
) -> dict[str, Any]:
    if verification.get("verified") is not True:
        raise QualificationError("verification.verified is not true")
    if verification.get("termination_reason") != "completed":
        raise QualificationError("verification termination_reason is not completed")
    if run_result.get("completed") is not True:
        raise QualificationError("run result is not completed")
    if run_result.get("termination_reason") != "completed":
        raise QualificationError("run termination_reason is not completed")

    count_fields = (
        "receipt_count",
        "exact_requests_rebuilt",
        "raw_request_bodies_authenticated",
        "raw_response_bodies_authenticated",
        "usage_objects_rederived",
        "identity_objects_rederived",
    )
    counts = {field: _int_field(verification, field) for field in count_fields}
    if len(set(counts.values())) != 1 or counts["receipt_count"] <= 0:
        raise QualificationError(f"campaign evidence counts disagree: {counts}")

    planned = run_result.get("planned_request_count")
    run_receipts = run_result.get("receipt_count")
    if planned != counts["receipt_count"] or run_receipts != counts["receipt_count"]:
        raise QualificationError(
            "run-result planned_request_count and receipt_count must equal verification"
        )
    if run_result.get("provider_error_count") != 0:
        raise QualificationError("provider_error_count must be zero")
    if _int_field(verification, "identity_mismatch_count") != 0:
        raise QualificationError("identity_mismatch_count must be zero")

    receipt_lines = sum(1 for line in receipts_path.read_bytes().splitlines() if line.strip())
    if receipt_lines != counts["receipt_count"]:
        raise QualificationError(
            f"receipt line count {receipt_lines} does not equal {counts['receipt_count']}"
        )

    return {
        **counts,
        "identity_mismatch_count": 0,
        "provider_error_count": 0,
        "planned_request_count": planned,
        "termination_reason": "completed",
        "verified": True,
    }


def _payload_hash(value: dict[str, Any]) -> str:
    material = dict(value)
    material.pop("payload_sha256", None)
    return sha256_bytes(canonical_bytes(material))


def verify_payload_hash(value: dict[str, Any]) -> None:
    observed = value.get("payload_sha256")
    if not isinstance(observed, str) or not SHA256_RE.fullmatch(observed):
        raise QualificationError("payload_sha256 is absent or malformed")
    expected = _payload_hash(value)
    if observed != expected:
        raise QualificationError(f"payload_sha256 mismatch: {observed} != {expected}")


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    source_head = _require_sha(args.source_head_sha, name="source_head_sha", width=40)
    checked_out = _require_sha(args.checked_out_sha, name="checked_out_sha", width=40)
    tree_sha = _require_sha(args.tree_sha, name="tree_sha", width=40)
    base_sha = _optional_sha(args.base_sha, name="base_sha", width=40)
    if source_head != checked_out:
        raise QualificationError(
            f"checkout custody mismatch: expected {source_head}, observed {checked_out}"
        )

    changed_paths = read_nul_paths(args.changed_paths_z)
    test_suites = [parse_test_log(path) for path in args.test_log]
    test_total = sum(item["count"] for item in test_suites)

    run_result = load_json(args.run_result)
    verification = load_json(args.verification)
    summary = load_json(args.summary)
    plan = load_json(args.plan)
    if not all(isinstance(value, dict) for value in (run_result, verification, summary, plan)):
        raise QualificationError("run, verification, summary, and plan inputs must be objects")

    campaign = validate_campaign(run_result, verification, args.receipts)
    campaign_id = verification.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise QualificationError("verification.campaign_id must be a non-empty string")
    if run_result.get("campaign_id") != campaign_id:
        raise QualificationError("run-result campaign_id does not match verification")
    if summary.get("campaign_id") != campaign_id:
        raise QualificationError("summary campaign_id does not match verification")
    if summary.get("receipt_count") != campaign["receipt_count"]:
        raise QualificationError("summary receipt_count does not match verification")
    if summary.get("verification") != verification:
        raise QualificationError("summary embedded verification does not match verification.json")
    if plan.get("campaign_id") != campaign_id:
        raise QualificationError("plan campaign_id does not match verification")
    if plan.get("request_count") != campaign["planned_request_count"]:
        raise QualificationError("plan request_count does not match the run plan")

    manifests = discover_manifests(args.manifest_root)
    mock_manifests = [
        item
        for item in manifests
        if item["provider"] == "mock" and item["adapter"] == "mock"
    ]
    if len(mock_manifests) != 1:
        raise QualificationError(
            "exactly one mock provider and adapter manifest must qualify the provider-free run"
        )
    credential_names_present = recognized_provider_credentials_present()
    if credential_names_present:
        raise QualificationError(
            "recognized provider credentials are present: "
            + ", ".join(credential_names_present)
        )

    evidence_inputs: list[tuple[str, Path]] = [
        ("plan", args.plan),
        ("run_result", args.run_result),
        ("verification", args.verification),
        ("summary", args.summary),
        ("receipts", args.receipts),
    ]
    evidence_inputs.extend((f"passive_{index + 1}", path) for index, path in enumerate(args.passive))
    evidence_inputs.extend((f"test_log_{index + 1}", path) for index, path in enumerate(args.test_log))
    evidence = [inspect_public_file(path, label=label) for label, path in evidence_inputs]

    pr_number = int(args.pr_number) if args.pr_number else None
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    receipt: dict[str, Any] = {
        "schema": QUALIFICATION_SCHEMA,
        "qualification": "PASS",
        "generated_at": generated_at,
        "run": {
            "repository": args.repository,
            "event_name": args.event_name,
            "workflow": args.workflow,
            "workflow_ref": args.workflow_ref,
            "run_id": int(args.run_id),
            "run_attempt": int(args.run_attempt),
            "pr_number": pr_number,
        },
        "source": {
            "base_sha": base_sha,
            "source_head_sha": source_head,
            "checked_out_sha": checked_out,
            "tree_sha": tree_sha,
            "checkout_binding": "exact-source-head",
        },
        "scope": {
            "changed_path_count": len(changed_paths),
            "changed_paths": changed_paths,
        },
        "conformance": {
            "test_total": test_total,
            "test_suites": test_suites,
            "campaign": campaign,
        },
        "dispatch": {
            "execution_path": {
                "provider": mock_manifests[0]["provider"],
                "adapter": mock_manifests[0]["adapter"],
            },
            "live_provider_dispatch_authorized": False,
            "credential_check_scope": list(PROVIDER_CREDENTIAL_ENV_NAMES),
            "recognized_provider_credentials_present": credential_names_present,
            "network_egress_observed": "UNMEASURED",
            "manifest_discovery_root": args.manifest_root.as_posix(),
            "committed_manifests": manifests,
        },
        "measurement_authority": {
            "harness_custody": "QUALIFIED",
            "provider_free_conformance": "QUALIFIED",
            "live_provider_behavior": "UNMEASURED",
            "frontier_capability": "UNMEASURED",
            "frontier_cache_behavior": "UNMEASURED",
            "frontier_cost": "UNMEASURED",
            "frontier_routing": "UNMEASURED",
        },
        "evidence": evidence,
    }
    receipt["payload_sha256"] = _payload_hash(receipt)
    verify_payload_hash(receipt)
    return receipt


def render_comment(
    receipt: dict[str, Any],
    *,
    artifact_id: str,
    artifact_url: str,
    artifact_digest: str,
    publication_artifact_id: str = "",
    publication_artifact_url: str = "",
    publication_artifact_digest: str = "",
    comment_id: str = "",
) -> str:
    verify_payload_hash(receipt)
    if receipt.get("qualification") != "PASS":
        raise QualificationError("only PASS receipts may be rendered as qualification comments")
    artifact_id_int = int(artifact_id)
    if artifact_id_int <= 0:
        raise QualificationError("artifact_id must be positive")
    artifact_digest = _require_sha(artifact_digest, name="artifact_digest", width=64)
    if not artifact_url.startswith("https://github.com/"):
        raise QualificationError("artifact_url must be a GitHub URL")

    publication_sentence = ""
    supplied_publication = any(
        (
            publication_artifact_id,
            publication_artifact_url,
            publication_artifact_digest,
            comment_id,
        )
    )
    if supplied_publication:
        if not all(
            (
                publication_artifact_id,
                publication_artifact_url,
                publication_artifact_digest,
                comment_id,
            )
        ):
            raise QualificationError(
                "publication artifact identity and comment_id must be supplied together"
            )
        publication_id_int = int(publication_artifact_id)
        comment_id_int = int(comment_id)
        if publication_id_int <= 0 or comment_id_int <= 0:
            raise QualificationError("publication artifact and comment IDs must be positive")
        publication_digest = _require_sha(
            publication_artifact_digest, name="publication_artifact_digest", width=64
        )
        if not publication_artifact_url.startswith("https://github.com/"):
            raise QualificationError("publication_artifact_url must be a GitHub URL")
        publication_sentence = (
            f" The publication index is artifact "
            f"[`{publication_id_int}`]({publication_artifact_url}) with upload digest "
            f"`{publication_digest}`; its JSON binds PR comment `{comment_id_int}` to the "
            "qualification payload and evidence artifact."
        )

    run = receipt["run"]
    source = receipt["source"]
    scope = receipt["scope"]
    conformance = receipt["conformance"]
    campaign = conformance["campaign"]
    suite_text = ", ".join(
        f"{suite['count']} from `{suite['path']}`" for suite in conformance["test_suites"]
    )
    return (
        f"{COMMENT_MARKER}\n"
        "### Machine-derived frontier-fingerprint qualification\n\n"
        f"This object classifies GitHub Actions run `{run['run_id']}` attempt "
        f"`{run['run_attempt']}` as `PASS` for provider-free conformance of source head "
        f"`{source['source_head_sha']}` and tree `{source['tree_sha']}`. The workflow "
        f"checked out that exact source head, rather than the synthetic pull-request merge ref, "
        f"and evaluated `{scope['changed_path_count']}` changed paths against base "
        f"`{source['base_sha'] or 'UNMEASURED'}`. It executed `{conformance['test_total']}` "
        f"tests ({suite_text}) and completed a deterministic mock campaign with "
        f"`{campaign['receipt_count']}` receipts, `{campaign['exact_requests_rebuilt']}` exact "
        f"requests rebuilt, `{campaign['raw_request_bodies_authenticated']}` raw request bodies "
        f"authenticated, `{campaign['raw_response_bodies_authenticated']}` raw response bodies "
        f"authenticated, `{campaign['usage_objects_rederived']}` usage objects rederived, "
        f"`{campaign['identity_objects_rederived']}` identity objects rederived, and "
        f"`{campaign['identity_mismatch_count']}` identity mismatches.\n\n"
        f"The public-safe evidence bundle is GitHub Actions artifact "
        f"[`{artifact_id_int}`]({artifact_url}), whose upload digest is `{artifact_digest}`. "
        f"The qualification receipt payload is `{receipt['payload_sha256']}`."
        f"{publication_sentence} The workflow used the committed mock adapter, found none of "
        "the declared provider-credential "
        "environment variables, kept every committed qualification manifest at "
        "`allow_live: false` with a zero price ceiling, and records "
        "network egress as `UNMEASURED`. This receipt therefore qualifies repository custody and "
        "provider-free conformance only. Live provider behavior, frontier capability, live cache "
        "behavior, cost, and routing remain `UNMEASURED`.\n\n"
        "**Control question:** Does any proposed merge claim depend on a file, count, comment, "
        "artifact, provider observation, or status that is absent from this source tree, this "
        "workflow run, or the linked evidence artifact?\n"
    )


def build_index(args: argparse.Namespace) -> dict[str, Any]:
    receipt = load_json(args.receipt)
    if not isinstance(receipt, dict):
        raise QualificationError("receipt must be an object")
    verify_payload_hash(receipt)
    artifact_id = int(args.artifact_id)
    if artifact_id <= 0:
        raise QualificationError("artifact_id must be positive")
    artifact_digest = _require_sha(args.artifact_digest, name="artifact_digest", width=64)
    if not args.artifact_url.startswith("https://github.com/"):
        raise QualificationError("artifact_url must be a GitHub URL")
    comment_id = int(args.comment_id) if args.comment_id else None
    if comment_id is not None and comment_id <= 0:
        raise QualificationError("comment_id must be positive")
    if args.comment_url and not args.comment_url.startswith("https://github.com/"):
        raise QualificationError("comment_url must be a GitHub URL")

    value: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "run_id": receipt["run"]["run_id"],
        "run_attempt": receipt["run"]["run_attempt"],
        "source_head_sha": receipt["source"]["source_head_sha"],
        "tree_sha": receipt["source"]["tree_sha"],
        "qualification_payload_sha256": receipt["payload_sha256"],
        "evidence_artifact": {
            "id": artifact_id,
            "url": args.artifact_url,
            "digest": artifact_digest,
        },
        "pr_comment": {
            "id": comment_id,
            "url": args.comment_url or None,
        },
    }
    value["payload_sha256"] = _payload_hash(value)
    verify_payload_hash(value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="derive and validate a qualification receipt")
    collect.add_argument("--repository", required=True)
    collect.add_argument("--event-name", required=True)
    collect.add_argument("--workflow", required=True)
    collect.add_argument("--workflow-ref", required=True)
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--run-attempt", required=True)
    collect.add_argument("--pr-number", default="")
    collect.add_argument("--source-head-sha", required=True)
    collect.add_argument("--checked-out-sha", required=True)
    collect.add_argument("--tree-sha", required=True)
    collect.add_argument("--base-sha", default="")
    collect.add_argument("--changed-paths-z", type=Path, required=True)
    collect.add_argument("--test-log", type=Path, action="append", required=True)
    collect.add_argument("--run-result", type=Path, required=True)
    collect.add_argument("--verification", type=Path, required=True)
    collect.add_argument("--summary", type=Path, required=True)
    collect.add_argument("--plan", type=Path, required=True)
    collect.add_argument("--receipts", type=Path, required=True)
    collect.add_argument("--passive", type=Path, action="append", default=[])
    collect.add_argument("--manifest-root", type=Path, required=True)
    collect.add_argument("--out", type=Path, required=True)

    render = sub.add_parser("render", help="render a PR comment from a receipt and artifact")
    render.add_argument("--receipt", type=Path, required=True)
    render.add_argument("--artifact-id", required=True)
    render.add_argument("--artifact-url", required=True)
    render.add_argument("--artifact-digest", required=True)
    render.add_argument("--publication-artifact-id", default="")
    render.add_argument("--publication-artifact-url", default="")
    render.add_argument("--publication-artifact-digest", default="")
    render.add_argument("--comment-id", default="")
    render.add_argument("--out", type=Path, required=True)

    verify = sub.add_parser("verify", help="verify a generated receipt or index payload")
    verify.add_argument("--input", type=Path, required=True)
    verify.add_argument(
        "--schema",
        choices=[QUALIFICATION_SCHEMA, INDEX_SCHEMA],
        required=True,
    )

    index = sub.add_parser("index", help="bind the receipt to artifact and PR comment identities")
    index.add_argument("--receipt", type=Path, required=True)
    index.add_argument("--artifact-id", required=True)
    index.add_argument("--artifact-url", required=True)
    index.add_argument("--artifact-digest", required=True)
    index.add_argument("--comment-id", default="")
    index.add_argument("--comment-url", default="")
    index.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "collect":
            write_json_atomic(args.out, build_receipt(args))
        elif args.command == "render":
            receipt = load_json(args.receipt)
            if not isinstance(receipt, dict):
                raise QualificationError("receipt must be an object")
            write_text_atomic(
                args.out,
                render_comment(
                    receipt,
                    artifact_id=args.artifact_id,
                    artifact_url=args.artifact_url,
                    artifact_digest=args.artifact_digest,
                    publication_artifact_id=args.publication_artifact_id,
                    publication_artifact_url=args.publication_artifact_url,
                    publication_artifact_digest=args.publication_artifact_digest,
                    comment_id=args.comment_id,
                ),
            )
        elif args.command == "verify":
            value = load_json(args.input)
            if not isinstance(value, dict):
                raise QualificationError("input must be an object")
            if value.get("schema") != args.schema:
                raise QualificationError(
                    f"schema mismatch: {value.get('schema')!r} != {args.schema!r}"
                )
            verify_payload_hash(value)
        elif args.command == "index":
            write_json_atomic(args.out, build_index(args))
        else:
            raise AssertionError(args.command)
    except (QualificationError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(f"frontier-qualification: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
