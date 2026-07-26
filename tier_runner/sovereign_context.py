"""Content-addressed context packs and exact prefix bindings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .sovereign_common import (
    CONTEXT_RECEIPT_SCHEMA,
    PlaneError,
    hash_json,
    now,
    sha256_bytes,
    sha256_file,
    write_json,
)
from .sovereign_schema import validate_manifest


@dataclass(frozen=True)
class PackMetrics:
    source_tokens: int
    selected_tokens: int
    cacheable_tokens: int
    dynamic_tokens: int
    pack_fingerprint: str


def pack_metrics(pack: dict[str, Any]) -> PackMetrics:
    selected = sum(block["tokens"] for block in pack["blocks"])
    cacheable = sum(
        block["tokens"]
        for block in pack["blocks"]
        if block["stability"] in {"estate", "campaign"}
    )
    return PackMetrics(
        source_tokens=pack["source_tokens"],
        selected_tokens=selected,
        cacheable_tokens=cacheable,
        dynamic_tokens=selected - cacheable,
        pack_fingerprint=hash_json(
            {
                "source_identity": pack["source_identity"],
                "source_revision": pack["source_revision"],
                "blocks": [
                    {
                        "id": block["id"],
                        "kind": block["kind"],
                        "stability": block["stability"],
                        "sha256": block["sha256"],
                        "tokens": block["tokens"],
                        "compression": block["compression"],
                    }
                    for block in pack["blocks"]
                ],
            }
        ),
    )


def prefix_fingerprint(runtime: dict[str, Any], pack: dict[str, Any]) -> str:
    """Bind reusable state to every compatibility-bearing identity."""
    return hash_json(
        {
            "model_id": runtime["model_id"],
            "tokenizer_id": runtime["tokenizer_id"],
            "runtime_id": runtime["runtime_id"],
            "runtime_version": runtime["runtime_version"],
            "quantization": runtime["quantization"],
            "source_identity": pack["source_identity"],
            "source_revision": pack["source_revision"],
            "blocks": [
                {
                    "id": block["id"],
                    "kind": block["kind"],
                    "sha256": block["sha256"],
                    "tokens": block["tokens"],
                    "stability": block["stability"],
                    "compression": block["compression"],
                }
                for block in pack["blocks"]
                if block["stability"] in {"estate", "campaign"}
            ],
        }
    )


def _block_bytes(block: dict[str, Any], repo: Path) -> tuple[bytes, dict[str, Any]]:
    content_path = block.get("content_path")
    if not content_path:
        raise PlaneError(
            f"context block {block['id']} has no content_path; it can be planned but not materialized"
        )
    path = (repo / content_path).resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError as exc:
        raise PlaneError(f"context block {block['id']} escapes the repository") from exc
    if not path.is_file():
        raise PlaneError(f"context block {block['id']} content is missing: {content_path}")
    raw = path.read_bytes()
    actual = sha256_bytes(raw)
    if actual != block["sha256"]:
        raise PlaneError(
            f"context block {block['id']} content hash mismatch: {actual} != {block['sha256']}"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlaneError(f"context block {block['id']} is not UTF-8 text") from exc
    normalized = text if text.endswith("\n") else text + "\n"
    header = (
        f"===== BEGIN {block['stability']}:{block['kind']}:{block['id']}:"
        f"{block['sha256']} =====\n"
    )
    footer = (
        f"===== END {block['stability']}:{block['kind']}:{block['id']} =====\n"
    )
    rendered = (header + normalized + footer).encode("utf-8")
    return rendered, {
        "id": block["id"],
        "kind": block["kind"],
        "stability": block["stability"],
        "source": block["source"],
        "content_path": content_path,
        "content_sha256": actual,
        "rendered_sha256": sha256_bytes(rendered),
        "tokens": block["tokens"],
        "compression": block["compression"],
    }


def materialize_context_pack(
    raw_manifest: Any,
    pack_id: str,
    repo: Path,
    out_root: Path,
) -> dict[str, Any]:
    """Render one pack into a stable prefix and dynamic suffix.

    The materialized bytes are runtime-independent. A runtime-specific KV binding
    is derived separately with :func:`prefix_fingerprint`.
    """
    manifest = validate_manifest(raw_manifest)
    packs = {pack["id"]: pack for pack in manifest["context_packs"]}
    if pack_id not in packs:
        raise PlaneError(f"unknown context pack: {pack_id}")
    pack = packs[pack_id]
    metrics = pack_metrics(pack)
    prefix_parts: list[bytes] = []
    dynamic_parts: list[bytes] = []
    records: list[dict[str, Any]] = []
    for block in pack["blocks"]:
        rendered, record = _block_bytes(block, repo)
        records.append(record)
        if block["stability"] in {"estate", "campaign"}:
            prefix_parts.append(rendered)
        else:
            dynamic_parts.append(rendered)
    prefix = b"".join(prefix_parts)
    dynamic = b"".join(dynamic_parts)
    target = out_root.resolve() / metrics.pack_fingerprint
    receipt = {
        "schema": CONTEXT_RECEIPT_SCHEMA,
        "plane_id": manifest["id"],
        "pack_id": pack_id,
        "source_identity": pack["source_identity"],
        "source_revision": pack["source_revision"],
        "pack_fingerprint": metrics.pack_fingerprint,
        "source_tokens": metrics.source_tokens,
        "selected_tokens": metrics.selected_tokens,
        "cacheable_tokens": metrics.cacheable_tokens,
        "dynamic_tokens": metrics.dynamic_tokens,
        "prefix_sha256": sha256_bytes(prefix),
        "dynamic_sha256": sha256_bytes(dynamic),
        "blocks": records,
        "paths": {
            "prefix": "prefix.txt",
            "dynamic": "dynamic.txt",
            "receipt": "pack-receipt.json",
        },
        "created_at": now(),
    }
    receipt["receipt_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "created_at"}
    )

    if target.exists():
        receipt_path = target / "pack-receipt.json"
        if receipt_path.is_file():
            existing = __import__("json").loads(receipt_path.read_text(encoding="utf-8"))
            if existing.get("receipt_sha256") == receipt["receipt_sha256"]:
                return existing
        raise PlaneError(f"context pack target exists with different bytes: {target}")

    out_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{pack_id}-", dir=out_root))
    try:
        (temporary / "prefix.txt").write_bytes(prefix)
        (temporary / "dynamic.txt").write_bytes(dynamic)
        write_json(temporary / "pack-receipt.json", receipt)
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return receipt


def verify_context_receipt(directory: Path) -> list[str]:
    errors: list[str] = []
    receipt_path = directory / "pack-receipt.json"
    try:
        import json

        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["pack-receipt.json is missing or invalid"]
    if receipt.get("schema") != CONTEXT_RECEIPT_SCHEMA:
        errors.append(f"receipt.schema must be {CONTEXT_RECEIPT_SCHEMA}")
        return errors
    for name, key in (("prefix.txt", "prefix_sha256"), ("dynamic.txt", "dynamic_sha256")):
        path = directory / name
        if not path.is_file():
            errors.append(f"{name} is missing")
        elif sha256_file(path) != receipt.get(key):
            errors.append(f"{name} hash mismatch")
    expected = hash_json(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"created_at", "receipt_sha256"}
        }
    )
    if receipt.get("receipt_sha256") != expected:
        errors.append("receipt_sha256 mismatch")
    return errors
