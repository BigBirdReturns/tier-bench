"""Deterministic verifier for claude cold-verification receipts.

Usage: python verify_cold_receipt.py <receipt.json>

Offline only: no network, no provider calls, no repository mutation.
Exit 0 when all checks pass, 2 otherwise; prints one JSON result object.

The portability rule this enforces is the one the 9d293e4 divergence
taught: fields another engine must *resolve* (targets, subjects) may not
carry machine-local addresses. Prose fields may quote such paths as
evidence; reference fields may not be them.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MACHINE_LOCAL = re.compile(r"^([A-Za-z]:[\\/]|/tmp/|/home/|/Users/|\\\\)")
VERDICTS = {"verified_reproduced", "verified_with_divergence", "custody_failed"}
# Fields another engine must resolve; these must be portable references.
REFERENCE_FIELDS = [
    ("target", "repo"),
    ("target", "branch"),
    ("target", "commit"),
    ("divergence", "subject"),
]


def verify(receipt_path: Path) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    raw = receipt_path.read_bytes()
    try:
        r = json.loads(raw)
        check("json_parses", True)
    except json.JSONDecodeError as exc:
        check("json_parses", False, str(exc))
        return {"checks": checks, "all_pass": False}

    check("schema_versioned",
          isinstance(r.get("schema"), str) and "@" in r.get("schema", ""),
          r.get("schema"))
    check("verdict_in_enum", r.get("verdict") in VERDICTS, r.get("verdict"))
    check("timestamp_iso8601_utc",
          bool(ISO_UTC.match(r.get("timestamp_utc", ""))),
          r.get("timestamp_utc"))

    target = r.get("target", {})
    check("target_commit_wellformed",
          bool(HEX40.match(target.get("commit", ""))), target.get("commit"))

    build = r.get("results", {}).get("build_machine_continuation_v0_3 verify", {})
    check("manifest_sha256_wellformed",
          bool(HEX64.match(build.get("manifest_sha256", ""))))
    check("artifact_commit_wellformed",
          bool(HEX40.match(build.get("artifact_commit", ""))))

    method = r.get("method", {})
    check("zero_provider_calls", method.get("provider_calls") == 0)
    check("zero_scientific_observations",
          method.get("scientific_observations") == 0)
    check("no_authority_created", method.get("authority_created") is False)

    nonportable = []
    for section, field in REFERENCE_FIELDS:
        value = r.get(section, {}).get(field, "")
        head = value.split(" ")[0] if isinstance(value, str) else ""
        if MACHINE_LOCAL.match(head):
            nonportable.append(f"{section}.{field}")
    check("reference_fields_portable", not nonportable, nonportable)

    state = r.get("state_assertion", {})
    check("no_unilateral_state_transition",
          state.get("claimed_transition") == "none",
          state.get("claimed_transition"))
    honored = state.get("prohibited_and_honored", [])
    check("prohibitions_include_no_pr_no_merge",
          "no PR" in honored and "no merge" in honored, honored)

    divergence = r.get("divergence")
    if r.get("verdict") in {"verified_with_divergence", "custody_failed"}:
        check("divergence_has_root_cause",
              isinstance(divergence, dict)
              and bool(divergence.get("root_cause"))
              and bool(divergence.get("evidence")))

    return {"checks": checks, "all_pass": all(c["pass"] for c in checks),
            "provider_calls": 0, "scientific_observations": 0}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify_cold_receipt.py <receipt.json>", file=sys.stderr)
        return 2
    result = verify(Path(argv[1]))
    print(json.dumps(result, indent=2, sort_keys=True))
    n = len(result["checks"])
    ok = sum(1 for c in result["checks"] if c["pass"])
    print(f"{'OK' if result['all_pass'] else 'FAIL'} - {ok}/{n} receipt checks; "
          "zero provider calls, zero scientific observations", file=sys.stderr)
    return 0 if result["all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
