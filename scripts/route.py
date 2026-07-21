"""Cartridge router: deterministic tier classification and accepted-local-coverage report.

This is pure policy and arithmetic. It never dispatches a task, never starts a
worker, and never calls a model. `plan` reads a job contract and a policy file
(cartridges.json) and prints the arm ladder a human (or desk_driver_loop.py's
--arm/--escalate-arms flags) should use. `report` scans the Monster Wrangler
receipts already written by prior runs and computes accepted-local-coverage
per arm, exactly as defined in the repo's monster-wrangler docs: ERROR rows
are transport/infrastructure noise and are excluded from the capability
denominator, not folded into it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any


TIER_ORDER = ["T0", "T1", "T2", "T3", "T4"]
TIER_INDEX = {tier: index for index, tier in enumerate(TIER_ORDER)}

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "cartridges.json"

# objective_verbs buckets, checked in ascending tier order; a verb may only
# appear in one bucket. Each bucket that matches at least one verb fires its
# own reason so the "MAXIMUM of every rule that fired" combination step has
# full visibility into what actually matched.
VERB_BUCKETS: list[tuple[str, list[str]]] = [
    ("T0", ["rename", "format", "sort", "lint"]),
    ("T1", ["implement", "add"]),
    ("T2", ["fix", "bug", "patch"]),
    ("T3", ["refactor", "debug", "review"]),
    (
        "T4",
        [
            "design",
            "decompose",
            "architecture",
            "delete",
            "remove",
            "drop",
            "migrate",
            "deploy",
            "destroy",
            "revoke",
        ],
    ),
]

RECEIPT_GLOB = "tier-runs/monster-wrangler/*/attempt-*/receipt.json"


def split_command(command: str) -> list[str]:
    """Split a command line without mangling Windows backslashes as escapes.

    Copied from scripts/desk_driver_loop.py so acceptance-command tokenizing
    behaves identically wherever a job contract's "acceptance" string is
    inspected.
    """
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    return list(lexer)


# --------------------------------------------------------------------------
# plan: deterministic tier classification
# --------------------------------------------------------------------------


class JobError(ValueError):
    """The job contract file is missing a required field or is malformed."""


def load_job(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobError(f"cannot read job file: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JobError(f"job file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise JobError("job contract must be a JSON object")

    objective = raw.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise JobError('job contract must have a non-empty "objective" string')

    files_raw = raw.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise JobError('job contract must have a non-empty "files" list')
    files = [str(entry).strip() for entry in files_raw]
    if any(not entry for entry in files):
        raise JobError('job contract "files" entries must be non-empty strings')

    acceptance = raw.get("acceptance")
    if not isinstance(acceptance, str) or not acceptance.strip():
        raise JobError('job contract must have a non-empty "acceptance" string')

    hints = raw.get("hints")
    if hints is not None and not isinstance(hints, dict):
        raise JobError('job contract "hints", when present, must be an object')

    return {
        "objective": objective.strip(),
        "files": files,
        "acceptance": acceptance.strip(),
        "hints": hints or {},
    }


def _scope_files_rule(files: list[str]) -> list[tuple[int, str]]:
    if len(files) > 2:
        return [(TIER_INDEX["T3"], f"scope_files: {len(files)} declared scopes (>2) => at least T3")]
    return []


def _is_directory_shaped(entry: str) -> bool:
    # A trailing slash is the declared form, but an operator writing "src/utils"
    # means the same unbounded thing. Judge on shape only (no disk access, so
    # classification stays deterministic and works before the tree exists):
    # a final component carrying no file extension is a directory.
    normalized = entry.replace("\\", "/").strip()
    if normalized.endswith("/"):
        return True
    tail = normalized.rsplit("/", 1)[-1]
    return bool(tail) and "." not in tail


def _directory_scope_rule(files: list[str]) -> list[tuple[int, str]]:
    dirs = [entry for entry in files if _is_directory_shaped(entry)]
    if dirs:
        detail = ", ".join(dirs)
        return [(TIER_INDEX["T2"], f"directory_scope: unbounded scope(s) [{detail}] => at least T2")]
    return []


def _acceptance_kind_rule(acceptance: str) -> list[tuple[int, str]]:
    fired: list[tuple[int, str]] = []
    lowered = acceptance.lower()
    if re.search(r"\bpytest\b", lowered) or re.search(r"\btests?\b", lowered):
        fired.append(
            (TIER_INDEX["T2"], f"acceptance_kind: acceptance mentions pytest/test ({acceptance!r}) => at least T2")
        )
    return fired


def _objective_verbs_rule(objective: str) -> list[tuple[int, str]]:
    lowered = objective.lower()
    fired: list[tuple[int, str]] = []
    for tier, verbs in VERB_BUCKETS:
        hits = sorted({verb for verb in verbs if re.search(rf"\b{re.escape(verb)}\b", lowered)})
        if hits:
            fired.append((TIER_INDEX[tier], f"objective_verbs: matched {', '.join(hits)} => {tier}"))
    return fired


def classify(job: dict[str, Any]) -> tuple[str, list[str]]:
    """Deterministically classify a job contract into a tier. No model call."""
    fired: list[tuple[int, str]] = []
    fired.extend(_scope_files_rule(job["files"]))
    fired.extend(_directory_scope_rule(job["files"]))
    fired.extend(_acceptance_kind_rule(job["acceptance"]))
    fired.extend(_objective_verbs_rule(job["objective"]))

    if not fired:
        # Fail upward, never downward. A verb list is never exhaustive ("purge
        # the cache", "reset the tenant"), so an unrecognised job must not land
        # on the cheapest arm by default. T2 is where the measured floor sits
        # and is the modal task; the referee catches an over-cheap guess, but
        # only after a wasted dispatch, and an under-escalated destructive job
        # is the expensive mistake.
        return "T2", ["default: no rule fired; unknown work defaults to T2, not T0"]

    tier_index = max(index for index, _ in fired)
    reasons = [reason for _, reason in fired]
    return TIER_ORDER[tier_index], reasons


# --------------------------------------------------------------------------
# shared: policy file
# --------------------------------------------------------------------------


class PolicyError(ValueError):
    pass


def load_policy(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PolicyError(f"cannot read policy file: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"policy file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError("policy file must be a JSON object")
    ladders = raw.get("ladders")
    if not isinstance(ladders, dict):
        raise PolicyError('policy file must have a "ladders" object')
    return raw


def ladder_for_tier(policy: dict[str, Any], tier: str) -> list[str]:
    ladder = policy["ladders"].get(tier)
    if not isinstance(ladder, list) or not ladder:
        raise PolicyError(f'policy has no non-empty ladder for tier "{tier}"')
    return [str(arm) for arm in ladder]


def arm_tier_labels(policy: dict[str, Any]) -> dict[str, str]:
    """Map each arm to the comma-joined tiers whose ladder contains it."""
    membership: dict[str, list[str]] = {}
    for tier in TIER_ORDER:
        for arm in policy.get("ladders", {}).get(tier, []):
            membership.setdefault(str(arm), []).append(tier)
    return {arm: ",".join(tiers) for arm, tiers in membership.items()}


# --------------------------------------------------------------------------
# report: accepted-local-coverage
# --------------------------------------------------------------------------


def default_state_dir() -> Path | None:
    """The repo's Git common dir (.git of the main checkout), or None if unresolvable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def receipt_difficulty_tier(receipt: dict[str, Any]) -> str:
    """Derive a per-attempt difficulty tier straight from the receipt, no model call.

    Reuses classify() unchanged (no forked rules): the receipt already recorded,
    at dispatch time, the same three fields a job contract needs
    (task/files/acceptance_command), so they are reassembled into a job dict
    and run through the identical plan()-time classification. A missing or
    malformed field degrades to the empty value classify()'s own rules already
    treat as a non-match (empty file list, empty strings) rather than raising,
    so a thin/legacy receipt lands on classify()'s own no-rule-fired default
    (T2) instead of crashing the report or silently under-counting difficulty.
    """
    task = receipt.get("task")
    files = receipt.get("files")
    acceptance_command = receipt.get("acceptance_command")
    job = {
        "objective": task if isinstance(task, str) else "",
        "files": [str(entry) for entry in files] if isinstance(files, list) else [],
        "acceptance": acceptance_command if isinstance(acceptance_command, str) else "",
    }
    tier, _reasons = classify(job)
    return tier


