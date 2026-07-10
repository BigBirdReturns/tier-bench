"""Merge independent control-set grades additively.

Input grades are a JSON array of {id, score, rationale}. The private key is
created by scripts/export_blind_control_packet.py. Original control-result rows
are copied unchanged except for an additive external_grades list on each probed
row. Baseline scores are preserved for agreement reporting only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

VALID_SCORES = {0, 1, 2}


def extract_json_array(text: str):
    text = text.strip()
    try:
        obj = json.loads(text)
    except Exception:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            sys.exit("Could not find a JSON array in the grades input.")
        obj = json.loads(match.group(0))
    if not isinstance(obj, list):
        sys.exit("Grades input must be a JSON array.")
    return obj


def read_jsonl(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or not rows[0].get("_meta"):
        raise ValueError(f"{path}: missing _meta row")
    return rows[0], rows[1:]


def write_jsonl(path: Path, meta: dict, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_key(path: Path) -> tuple[dict, dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if "items" in obj and "_meta" in obj:
        return obj["_meta"], obj["items"]
    return {}, obj


def validate_grades(grades: list[dict], expected_ids: set[str]) -> dict[str, dict]:
    seen = set()
    out = {}
    for idx, grade in enumerate(grades):
        if not isinstance(grade, dict):
            sys.exit(f"Grade at index {idx} is not an object.")
        oid = grade.get("id")
        if oid not in expected_ids:
            sys.exit(f"Unknown grade id: {oid!r}")
        if oid in seen:
            sys.exit(f"Duplicate grade id: {oid}")
        seen.add(oid)
        score = grade.get("score")
        if not isinstance(score, int) or isinstance(score, bool):
            sys.exit(f"Grade id {oid} has non-integer score: {score!r}")
        if score not in VALID_SCORES:
            sys.exit(f"Grade id {oid} has out-of-range score: {score!r}")
        if "rationale" not in grade:
            sys.exit(f"Grade id {oid} is missing rationale.")
        out[oid] = grade
    missing = expected_ids - seen
    if missing:
        sample = ", ".join(sorted(missing)[:5])
        sys.exit(f"Missing {len(missing)} grade id(s), e.g. {sample}")
    return out


def write_raw_artifact(grades_path: Path, out_dir: Path, grade_run_id: str, run_meta: dict) -> None:
    run_dir = out_dir / "_external_grade_runs" / grade_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_sha = sha256_file(grades_path)
    manifest_path = run_dir / "manifest.json"
    artifact_path = run_dir / "grades.raw.json"
    manifest = {**run_meta, "raw_artifact_sha256": raw_sha, "raw_artifact_file": str(artifact_path.relative_to(out_dir))}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old != manifest:
            sys.exit(f"Conflicting artifact for existing grade_run_id: {grade_run_id}")
    if artifact_path.exists() and sha256_file(artifact_path) != raw_sha:
        sys.exit(f"Conflicting raw artifact for existing grade_run_id: {grade_run_id}")
    shutil.copyfile(grades_path, artifact_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--grader", required=True, help="Declared grader provenance; use an unverified label unless independently attested.")
    ap.add_argument("--grade-run-id", required=True, help="Unique ID for this returned external grade artifact.")
    ap.add_argument("--out", default="regraded_control_results")
    args = ap.parse_args()

    grades_path = Path(args.grades)
    key_meta, key = load_key(Path(args.key))
    expected_ids = set(key)
    grades = validate_grades(extract_json_array(grades_path.read_text(encoding="utf-8")), expected_ids)
    packet_sha = key_meta.get("packet_sha256")
    source_commit = key_meta.get("source_commit")
    if not packet_sha or not source_commit:
        sys.exit("Key is missing packet_sha256 or source_commit metadata.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_meta = {
        "grade_run_id": args.grade_run_id,
        "grader": args.grader,
        "packet_sha256": packet_sha,
        "packet_source_commit": source_commit,
        "key_schema": key_meta.get("key_schema"),
        "packet_schema": key_meta.get("packet_schema"),
        "id_salt_commitment": key_meta.get("id_salt_commitment"),
        "permutation_commitment": key_meta.get("permutation_commitment"),
    }
    write_raw_artifact(grades_path, out_dir, args.grade_run_id, run_meta)

    by_file: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for oid, meta in key.items():
        by_file[meta["source_file"]].append((oid, meta))

    agree = {"match": 0, "off_by_1": 0, "off_by_2": 0, "ungraded": 0, "n": 0}
    disagreements = []
    written = []

    for source_file, oid_metas in sorted(by_file.items()):
        src = Path(source_file)
        meta, rows = read_jsonl(src)
        meta = dict(meta)
        meta.setdefault("administration_id", src.stem)
        lookup = {(m["administration_id"], m["probe_id"]): oid for oid, m in oid_metas}
        for row in rows:
            oid = lookup.get((meta["administration_id"], row["probe_id"])) or lookup.get((src.stem, row["probe_id"]))
            if not oid:
                continue
            grade = grades[oid]
            ext_score = grade["score"]
            rationale = grade["rationale"]
            agree["n"] += 1
            baseline = key[oid].get("baseline_score")
            if baseline is not None:
                delta = abs(ext_score - baseline)
                agree["match" if delta == 0 else ("off_by_1" if delta == 1 else "off_by_2")] += 1
                if delta:
                    disagreements.append((meta.get("administration_id", src.stem), row["probe_id"], baseline, ext_score, str(rationale)[:70]))
            ext = {
                "id": oid,
                "grade_run_id": args.grade_run_id,
                "packet_sha256": packet_sha,
                "packet_source_commit": source_commit,
                "score": ext_score,
                "score_key": "2=pass,1=partial,0=fail; null=UNGRADED",
                "grader": args.grader,
                "grader_conflict": "independent external grade; exact executor model unverified unless separately attested",
                "grade_note": rationale,
            }
            existing = [x for x in row.get("external_grades", []) if x.get("grade_run_id") == args.grade_run_id]
            if existing and any(x != ext for x in existing):
                sys.exit(f"Conflicting existing judgment for grade_run_id {args.grade_run_id}, id {oid}")
            row.setdefault("external_grades", [])
            row["external_grades"] = [x for x in row["external_grades"] if x.get("grade_run_id") != args.grade_run_id] + [ext]
        out_path = out_dir / src.name
        write_jsonl(out_path, meta, rows)
        written.append(out_path)

    print(f"Wrote {len(written)} additive regraded files to {out_dir}/  (grader={args.grader}, grade_run_id={args.grade_run_id})")
    print(
        f"\nAGREEMENT vs baseline (n={agree['n']}): "
        f"exact={agree['match']}  off-by-1={agree['off_by_1']}  off-by-2={agree['off_by_2']}  ungraded={agree['ungraded']}"
    )
    if disagreements:
        print("\nDisagreements (administration probe  baseline->external  note):")
        for admin, probe, baseline, ext, note in sorted(disagreements):
            print(f"  {admin:<45} {probe:<4} {baseline}->{ext}  {note}")


if __name__ == "__main__":
    main()
