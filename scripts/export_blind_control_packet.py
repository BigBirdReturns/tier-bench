"""Export a blind external-grading packet from frozen control-result evidence.

The public packet is safe to send to an independent grader: it contains only
packet-local opaque item IDs, rubric text, probe shape/surface, and exact
preserved response verbatims. A separate private key maps opaque IDs back to the
source run and stores baseline scores for later agreement reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path

PROBE_ORDER = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10"]
FORBIDDEN_PACKET_KEYS = {
    "administration_id",
    "run_id",
    "source_file",
    "score",
    "score_total",
    "score_max",
    "score_key",
    "grader",
    "grader_conflict",
    "grade_note",
    "evidence_class",
    "model",
    "effort",
    "contributor",
    "date",
}


def source_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"


def administration_id(path: Path, meta: dict) -> str:
    return str(meta.get("administration_id") or meta.get("run_id") or path.stem)


def load_jsonl(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or not rows[0].get("_meta"):
        raise ValueError(f"{path}: missing _meta row")
    return rows[0], rows[1:]


def opaque_id(source_commit: str, admin_id: str, probe_id: str, response: str) -> str:
    payload = f"{source_commit}\0{admin_id}\0{probe_id}\0{response}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def build_packet(data_dir: Path, rubric_path: Path, source: str, seed: str):
    rubric = rubric_path.read_text(encoding="utf-8")
    packet_rows = []
    key = {}
    for path in sorted(data_dir.glob("*.jsonl")):
        meta, rows = load_jsonl(path)
        admin_id = administration_id(path, meta)
        for row in sorted(rows, key=lambda r: PROBE_ORDER.index(r["probe_id"])):
            oid = opaque_id(source, admin_id, row["probe_id"], row["response"])
            item = {
                "id": oid,
                "probe_id": row["probe_id"],
                "probe_shape": row["probe_shape"],
                "prompt_surface": row["prompt_surface"],
                "response": row["response"],
            }
            leaked = FORBIDDEN_PACKET_KEYS.intersection(item)
            if leaked:
                raise AssertionError(f"packet item leaked forbidden keys: {sorted(leaked)}")
            packet_rows.append(item)
            key[oid] = {
                "source_file": str(path),
                "administration_id": admin_id,
                "model": meta.get("model"),
                "effort": meta.get("effort"),
                "contributor": meta.get("contributor"),
                "date": meta.get("date"),
                "probe_id": row["probe_id"],
                "baseline_score": row.get("score"),
                "baseline_grader": row.get("grader"),
            }
    random.Random(seed).shuffle(packet_rows)
    packet = {
        "_meta": {
            "packet_schema": "tier-bench.control_blind_packet.v1",
            "source_commit": source,
            "permutation_seed": seed,
            "item_count": len(packet_rows),
            "instructions": "Return exactly one JSON object per item as an array of {id, score, rationale}. Score only from this packet's rubric and verbatim responses. Do not infer subject model identity.",
        },
        "rubric": rubric,
        "items": packet_rows,
    }
    return packet, key


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/control-results")
    ap.add_argument("--rubric", default="driver/control-set.md")
    ap.add_argument("--packet", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--source-commit", default=None)
    ap.add_argument("--seed", default="control-blind-v1")
    args = ap.parse_args()

    source = args.source_commit or source_commit()
    packet_path = Path(args.packet)
    key_path = Path(args.key)
    packet, key = build_packet(Path(args.data), Path(args.rubric), source, args.seed)
    write_json(packet_path, packet)
    digest = sha256_file(packet_path)
    key_obj = {
        "_meta": {
            "key_schema": "tier-bench.control_blind_key.v1",
            "source_commit": source,
            "packet_path": str(packet_path),
            "packet_sha256": digest,
            "permutation_seed": args.seed,
        },
        "items": key,
    }
    write_json(key_path, key_obj)
    print(f"wrote packet: {packet_path}")
    print(f"wrote key: {key_path}")
    print(f"packet_sha256: {digest}")


if __name__ == "__main__":
    main()
