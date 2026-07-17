"""Verify the bounded, repository-custodied Sol-root continuation packet."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
PACKET = Path(__file__).resolve().parent / ".cart0"
ENTRY = "000.000.INDEX.md"
SUBJECT_FILES = (
    ENTRY,
    "000.100.AUTHORITY.md",
    "010.100.STATE.md",
    "020.100.ARTIFACTS.md",
    "300.100.NEXT_TRANSITION.md",
    "500.100.VERIFICATION.md",
    "ENTRY_PROMPT.txt",
)
RECEIPT = "700.100.RECEIPT.json"
MAX_SUBJECT_FILE_BYTES = 2_500
MAX_SUBJECT_TOTAL_BYTES = 10_000
MAX_RECEIPT_BYTES = 5_500
REPO_POINTERS = (
    "docs/agents/QUEUE.md",
    "experiments/sol_root_matched_config/PROTOCOL_PROPOSAL_V0_2.md",
    "experiments/sol_root_matched_config/CLOSURE_PACKET_V0_2.json",
    "experiments/sol_root_matched_config/compile_proposal.py",
    "experiments/sol_root_matched_config/design_proposal_v0_2.json",
    "experiments/sol_root_matched_config/display_inventory_v0_2.json",
    "experiments/sol_root_matched_config/fixtures/model_catalog_fixture_v0_2.json",
    "experiments/sol_root_matched_config/generated",
    "tests/test_sol_root_matched_config.py",
    "experiments/sol_root_matched_config/verify_continuation.py",
    "tests/test_sol_root_continuation.py",
    ".github/workflows/breadth-durability.yml",
    "experiments/cart0_net_effect_pilot0/REPORT.md",
    "experiments/luna_sol_anchor_replication_v2",
    "experiments/luna_sol_anchor_replication_v2/SPARK_EXECUTION_SURFACE_V2_2_3_FREEZE.json",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(data: bytes) -> bytes:
    """Make text receipts stable across Git LF/CRLF worktrees."""
    return data.replace(b"\r\n", b"\n")


def inspect_packet(packet: Path = PACKET, verifier: Path | None = None) -> dict:
    verifier = verifier or Path(__file__)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: object) -> None:
        checks.append({"name": name, "pass": bool(passed), "detail": detail})

    data: dict[str, bytes] = {}
    for name in SUBJECT_FILES:
        path = packet / name
        check(f"exists:{name}", path.is_file(), str(path))
        if path.is_file():
            data[name] = normalized(path.read_bytes())

    sizes = {name: len(content) for name, content in data.items()}
    check("subject_file_size_limit", bool(sizes) and all(size <= MAX_SUBJECT_FILE_BYTES for size in sizes.values()), sizes)
    total = sum(sizes.values())
    check("subject_total_size_limit", total <= MAX_SUBJECT_TOTAL_BYTES, total)

    text = {name: content.decode("utf-8") for name, content in data.items()}
    index = text.get(ENTRY, "")
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", index)
    expected_links = set(SUBJECT_FILES[1:]) | {RECEIPT}
    check("index_links_complete", set(links) == expected_links, links)
    check("index_links_resolve", all(link == RECEIPT or (packet / link).is_file() for link in links), links)

    authority = text.get("000.100.AUTHORITY.md", "").lower()
    required_authority = [
        "no provider call",
        "gated unless",
        "never treat a proposal ceiling as call authority",
        "preserve every prior raw output and receipt",
        "check `docs/agents/queue.md`",
    ]
    check("authority_prohibitions", all(term in authority for term in required_authority), required_authority)

    entry = text.get("ENTRY_PROMPT.txt", "").lower()
    check("entry_routes_to_index", "experiments/sol_root_matched_config/.cart0/000.000.index.md" in entry, ENTRY)
    check("entry_denies_provider_calls", "no provider call" in entry, True)

    combined = "\n".join(text.values()).lower()
    forbidden_commands = ["codex exec", "--model gpt-", "provider.invoke", "run_benchmark"]
    check("no_provider_command", not any(term in combined for term in forbidden_commands), forbidden_commands)
    missing_repo = [pointer for pointer in REPO_POINTERS if not (ROOT / pointer).exists()]
    check("repo_pointers_resolve", not missing_repo, missing_repo)

    hashes = {name: sha256(content) for name, content in sorted(data.items())}
    receipt = {
        "schema": "tier_bench.sol_root_continuation_receipt.v0.2",
        "entry_address": ENTRY,
        "packet_root": "experiments/sol_root_matched_config/.cart0",
        "limits": {
            "max_subject_file_bytes": MAX_SUBJECT_FILE_BYTES,
            "max_subject_total_bytes": MAX_SUBJECT_TOTAL_BYTES,
            "max_receipt_bytes": MAX_RECEIPT_BYTES,
        },
        "observed": {
            "subject_files": len(data),
            "subject_total_bytes": total,
            "conservative_token_proxy_bytes_div_4": (total + 3) // 4,
        },
        "subject_sha256": hashes,
        "verifier_sha256": sha256(normalized(verifier.read_bytes())),
        "checks": checks,
        "all_pass": all(item["pass"] for item in checks),
        "provider_calls": 0,
        "scientific_observations": 0,
        "authority_created": False,
    }
    return receipt


def canonical(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def verify_committed(packet: Path = PACKET) -> dict:
    expected = inspect_packet(packet)
    receipt_path = packet / RECEIPT
    receipt_bytes = receipt_path.read_bytes() if receipt_path.is_file() else b""
    expected["checks"].append({
        "name": "receipt_size_limit",
        "pass": bool(receipt_bytes) and len(receipt_bytes) <= MAX_RECEIPT_BYTES,
        "detail": len(receipt_bytes),
    })
    expected["all_pass"] = all(item["pass"] for item in expected["checks"])
    committed = json.loads(receipt_bytes) if receipt_bytes else None
    # The stored receipt predates its own size check to avoid a circular document.
    comparable = dict(expected)
    comparable["checks"] = [item for item in expected["checks"] if item["name"] != "receipt_size_limit"]
    comparable["all_pass"] = all(item["pass"] for item in comparable["checks"])
    expected["checks"].append({
        "name": "receipt_matches_subjects",
        "pass": committed == comparable,
        "detail": str(receipt_path),
    })
    expected["all_pass"] = all(item["pass"] for item in expected["checks"])
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify"))
    args = parser.parse_args(argv)
    if args.action == "build":
        receipt = inspect_packet()
        if not receipt["all_pass"]:
            print(canonical(receipt).decode("utf-8"), file=sys.stderr)
            return 2
        (PACKET / RECEIPT).write_bytes(canonical(receipt))
    else:
        receipt = verify_committed()
    print(canonical(receipt).decode("utf-8"), end="")
    return 0 if receipt["all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
