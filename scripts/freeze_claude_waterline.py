#!/usr/bin/env python3
"""Freeze Claude Code manifests for a model-waterline protocol.

This script reads the current local Claude Code version and help surface, writes
one shared prompt template plus one committed-manifest candidate per ready
Anthropic route, and emits a binding receipt. It never runs a model and never
commits files. Commit the generated files before creating a residue campaign.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any

from tier_runner.model_waterline import (
    PROTOCOL_SCHEMA,
    WaterlineError,
    canonical,
    load_json,
    validate_protocol,
    write_json,
)

MANIFEST_SCHEMA = "tier-bench/pilot-backends@1"
ADAPTER_VERSION = "9"
ISOLATION = {
    "fresh_session_per_call": True,
    "instruction_files": False,
    "auto_memory": False,
    "conversation_carryover": False,
}
PROMPT = """You are one isolated model-waterline trial.

Governing base commit:
{{BASE_COMMIT}}

Task:
{{TASK}}

Allowed repository scope:
{{FILES}}

The external referee will run:
{{ACCEPTANCE}}

Work only inside the declared scope. Edit the necessary files directly. Do not
change the acceptance predicate, repository instructions, Git state, or files
outside the packet. Completion is determined by the external referee, not by
your narration.
"""


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_text(argv: list[str], *, binary: bool = False) -> str | bytes:
    result = subprocess.run(argv, capture_output=True)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise WaterlineError(f"command failed: {' '.join(argv)}: {detail}")
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", errors="replace").strip()


def repo_head(repo: Path) -> str:
    value = run_text(["git", "-C", str(repo), "rev-parse", "HEAD"])
    assert isinstance(value, str)
    if len(value) != 40:
        raise WaterlineError("target repository HEAD is not a full Git SHA")
    return value


def relative_path(from_dir: Path, target: Path) -> str:
    import os

    return Path(os.path.relpath(target, from_dir)).as_posix()


def manifest_for(
    *,
    route: dict[str, Any],
    protocol_commit: str,
    prompt_path: Path,
    prompt_sha256: str,
    manifest_path: Path,
    claude_bin: str,
    claude_version: str,
    help_sha256: str,
) -> dict[str, Any]:
    arm = route["arm"]
    command = [
        "python",
        "-m",
        "tier_runner.adapters.claude_code",
        "--arm",
        "{arm}",
        "--dispatch",
        "{dispatch_receipt}",
        "--prompt",
        "{prompt}",
        "--result",
        "{backend_result}",
        "--worktree",
        "{worktree}",
        "--claude-bin",
        claude_bin,
        "--claude-version",
        claude_version,
        "--claude-help-sha256",
        help_sha256,
        "--adapter-version",
        ADAPTER_VERSION,
        "--model",
        route["model_id"],
        "--effort",
        route["effort"],
        "--account",
        route.get("account", "claude-subscription"),
        "--tier",
        route.get("tier", "frontier"),
        "--surface",
        route.get("surface", "claude-code-subscription"),
        "--cost-basis",
        route.get("cost_basis", "subscription-derived"),
    ]
    return {
        "schema": MANIFEST_SCHEMA,
        "protocol_commit": protocol_commit,
        "isolation": ISOLATION,
        "tool_versions": {
            "claude_code": claude_version,
            "claude_help_sha256": help_sha256,
            "tier_claude_adapter": ADAPTER_VERSION,
        },
        "prompt_templates": {
            "waterline_task": {
                "path": relative_path(manifest_path.parent, prompt_path),
                "sha256": prompt_sha256,
            }
        },
        "arms": {
            arm: {
                "model_id": route["model_id"],
                "effort": route["effort"],
                "surface": route.get("surface", "claude-code-subscription"),
                "cost_basis": route.get("cost_basis", "subscription-derived"),
                "account": route.get("account", "claude-subscription"),
                "tier": route.get("tier", "frontier"),
                "prompt_template": "waterline_task",
                "adapter": {"command": command},
            }
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument(
        "--prompt-path",
        default="waterlines/model-waterline/prompt.md",
        help="repository-relative shared prompt template",
    )
    parser.add_argument(
        "--receipt-path",
        default="waterlines/model-waterline/MANIFEST_BINDING.json",
        help="repository-relative binding receipt",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        protocol = validate_protocol(load_json(args.protocol))
        if protocol.get("schema") != PROTOCOL_SCHEMA:
            raise WaterlineError("unexpected protocol schema")
        repo = args.repo.resolve()
        head = repo_head(repo)
        version = run_text([args.claude_bin, "--version"])
        help_bytes = run_text([args.claude_bin, "--help"], binary=True)
        assert isinstance(version, str) and isinstance(help_bytes, bytes)
        help_sha = sha_bytes(help_bytes)

        prompt_path = (repo / args.prompt_path).resolve()
        try:
            prompt_path.relative_to(repo)
        except ValueError as exc:
            raise WaterlineError("prompt path escapes target repository") from exc
        if prompt_path.exists() and not args.force:
            existing = prompt_path.read_text(encoding="utf-8")
            if existing != PROMPT:
                raise WaterlineError(
                    f"{prompt_path} exists with different bytes; use --force only after review"
                )
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(PROMPT, encoding="utf-8")
        prompt_hash = sha_bytes(prompt_path.read_bytes())

        outputs = []
        for route in protocol["routes"]:
            if route["status"] != "ready":
                continue
            if route.get("provider", "anthropic") != "anthropic":
                continue
            manifest_path = (repo / Path(*PurePosixPath(route["manifest"]).parts)).resolve()
            try:
                manifest_path.relative_to(repo)
            except ValueError as exc:
                raise WaterlineError(f"manifest path escapes repository: {route['manifest']}") from exc
            if manifest_path.exists() and not args.force:
                raise WaterlineError(f"manifest already exists: {route['manifest']}")
            manifest = manifest_for(
                route=route,
                protocol_commit=head,
                prompt_path=prompt_path,
                prompt_sha256=prompt_hash,
                manifest_path=manifest_path,
                claude_bin=args.claude_bin,
                claude_version=version,
                help_sha256=help_sha,
            )
            write_json(manifest_path, manifest)
            outputs.append(
                {
                    "route_id": route["id"],
                    "path": manifest_path.relative_to(repo).as_posix(),
                    "sha256": sha_bytes(manifest_path.read_bytes()),
                    "model_id": route["model_id"],
                    "effort": route["effort"],
                }
            )

        receipt_path = (repo / args.receipt_path).resolve()
        try:
            receipt_path.relative_to(repo)
        except ValueError as exc:
            raise WaterlineError("receipt path escapes target repository") from exc
        receipt = {
            "schema": "tier-bench/model-waterline-manifest-binding@1",
            "protocol_id": protocol["id"],
            "protocol_sha256": hashlib.sha256(
                (canonical(protocol) + "\n").encode("utf-8")
            ).hexdigest(),
            "target_head_before_commit": head,
            "claude_bin": args.claude_bin,
            "claude_version": version,
            "claude_help_sha256": help_sha,
            "adapter_version": ADAPTER_VERSION,
            "prompt": {
                "path": prompt_path.relative_to(repo).as_posix(),
                "sha256": prompt_hash,
            },
            "manifests": outputs,
            "next_action": (
                "Review and commit these exact files. Campaign creation remains blocked "
                "until the target repository HEAD contains them."
            ),
        }
        write_json(receipt_path, receipt)
        print(json.dumps({"ok": True, "manifests": len(outputs), "receipt": str(receipt_path)}, indent=2))
        return 0
    except (WaterlineError, OSError, ValueError) as exc:
        print(f"freeze-waterline: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
