#!/usr/bin/env python3
"""Validate the OSS replay field (data/oss_replay/field.jsonl) — fail closed.

The field is where captured knot grammars meet real open-source code. Every
entry must be safe to replay and honest about what it claims:

  - LICENSE: only allowlisted licenses may be vendored into this repository.
  - CUSTODY: every vendored file must exist and hash to the declared sha256;
    the upstream pin must be a full commit hash.
  - HIDDEN GRADING: the linked task manifest must exist and declare
    hidden_files + hidden_run_command (breadth-valid; gameable tasks refused).
  - CAPTURE LINKAGE: every capture_id must exist in data/capture/*.jsonl, and
    every distinct_work_item_id must be unique across the field AND distinct
    from every replay id already recorded in the capture ledger (the
    same-instance rule is enforced at admission, not remembered at replay).
  - REPLAY DISCIPLINE: status "replayed" requires at least one replay receipt
    whose file exists; entries never carry validated_replays counts — credit
    lives in the capture ledger only, written by its own gated process.

Absence of a field file is UNMEASURED, not an error (exit 0, says so).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIELD = REPO / "data/oss_replay/field.jsonl"
CAPTURE_DIR = REPO / "data/capture"

LICENSE_ALLOWLIST = {
    "PSF-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC",
}
STATUSES = {"candidate", "admitted", "replayed", "retired"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load_field(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _capture_ids() -> set[str]:
    ids = set()
    for f in sorted(CAPTURE_DIR.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("record_type") == "capture":
                    ids.add(row.get("capture_id"))
    return ids


def _capture_replay_ids() -> set[str]:
    """Every distinct work item already spent by a capture-ledger replay.
    The ledger's field name is work_item_id (hash-bound replay-receipt@1)."""
    ids = set()
    for f in sorted(CAPTURE_DIR.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                for ev in row.get("replay_evidence") or []:
                    if isinstance(ev, dict):
                        item = ev.get("work_item_id") or ev.get("distinct_work_item_id")
                        if item:
                            ids.add(item)
    return ids


def validate_entry(entry: dict, repo: Path, errors: list[str]) -> None:
    eid = entry.get("entry_id", "<missing>")
    label = f"entry {eid}"
    if entry.get("record_type") != "oss_replay_entry":
        errors.append(f"{label}: record_type must be oss_replay_entry")
    if not isinstance(eid, str) or not eid.startswith("ossrf_"):
        errors.append(f"{label}: entry_id must start with 'ossrf_'")
    if entry.get("status") not in STATUSES:
        errors.append(f"{label}: invalid status {entry.get('status')!r}")

    up = entry.get("upstream")
    if not isinstance(up, dict):
        errors.append(f"{label}: upstream must be an object")
        up = {}
    if up.get("license") not in LICENSE_ALLOWLIST:
        errors.append(f"{label}: license {up.get('license')!r} is not allowlisted "
                      f"({sorted(LICENSE_ALLOWLIST)})")
    if not isinstance(up.get("ref_commit"), str) or not HEX40.fullmatch(up["ref_commit"]):
        errors.append(f"{label}: upstream.ref_commit must be a full 40-hex commit")
    vendored = up.get("vendored_dir")
    hashes = up.get("sha256")
    if not isinstance(vendored, str) or not isinstance(hashes, dict) or not hashes:
        errors.append(f"{label}: upstream.vendored_dir and non-empty upstream.sha256 required")
    else:
        vdir = repo / vendored
        for name, want in hashes.items():
            path = vdir / name
            if not isinstance(want, str) or not HEX64.fullmatch(want):
                errors.append(f"{label}: sha256[{name}] must be a 64-hex digest")
            elif not path.is_file():
                errors.append(f"{label}: vendored file missing: {vendored}/{name}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != want:
                errors.append(f"{label}: vendored bytes drifted: {vendored}/{name}")
        if not (vdir / "LICENSE").is_file():
            errors.append(f"{label}: vendored_dir must carry the upstream LICENSE file")

    manifest_rel = entry.get("task_manifest")
    if not isinstance(manifest_rel, str) or not (repo / manifest_rel).is_file():
        errors.append(f"{label}: task_manifest does not exist: {manifest_rel}")
    else:
        try:
            manifest = json.loads((repo / manifest_rel).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{label}: task_manifest unreadable: {exc}")
        else:
            if not manifest.get("hidden_files") or not manifest.get("hidden_run_command"):
                errors.append(f"{label}: task must be hidden-graded (gameable tasks refused)")
            fixture = repo / manifest.get("fixture_dir", "")
            for hidden in manifest.get("hidden_files", []):
                if not (fixture / hidden).is_file():
                    errors.append(f"{label}: declared hidden grader missing: {hidden}")

    links = entry.get("capture_links")
    if not isinstance(links, list) or not links:
        errors.append(f"{label}: capture_links must be a non-empty list")
        links = []
    known_captures = _capture_ids()
    for link in links:
        if not isinstance(link, dict):
            errors.append(f"{label}: capture_links items must be objects")
            continue
        if link.get("capture_id") not in known_captures:
            errors.append(f"{label}: unknown capture_id {link.get('capture_id')!r} "
                          f"(not in data/capture/)")
        for key in ("relation", "distinct_work_item_id"):
            if not isinstance(link.get(key), str) or not link[key].strip():
                errors.append(f"{label}: capture_links.{key} must be non-empty")

    adm = entry.get("admission")
    if not isinstance(adm, dict):
        errors.append(f"{label}: admission must be an object")
        adm = {}
    if entry.get("status") in {"admitted", "replayed"}:
        if adm.get("license_allowlisted") is not True or adm.get("vendored_bytes_verified") is not True:
            errors.append(f"{label}: admitted entries require license_allowlisted and "
                          f"vendored_bytes_verified to be true")
        for key in ("pii", "determinism"):
            if not isinstance(adm.get(key), str) or not adm[key].strip():
                errors.append(f"{label}: admission.{key} must be a non-empty statement")

    replays = entry.get("replays")
    if not isinstance(replays, list):
        errors.append(f"{label}: replays must be a list")
        replays = []
    if entry.get("status") == "replayed" and not replays:
        errors.append(f"{label}: status 'replayed' requires at least one replay receipt")
    for r in replays:
        if not isinstance(r, dict) or not (repo / str(r.get("receipt_path", ""))).is_file():
            errors.append(f"{label}: replay receipt missing: {r.get('receipt_path')!r}")
        elif r.get("outcome") not in {"validated", "spoiled", "partial"}:
            errors.append(f"{label}: invalid replay outcome {r.get('outcome')!r}")

    if "validated_replays" in entry:
        errors.append(f"{label}: entries may not carry validated_replays — "
                      f"amortization credit lives in the capture ledger only")


def validate_field(rows: list[dict], repo: Path = REPO) -> list[str]:
    errors: list[str] = []
    seen_entries, seen_items = set(), set()
    ledger_items = _capture_replay_ids()
    for entry in rows:
        eid = entry.get("entry_id")
        if eid in seen_entries:
            errors.append(f"duplicate entry_id {eid!r}")
        seen_entries.add(eid)
        for link in entry.get("capture_links") or []:
            if isinstance(link, dict):
                item = link.get("distinct_work_item_id")
                if item in seen_items:
                    errors.append(f"entry {eid}: duplicate distinct_work_item_id {item!r} in field")
                seen_items.add(item)
                if item in ledger_items:
                    errors.append(f"entry {eid}: distinct_work_item_id {item!r} already spent "
                                  f"in the capture ledger (same-instance rule)")
        validate_entry(entry, repo, errors)
    return errors


def main() -> int:
    if not FIELD.is_file():
        print("UNMEASURED — no OSS replay field exists yet (data/oss_replay/field.jsonl)")
        return 0
    rows = _load_field(FIELD)
    errors = validate_field(rows)
    if errors:
        print(f"FAIL — {len(errors)} OSS replay field problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
    print(f"OK — {len(rows)} OSS replay entr{'y' if len(rows)==1 else 'ies'} "
          f"({', '.join(f'{v} {k}' for k, v in sorted(by_status.items()))}); "
          f"licenses allowlisted, vendored bytes verified, hidden grading present, "
          f"capture links resolve, distinct-instance rule holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