def work_key(receipt: dict[str, Any]) -> str:
    """Identity of the WORK, independent of which arm attempted it or what it was called.

    Two attempts are the same work when they were judged by the same acceptance
    command over the same declared scopes. Task ids deliberately do not enter
    this: the five-arm charclass bake-off used a distinct id per arm
    (charclass-arm-spark, charclass-arm-luna, ...) for one identical job, and
    that is exactly the case a capability comparison must be able to group.
    """
    files = receipt.get("files")
    payload = {
        "acceptance": receipt.get("acceptance_command") if isinstance(receipt.get("acceptance_command"), str) else "",
        "files": sorted(str(entry) for entry in files) if isinstance(files, list) else [],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def scan_receipts(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Tally accepted/rejected/errors per arm from every receipt.json found.

    Per the repo's verified-yield rule (docs/monster-wrangler.md): ACCEPTED
    and REJECTED are the two adjudicated capability outcomes; ERROR rows are
    transport/infrastructure noise, counted separately, and excluded from the
    coverage denominator. Any other terminal state (CANCELED, INTERRUPTED) is
    not part of this metric and is ignored. Unreadable or malformed receipts
    are skipped rather than failing the report.

    Each ACCEPTED/REJECTED receipt is additionally bucketed by its derived
    difficulty tier (see receipt_difficulty_tier) under "by_tier", so a flood
    of trivial-tier accepts cannot masquerade as broad capability (Terra P1:
    coverage is gameable when raw counts hide what was actually attempted).
    ERROR rows are not tier-bucketed; they carry no adjudicated outcome to
    attribute to a difficulty and stay purely in the flat "errors" counter.
    """
    counts: dict[str, dict[str, Any]] = {}
    root = state_dir
    if not root.exists():
        return counts
    for receipt_path in sorted(root.glob(RECEIPT_GLOB)):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        arm = receipt.get("arm")
        state = receipt.get("state")
        if not isinstance(arm, str) or not arm:
            continue
        bucket = counts.setdefault(
            arm, {"accepted": 0, "rejected": 0, "errors": 0, "by_tier": {}, "work": {}}
        )
        if state == "ACCEPTED":
            bucket["accepted"] += 1
        elif state == "REJECTED":
            bucket["rejected"] += 1
        elif state == "ERROR":
            bucket["errors"] += 1
        else:
            continue
        if state in ("ACCEPTED", "REJECTED"):
            tier = receipt_difficulty_tier(receipt)
            tier_bucket = bucket["by_tier"].setdefault(tier, {"accepted": 0, "rejected": 0})
            tier_bucket["accepted" if state == "ACCEPTED" else "rejected"] += 1
            work_bucket = bucket["work"].setdefault(
                work_key(receipt), {"accepted": 0, "rejected": 0}
            )
            work_bucket["accepted" if state == "ACCEPTED" else "rejected"] += 1
    return counts


def coverage_of(accepted: int, rejected: int) -> float | None:
    denom = accepted + rejected
    if denom == 0:
        return None
    return accepted / denom


def error_rate_of(accepted: int, rejected: int, errors: int) -> float | None:
    """errors / (accepted + rejected + errors), or null when there is no evidence at all.

    Coverage is conditional on adjudication (its denominator excludes ERROR
    rows by design; see module docstring). Printed beside it, error_rate uses
    every attempt as its denominator so a small adjudicated sample sitting
    behind a wall of ERROR rows cannot read as strong coverage evidence.
    """
    attempts = accepted + rejected + errors
    if attempts == 0:
        return None
    return errors / attempts


def shared_work_map(counts: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """work_key -> {arm -> outcome} for every piece of work at least two arms attempted.

    This is the only sound comparison this data supports. An earlier version
    ranked arms by a difficulty tier derived from the receipt's task PROSE, and
    it inverted the truth on real receipts: the local arm was credited with
    clearing T4 (its request happened to contain a T4 verb) and marked
    comparable, while the arm that actually cleared the hard hidden-graded task
    was marked not comparable. Wording is not difficulty. Only like-for-like
    work is comparable, so comparability is now an observed property of the
    evidence -- did two arms attempt the same job -- not an inference from text.
    """
    by_key: dict[str, dict[str, dict[str, int]]] = {}
    for arm, bucket in counts.items():
        for key, outcome in bucket.get("work", {}).items():
            by_key.setdefault(key, {})[arm] = dict(outcome)
    return {key: arms for key, arms in by_key.items() if len(arms) > 1}


def _is_comparable(shared_count: int) -> bool:
    """True only when this arm shares at least one job with another arm.

    Terra's tiny-denominator finding, answered structurally rather than with a
    threshold: a coverage number computed over work nobody else attempted is
    not a capability claim about anything, however many attempts back it.
    """
    return shared_count > 0


def build_report_rows(
    policy: dict[str, Any], counts: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels = arm_tier_labels(policy)
    shared = shared_work_map(counts)
    rows: list[dict[str, Any]] = []
    total_accepted = 0
    total_rejected = 0
    total_errors = 0
    for arm in sorted(counts):
        bucket = counts[arm]
        accepted, rejected, errors = bucket["accepted"], bucket["rejected"], bucket["errors"]
        total_accepted += accepted
        total_rejected += rejected
        total_errors += errors

        # Kept, but named for what it actually is: the tier the REQUEST WORDING
        # classifies to, not a measured difficulty. It is descriptive of the job
        # mix an arm was handed; it is never evidence of what an arm can do.
        by_requested_tier = {
            tier: {
                "accepted": tier_bucket["accepted"],
                "rejected": tier_bucket["rejected"],
                "coverage": coverage_of(tier_bucket["accepted"], tier_bucket["rejected"]),
            }
            for tier, tier_bucket in bucket["by_tier"].items()
        }
        shared_keys = [key for key in bucket.get("work", {}) if key in shared]
        shared_accepted = sum(bucket["work"][key]["accepted"] for key in shared_keys)
        shared_rejected = sum(bucket["work"][key]["rejected"] for key in shared_keys)

        rows.append(
            {
                "arm": arm,
                "tier": labels.get(arm, "-"),
                "accepted": accepted,
                "rejected": rejected,
                "errors": errors,
                "attempts": accepted + rejected + errors,
                "coverage": coverage_of(accepted, rejected),
                "error_rate": error_rate_of(accepted, rejected, errors),
                "by_requested_tier": by_requested_tier,
                "shared_work": len(shared_keys),
                "shared_coverage": coverage_of(shared_accepted, shared_rejected),
                "comparable": _is_comparable(len(shared_keys)),
            }
        )
    total = {
        "accepted": total_accepted,
        "rejected": total_rejected,
        "errors": total_errors,
        "attempts": total_accepted + total_rejected + total_errors,
        "coverage": coverage_of(total_accepted, total_rejected),
        "error_rate": error_rate_of(total_accepted, total_rejected, total_errors),
    }
    return rows, total


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _coverage_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def cmd_plan(args: argparse.Namespace) -> int:
    policy_path = args.policy or DEFAULT_POLICY_PATH
    try:
        job = load_job(args.job)
        policy = load_policy(policy_path)
        tier, reasons = classify(job)
        ladder = ladder_for_tier(policy, tier)
    except (JobError, PolicyError) as exc:
        print(f"route.py plan: {exc}", file=sys.stderr)
        return 2
    arm = ladder[0]
    escalate = ladder[1:]

    if args.json:
        payload = {"tier": tier, "arm": arm, "escalate": escalate, "reasons": reasons}
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"tier: {tier}")
    print(f"arm: {arm}")
    print(f"escalate: {', '.join(escalate) if escalate else '(none)'}")
    print("reasons:")
    if reasons:
        for reason in reasons:
            print(f"  - {reason}")
    else:
        print("  (none fired; default floor T0)")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    policy_path = args.policy or DEFAULT_POLICY_PATH
    try:
        policy = load_policy(policy_path)
    except PolicyError as exc:
        print(f"route.py report: {exc}", file=sys.stderr)
        return 2

    if args.state_dir is not None:
        state_dir = args.state_dir.expanduser().resolve()
    else:
        state_dir = default_state_dir()
        if state_dir is None:
            print(
                "route.py report: cannot resolve the default --state-dir "
                "(not inside a Git repository?); pass --state-dir explicitly",
                file=sys.stderr,
            )
            return 2

    counts = scan_receipts(state_dir)
    rows, total = build_report_rows(policy, counts)

    if args.json:
        arms_by_name = {row["arm"]: {k: v for k, v in row.items() if k != "arm"} for row in rows}
        payload = {
            "state_dir": str(state_dir),
            "arms": arms_by_name,
            "head_to_head": shared_work_map(counts),
            "total": total,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    header = (
        "arm",
        "tier",
        "accepted",
        "rejected",
        "errors",
        "attempts",
        "coverage",
        "error_rate",
        "shared_work",
        "shared_coverage",
        "comparable",
    )
    print("\t".join(header))
    any_incomparable = False
    for row in rows:
        marker = "" if row["comparable"] else "*"
        if marker:
            any_incomparable = True
        print(
            "\t".join(
                [
                    row["arm"] + marker,
                    row["tier"],
                    str(row["accepted"]),
                    str(row["rejected"]),
                    str(row["errors"]),
                    str(row["attempts"]),
                    _coverage_text(row["coverage"]),
                    _coverage_text(row["error_rate"]),
                    str(row["shared_work"]),
                    _coverage_text(row["shared_coverage"]),
                    "yes" if row["comparable"] else "no" + marker,
                ]
            )
        )
    print(
        "\t".join(
            [
                "TOTAL",
                "-",
                str(total["accepted"]),
                str(total["rejected"]),
                str(total["errors"]),
                str(total["attempts"]),
                _coverage_text(total["coverage"]),
                _coverage_text(total["error_rate"]),
                "-",
                "-",
                "-",
            ]
        )
    )
    if any_incomparable:
        print(
            "* comparable=false: this arm shares no adjudicated job with any other arm, so its "
            "coverage is computed over work nobody else attempted and ranks it against nothing. "
            "Compare arms on shared_coverage (same acceptance command, same scopes) or not at all; "
            "the request's wording is not a measure of difficulty."
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="route.py",
        description="Cartridge router: deterministic job->tier->arm-ladder selection, "
        "and accepted-local-coverage reporting over existing Monster Wrangler receipts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="classify a job contract into a tier and arm ladder")
    plan_parser.add_argument("--job", required=True, type=Path)
    plan_parser.add_argument("--policy", type=Path, default=None)
    plan_parser.add_argument("--json", action="store_true")

    report_parser = sub.add_parser("report", help="compute accepted-local-coverage per arm")
    report_parser.add_argument("--policy", type=Path, default=None)
    report_parser.add_argument("--state-dir", type=Path, default=None)
    report_parser.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "plan":
        return cmd_plan(args)
    if args.command == "report":
        return cmd_report(args)
    return 2  # unreachable: argparse enforces a valid subcommand


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside the modeled guard paths
        print(f"route.py: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
