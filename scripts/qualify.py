"""Hinge qualification sorter: the front door that tells an operator when NOT
to reach for the heavy machinery.

qualify.py is deterministic and makes no model call. It reads one job
contract (or a JSON array of them) and answers exactly one question: given
what is declared, which dispatch mode fits?

    not_eligible      - the machinery cannot verify this; a human does it
    single_dispatch   - one coherent change, one acceptance, no depends_on
    parallel_dispatch - several independent contracts, no depends_on edges
    driver_loop       - depends_on edges exist, or decomposition is unknown
    planner_first     - the objective classifies T4+ (route.classify; the
                        tier rules live in exactly one place)

Precedence (checked in this order, first match wins):
  1. not_eligible    - any contract fails a hard-eligibility check
  2. driver_loop      - any contract declares depends_on or
                        hints.decomposition_unknown
  3. planner_first    - any contract's objective classifies T4 or T5
  4. single_dispatch  - exactly one contract survives the above
  5. parallel_dispatch - more than one contract survives the above

This module never dispatches anything and never edits a grader, a contract,
or another agent's files. It only classifies.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

# route.py is the one place tier classification rules live; qualify.py
# imports it rather than forking the verb/scope rules (see route.py's own
# module docstring). Both scripts live in scripts/, and Python puts a
# directly-run script's own directory on sys.path[0], so this import works
# regardless of the caller's cwd.
from route import TIER_INDEX, classify

FORBIDDEN_CONTRACT_FIELDS = {"model", "arm", "tier", "vendor"}

# Vendor/model name tokens that make an acceptance command "model-ish" -
# something only a human (or another model) can judge, not a shell exit
# code. Matched as whole words, case-insensitively.
MODEL_VENDOR_TOKENS = [
    "claude", "anthropic", "gpt", "openai", "chatgpt", "codex", "sonnet",
    "haiku", "opus", "gemini", "bard", "llama", "mistral", "qwen", "deepseek",
    "grok", "copilot", "ollama", "arm_spark", "arm_haiku", "arm_luna",
    "arm_a", "arm_terra", "arm_b", "spark", "luna", "terra", "sol",
]
MODEL_ISH_WORDS = ["review", "judge", "eyeball", "approve", "approved", "approves"]
MODEL_ISH_PHRASES = ["looks good", "have a human", "manual review", "human review"]

# The acceptance-command execution timeout is 120s per spec. It is read at
# call time (not import time) from an env var so tests can exercise the
# timeout->unknown branch without a real two-minute wait; the CLI default is
# unchanged at 120s.
DEFAULT_DISCRIMINATE_TIMEOUT_SECONDS = 120.0


class QualifyError(ValueError):
    """The job file is missing, malformed, or not a contract/array of contracts."""


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def load_contracts(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise QualifyError(f"cannot read job file: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise QualifyError(f"job file is not valid JSON: {path}: {exc}") from exc
    if isinstance(raw, dict):
        items: list[Any] = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        raise QualifyError("job file must be a JSON object (one contract) or an array of contracts")
    if not items:
        raise QualifyError("job file contains no contracts")
    for item in items:
        if not isinstance(item, dict):
            raise QualifyError("each contract must be a JSON object")
    return items


# --------------------------------------------------------------------------
# eligibility: is this even verifiable by the machinery?
# --------------------------------------------------------------------------


def _contract_id(raw: dict[str, Any], index: int) -> str:
    raw_id = raw.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    return f"job-{index}"


def _model_ish_hits(acceptance: str) -> list[str]:
    lowered = acceptance.lower()
    hits: list[str] = []
    for token in MODEL_VENDOR_TOKENS + MODEL_ISH_WORDS:
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            hits.append(token)
    for phrase in MODEL_ISH_PHRASES:
        if phrase in lowered:
            hits.append(phrase)
    return hits


def _is_directory_shaped(entry: str) -> bool:
    # Mirrors route.py's own rule exactly (kept local rather than importing
    # a private helper across modules): a final path component carrying no
    # file extension, or a declared trailing slash, is an unbounded scope.
    normalized = entry.replace("\\", "/").strip()
    if normalized.endswith("/"):
        return True
    tail = normalized.rsplit("/", 1)[-1]
    return bool(tail) and "." not in tail


def _scope_issues(entry: str, repo: Path | None) -> list[str]:
    issues: list[str] = []
    value = entry.strip().replace("\\", "/")
    if not value:
        return [f"empty scope entry: {entry!r}"]
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        issues.append(f"is an absolute path: {entry!r}")
    pure = PurePosixPath(value.rstrip("/"))
    if not pure.parts or ".." in pure.parts or pure.parts[0] == ".git":
        issues.append(f"escapes the repo: {entry!r}")
    if _is_directory_shaped(entry):
        issues.append(f"is directory-shaped / unbounded: {entry!r}")
    if repo is not None and not issues:
        candidate = (repo / Path(*pure.parts)).resolve()
        try:
            candidate.relative_to(repo.resolve())
        except ValueError:
            issues.append(f"resolves outside --repo: {entry!r}")
    return issues


def evaluate_contract(raw: dict[str, Any], index: int, repo: Path | None) -> dict[str, Any]:
    cid = _contract_id(raw, index)
    reasons: list[str] = []

    for field in sorted(FORBIDDEN_CONTRACT_FIELDS & set(raw)):
        reasons.append(
            f"forbidden_field: contract {cid} names a {field!r} field directly ({raw[field]!r}); "
            "a job contract must never name a model/arm/tier/vendor"
        )

    objective = raw.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        reasons.append(f"missing_objective: contract {cid} has no non-empty 'objective'")
        objective = None
    else:
        objective = objective.strip()

    files_raw = raw.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        reasons.append(f"missing_files: contract {cid} has no non-empty 'files' list")
        files: list[str] = []
    else:
        files = [str(entry) for entry in files_raw]
        for entry in files:
            for issue in _scope_issues(entry, repo):
                reasons.append(f"scope: contract {cid} file {issue}")

    acceptance = raw.get("acceptance")
    if not isinstance(acceptance, str) or not acceptance.strip():
        reasons.append(f"no_acceptance: contract {cid} has no acceptance command")
        acceptance = None
    else:
        acceptance = acceptance.strip()
        hits = _model_ish_hits(acceptance)
        if hits:
            reasons.append(
                f"model_ish_acceptance: contract {cid} acceptance {acceptance!r} mentions "
                f"{', '.join(sorted(set(hits)))} - a human judges this, not an exit code"
            )

    depends_raw = raw.get("depends_on") or []
    depends_on = [str(dep) for dep in depends_raw] if isinstance(depends_raw, list) else []

    hints = raw.get("hints") if isinstance(raw.get("hints"), dict) else {}
    decomposition_unknown = bool(hints.get("decomposition_unknown"))

    return {
        "id": cid,
        "objective": objective,
        "files": files,
        "acceptance": acceptance,
        "depends_on": depends_on,
        "decomposition_unknown": decomposition_unknown,
        "eligible": not reasons,
        "eligibility_reasons": reasons,
        "tier": None,
        "tier_reasons": [],
        "discriminates": None,
    }


# --------------------------------------------------------------------------
# discriminative precheck (optional, --check-discriminates)
# --------------------------------------------------------------------------


def run_discriminate_check(acceptance: str, repo: Path) -> bool | None:
    """True iff the acceptance command exits nonzero before any patch. None on timeout."""
    timeout = float(os.environ.get("QUALIFY_DISCRIMINATE_TIMEOUT_SECONDS", DEFAULT_DISCRIMINATE_TIMEOUT_SECONDS))
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        result = subprocess.run(
            acceptance, shell=True, cwd=repo, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return None
    return result.returncode != 0


# --------------------------------------------------------------------------
# mode determination
# --------------------------------------------------------------------------


VERDICT_TAIL = {
    "not_eligible": "the machinery cannot verify this; a human does it",
    "single_dispatch": "do not use the driver loop; one desk task or tier run is correct",
    "parallel_dispatch": "dispatch concurrently; still no DAG",
    "driver_loop": "the DAG earns its keep",
    "planner_first": "plan before dispatch",
}


def build_verdict(mode: str) -> str:
    return f"{mode}: {VERDICT_TAIL[mode]}"


def qualify(
    contracts_raw: list[dict[str, Any]], repo: Path | None, check_discriminates: bool = False
) -> dict[str, Any]:
    contracts = [evaluate_contract(raw, index, repo) for index, raw in enumerate(contracts_raw)]
    reasons: list[str] = []
    for contract in contracts:
        reasons.extend(contract["eligibility_reasons"])

    if any(not contract["eligible"] for contract in contracts):
        mode = "not_eligible"
    else:
        depends_edges = [contract for contract in contracts if contract["depends_on"]]
        unknown_decomp = [contract for contract in contracts if contract["decomposition_unknown"]]
        if depends_edges or unknown_decomp:
            mode = "driver_loop"
            for contract in depends_edges:
                reasons.append(
                    f"depends_on: contract {contract['id']} depends on {', '.join(contract['depends_on'])}"
                )
            for contract in unknown_decomp:
                reasons.append(
                    f"decomposition_unknown: hints.decomposition_unknown is true on contract {contract['id']}"
                )
        else:
            t4_hits: list[tuple[dict[str, Any], str]] = []
            for contract in contracts:
                job = {
                    "objective": contract["objective"],
                    "files": contract["files"],
                    "acceptance": contract["acceptance"],
                }
                tier, tier_reasons = classify(job)
                contract["tier"] = tier
                contract["tier_reasons"] = tier_reasons
                if TIER_INDEX[tier] >= TIER_INDEX["T4"]:
                    t4_hits.append((contract, tier))
            if t4_hits:
                mode = "planner_first"
                for contract, tier in t4_hits:
                    reasons.append(
                        f"planner_first: contract {contract['id']} objective classifies {tier} via "
                        f"route.classify ({'; '.join(contract['tier_reasons'])})"
                    )
            elif len(contracts) == 1:
                mode = "single_dispatch"
                reasons.append(
                    f"single_dispatch: contract {contracts[0]['id']} is one coherent change, "
                    "one acceptance, no depends_on"
                )
            else:
                mode = "parallel_dispatch"
                reasons.append(
                    f"parallel_dispatch: {len(contracts)} independent contracts, no depends_on edges"
                )

    if check_discriminates:
        assert repo is not None  # enforced by the CLI before qualify() is called
        for contract in contracts:
            if contract["acceptance"]:
                contract["discriminates"] = run_discriminate_check(contract["acceptance"], repo)

    checked_values = [contract["discriminates"] for contract in contracts if contract["acceptance"]]
    if not check_discriminates or not checked_values:
        discriminates: bool | None = None
    elif any(value is False for value in checked_values):
        discriminates = False
    elif any(value is None for value in checked_values):
        discriminates = None
    else:
        discriminates = True

    return {
        "mode": mode,
        "reasons": reasons,
        "contracts": contracts,
        "discriminates": discriminates,
        "verdict": build_verdict(mode),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qualify.py",
        description="Hinge qualification sorter: deterministically decide whether a job contract "
        "(or array of contracts) belongs on single dispatch, parallel dispatch, the driver loop, "
        "a planner first, or is not machine-verifiable at all.",
    )
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--check-discriminates", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _discriminates_text(value: bool | None) -> str:
    return "unknown" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check_discriminates and args.repo is None:
        print("qualify.py: --check-discriminates requires --repo", file=sys.stderr)
        return 2

    try:
        contracts_raw = load_contracts(args.job)
    except QualifyError as exc:
        print(f"qualify.py: {exc}", file=sys.stderr)
        return 2

    repo = args.repo.expanduser().resolve() if args.repo is not None else None
    result = qualify(contracts_raw, repo, check_discriminates=args.check_discriminates)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"mode: {result['mode']}")
    print("reasons:")
    if result["reasons"]:
        for reason in result["reasons"]:
            print(f"  - {reason}")
    else:
        print("  (none)")
    print("contracts:")
    for contract in result["contracts"]:
        print(
            f"  - id={contract['id']} eligible={contract['eligible']} "
            f"tier={contract['tier'] or '-'} discriminates={_discriminates_text(contract['discriminates'])}"
        )
    print(f"discriminates: {_discriminates_text(result['discriminates'])}")
    print(f"verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside the modeled guard paths
        print(f"qualify.py: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
