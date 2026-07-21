"""Validate a job contract against the frozen v1 shape (schemas/job_contract.schema.json).

Stdlib only: this reimplements the schema's checks directly rather than
depending on the `jsonschema` package, so the chat-bridge round trip
(docs/chat-bridge.md) never needs anything installed beyond a Python 3.12
interpreter.

Usage:
    python -B scripts/validate_contract.py <file.json|-> [--json]

Exit codes:
    0   contract is valid
    1   contract is invalid (each violation is printed)
    2   input is unreadable or not valid JSON

HARD RULE enforced here (not just documented in the schema): a contract that
names a "model", "arm", "tier", "vendor", or "provider" is invalid. The
contract describes work; a router decides who performs it. That is what lets
a contract outlive whichever model happened to exist when it was written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

REQUIRED_TOP_FIELDS = ("schema", "objective", "files", "acceptance")
OPTIONAL_TOP_FIELDS = ("id", "limits", "depends_on")
ALLOWED_TOP_FIELDS = frozenset(REQUIRED_TOP_FIELDS) | frozenset(OPTIONAL_TOP_FIELDS)

MODEL_NAMING_KEYS = ("model", "arm", "tier", "vendor", "provider")

ALLOWED_LIMITS_FIELDS = frozenset({"max_files_changed", "max_rounds"})

CONTRACT_SCHEMA_CONST = "tier-bench/job-contract@1"


class InputError(ValueError):
    """The input file/stream could not be read or is not valid JSON."""


def load_raw(source: str) -> Any:
    try:
        if source == "-":
            text = sys.stdin.read()
        else:
            text = Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read input: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"input is not valid JSON: {exc}") from exc


def _normalized_scope(entry: str) -> str:
    return entry.strip().replace("\\", "/")


def _is_unsafe_scope(entry: str) -> bool:
    value = _normalized_scope(entry)
    if not value:
        return True
    if value.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:", value):
        return True
    pure = PurePosixPath(value.rstrip("/"))
    if not pure.parts:
        return True
    if ".." in pure.parts:
        return True
    if pure.parts[0] == ".git":
        return True
    return False


def _check_model_naming(raw: dict[str, Any]) -> list[str]:
    violations = []
    for key in MODEL_NAMING_KEYS:
        if key in raw:
            violations.append(
                f'model-naming rejection: contract must not include "{key}" '
                f"(found {key!r}: {raw[key]!r}) — the contract describes work, "
                f"not who performs it; a router chooses the model, arm, tier, "
                f"or vendor, and that choice must not be frozen into the contract"
            )
    return violations


def _check_schema_field(raw: dict[str, Any]) -> list[str]:
    if "schema" not in raw:
        return ['missing required field: "schema"']
    schema = raw["schema"]
    if schema != CONTRACT_SCHEMA_CONST:
        return [f'"schema" must be exactly {CONTRACT_SCHEMA_CONST!r}, got {schema!r}']
    return []


def _check_id_field(raw: dict[str, Any]) -> list[str]:
    if "id" not in raw:
        return []
    value = raw["id"]
    if not isinstance(value, str) or not ID_RE.match(value):
        return [f'"id", if present, must match {ID_RE.pattern!r}, got {value!r}']
    return []


def _check_objective_field(raw: dict[str, Any]) -> list[str]:
    if "objective" not in raw:
        return ['missing required field: "objective"']
    value = raw["objective"]
    if not isinstance(value, str) or not value.strip():
        return ['"objective" must be a non-empty string']
    return []


def _check_files_field(raw: dict[str, Any]) -> list[str]:
    if "files" not in raw:
        return ['missing required field: "files"']
    files = raw["files"]
    if not isinstance(files, list) or not files:
        return ['"files" must be a non-empty list']
    violations: list[str] = []
    for entry in files:
        if not isinstance(entry, str) or not entry.strip():
            violations.append(f'"files" entries must be non-empty strings, got {entry!r}')
            continue
        if _is_unsafe_scope(entry):
            violations.append(
                f'"files" entry {entry!r} is not a safe repo-relative scope '
                f'(must be relative, contain no "..", and not reach into .git)'
            )
    return violations


def _check_acceptance_field(raw: dict[str, Any]) -> list[str]:
    if "acceptance" not in raw:
        return ['missing required field: "acceptance"']
    value = raw["acceptance"]
    if not isinstance(value, str) or not value.strip():
        return ['"acceptance" must be a non-empty string (one shell command)']
    if "\n" in value or "\r" in value:
        return ['"acceptance" must be a single shell command (no newlines)']
    return []


def _check_limits_field(raw: dict[str, Any]) -> list[str]:
    if "limits" not in raw:
        return []
    limits = raw["limits"]
    if not isinstance(limits, dict):
        return ['"limits", if present, must be an object']
    violations: list[str] = []
    for key in limits:
        if key not in ALLOWED_LIMITS_FIELDS:
            violations.append(f'"limits" has unknown key {key!r}; allowed: {sorted(ALLOWED_LIMITS_FIELDS)}')
    for key in ("max_files_changed", "max_rounds"):
        if key not in limits:
            continue
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            violations.append(f'"limits.{key}", if present, must be an integer >= 1, got {value!r}')
    return violations


def _check_depends_on_field(raw: dict[str, Any]) -> list[str]:
    if "depends_on" not in raw:
        return []
    value = raw["depends_on"]
    if not isinstance(value, list):
        return ['"depends_on", if present, must be a list']
    violations: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            violations.append(f'"depends_on" entries must be non-empty strings, got {entry!r}')
    return violations


def _check_unknown_top_fields(raw: dict[str, Any]) -> list[str]:
    unexpected = sorted(set(raw) - ALLOWED_TOP_FIELDS - set(MODEL_NAMING_KEYS))
    return [f'unknown top-level field: "{key}"' for key in unexpected]


def validate(raw: Any) -> list[str]:
    """Returns a list of violation messages; empty means the contract is valid."""
    if not isinstance(raw, dict):
        return ["job contract must be a JSON object"]

    violations: list[str] = []
    violations.extend(_check_model_naming(raw))
    violations.extend(_check_schema_field(raw))
    violations.extend(_check_id_field(raw))
    violations.extend(_check_objective_field(raw))
    violations.extend(_check_files_field(raw))
    violations.extend(_check_acceptance_field(raw))
    violations.extend(_check_limits_field(raw))
    violations.extend(_check_depends_on_field(raw))
    violations.extend(_check_unknown_top_fields(raw))
    return violations


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_contract.py",
        description="Validate a job contract against the frozen tier-bench/job-contract@1 shape.",
    )
    parser.add_argument("source", metavar="file.json|-", help='contract file, or "-" for stdin')
    parser.add_argument("--json", action="store_true", help="print {valid, violations} as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw = load_raw(args.source)
    except InputError as exc:
        if args.json:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"validate_contract.py: {exc}", file=sys.stderr)
        return 2

    violations = validate(raw)
    valid = not violations

    if args.json:
        print(json.dumps({"valid": valid, "violations": violations}, ensure_ascii=False))
        return 0 if valid else 1

    if valid:
        print("valid")
        return 0
    print("invalid:")
    for violation in violations:
        print(f"  - {violation}")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside the modeled guard paths
        print(f"validate_contract.py: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
