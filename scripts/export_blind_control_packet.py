"""Export a blind external-grading packet from frozen control-result evidence.

The public packet is safe to send to an independent grader: it contains only
packet-local opaque item IDs, rubric text, probe shape/surface, and exact
preserved response verbatims. A separate private key maps opaque IDs back to the
source run and stores baseline scores for later agreement reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import random
import secrets
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


def secret_commitment(label: str, secret: str) -> str:
    return hashlib.sha256(f"{label}\0{secret}".encode("utf-8")).hexdigest()


def opaque_id(id_salt: str, source_commit: str, admin_id: str,
              probe_id: str, response: str) -> str:
    payload = f"{source_commit}\0{admin_id}\0{probe_id}\0{response}".encode("utf-8")
    return hmac.new(id_salt.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:24]


def build_packet(data_dir: Path, rubric_path: Path, source: str, seed: str,
                 id_salt: str):
    rubric = rubric_path.read_text(encoding="utf-8")
    packet_rows = []
    key = {}
    for path in sorted(data_dir.glob("*.jsonl")):
        meta, rows = load_jsonl(path)
        admin_id = administration_id(path, meta)
        for row in sorted(rows, key=lambda r: PROBE_ORDER.index(r["probe_id"])):
            oid = opaque_id(id_salt, source, admin_id, row["probe_id"], row["response"])
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
            "packet_schema": "tier-bench.control_blind_packet.v2",
            "source_commit": source,
            "id_salt_commitment": secret_commitment("id-salt", id_salt),
            "permutation_commitment": secret_commitment("permutation", seed),
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


def load_private_secrets(path: Path) -> tuple[str, str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    meta = obj.get("_meta", obj)
    try:
        return str(meta["id_salt"]), str(meta["permutation_seed"])
    except KeyError as e:
        raise ValueError(f"{path}: missing private secret {e.args[0]!r}") from e


def load_id_salt(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("{"):
        obj = json.loads(text)
        text = str(obj.get("id_salt") or obj.get("_meta", {}).get("id_salt") or "")
    if not text:
        raise ValueError(f"{path}: empty id salt")
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/control-results")
    ap.add_argument("--rubric", default="driver/control-set.md")
    ap.add_argument("--packet", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--source-commit", default=None)
    ap.add_argument("--seed", default=None,
                    help="Private permutation seed. Omit to generate 256 bits; never publish it.")
    ap.add_argument("--id-salt-file", default=None,
                    help="Private salt file for deterministic regeneration. Omit to generate 256 bits.")
    ap.add_argument("--secrets-from-key", default=None,
                    help="Regenerate using id_salt and permutation_seed from an existing private key.")
    args = ap.parse_args()

    source = args.source_commit or source_commit()
    if args.secrets_from_key:
        if args.seed or args.id_salt_file:
            ap.error("--secrets-from-key cannot be combined with --seed or --id-salt-file")
        id_salt, seed = load_private_secrets(Path(args.secrets_from_key))
    else:
        id_salt = (load_id_salt(Path(args.id_salt_file))
                   if args.id_salt_file else secrets.token_hex(32))
        seed = args.seed or secrets.token_hex(32)
    if len(id_salt) < 32:
        ap.error("id salt must contain at least 32 characters")
    if len(seed) < 16:
        ap.error("permutation seed must contain at least 16 characters")
    packet_path = Path(args.packet)
    key_path = Path(args.key)
    packet, key = build_packet(Path(args.data), Path(args.rubric), source, seed, id_salt)
    write_json(packet_path, packet)
    digest = sha256_file(packet_path)
    key_obj = {
        "_meta": {
            "key_schema": "tier-bench.control_blind_key.v2",
            "packet_schema": "tier-bench.control_blind_packet.v2",
            "source_commit": source,
            "packet_path": str(packet_path),
            "packet_sha256": digest,
            "id_salt": id_salt,
            "id_salt_commitment": secret_commitment("id-salt", id_salt),
            "permutation_seed": seed,
            "permutation_commitment": secret_commitment("permutation", seed),
        },
        "items": key,
    }
    write_json(key_path, key_obj)
    print(f"wrote packet: {packet_path}")
    print(f"wrote key: {key_path}")
    print(f"packet_sha256: {digest}")


if __name__ == "__main__":
    main()
