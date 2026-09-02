#!/usr/bin/env python3
"""Verify the authenticated identity on an ARC-D B2 private audit.

This tool verifies authentication evidence only. It never reads grader bytes
and never decides admission. GitHub Actions evidence is verified with GitHub's
Sigstore/OIDC attestation verifier and an exact certificate identity. Signed
commit evidence is verified by Git and an exact OpenPGP fingerprint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess]


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_file(path: Path, label: str) -> list[str]:
    if not path.is_file() or path.is_symlink():
        return [f"{label} must be a regular non-symlink file"]
    return []


def verify_github_actions_oidc(
    artifact: Path,
    bundle: Path,
    repository: str,
    certificate_identity: str,
    source_digest: str | None = None,
    *,
    runner: Runner = subprocess.run,
) -> list[str]:
    """Verify a GitHub Actions artifact attestation fail closed."""
    errors = _regular_file(artifact, "attested artifact")
    errors.extend(_regular_file(bundle, "attestation bundle"))
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository) is None:
        errors.append("authentication repository is malformed")
    if not certificate_identity.startswith("https://github.com/") or "@refs/heads/main" not in certificate_identity:
        errors.append("OIDC certificate identity must pin a main-branch GitHub workflow")
    if errors:
        return errors
    command = [
        "gh", "attestation", "verify", str(artifact),
        "--repo", repository,
        "--bundle", str(bundle),
        "--cert-identity", certificate_identity,
        "--deny-self-hosted-runners",
        "--format", "json",
    ]
    if source_digest is not None:
        if re.fullmatch(r"[0-9a-f]{40}", source_digest) is None:
            return ["OIDC source digest must be a full 40-hex commit"]
        command.extend(["--source-digest", source_digest])
    proc = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ["GitHub Actions OIDC attestation verification failed"]
    try:
        result = json.loads(proc.stdout)
    except (TypeError, json.JSONDecodeError):
        return ["OIDC verifier did not return valid JSON"]
    if not isinstance(result, list) or not result:
        return ["OIDC verifier returned no verified attestations"]
    return []


def verify_signed_commit(
    repository: Path,
    commit: str,
    expected_fingerprint: str,
    *,
    runner: Runner = subprocess.run,
) -> list[str]:
    """Verify one exact Git commit and OpenPGP signer fingerprint."""
    if not repository.is_dir():
        return ["signed-commit repository is missing"]
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        return ["signed-commit identity requires a full 40-hex commit"]
    fingerprint = expected_fingerprint.upper()
    if re.fullmatch(r"[0-9A-F]{40,64}", fingerprint) is None:
        return ["signed-commit fingerprint is malformed"]
    exists = runner(
        ["git", "-C", str(repository), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if exists.returncode != 0:
        return ["signed audit commit is unavailable"]
    proc = runner(
        ["git", "-C", str(repository), "verify-commit", "--raw", commit],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ["audit commit signature verification failed"]
    status = f"{proc.stdout}\n{proc.stderr}".upper()
    valid = re.findall(r"\[GNUPG:\]\s+VALIDSIG\s+([0-9A-F]{40,64})", status)
    if fingerprint not in valid:
        return ["audit commit signer fingerprint mismatch"]
    return []


def _print(errors: Sequence[str]) -> int:
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("AUTHENTICATED_AUDIT_IDENTITY_VERIFIED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    oidc = sub.add_parser("github-actions-oidc")
    oidc.add_argument("--artifact", type=Path, required=True)
    oidc.add_argument("--bundle", type=Path, required=True)
    oidc.add_argument("--repository", required=True)
    oidc.add_argument("--certificate-identity", required=True)
    oidc.add_argument("--source-digest")

    signed = sub.add_parser("signed-commit")
    signed.add_argument("--repository", type=Path, required=True)
    signed.add_argument("--commit", required=True)
    signed.add_argument("--fingerprint", required=True)

    args = parser.parse_args()
    if args.mode == "github-actions-oidc":
        return _print(verify_github_actions_oidc(
            args.artifact,
            args.bundle,
            args.repository,
            args.certificate_identity,
            args.source_digest,
        ))
    return _print(verify_signed_commit(args.repository, args.commit, args.fingerprint))


if __name__ == "__main__":
    raise SystemExit(main())
