"""Loopback-only persistent llama.cpp slot-cache control."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .sovereign_common import (
    CACHE_RECEIPT_SCHEMA,
    PlaneError,
    hash_json,
    now,
    safe_filename,
)
from .sovereign_context import pack_metrics, prefix_fingerprint
from .sovereign_schema import validate_manifest


def normalize_server_url(value: str, *, unsafe_network: bool = False) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PlaneError("server URL must be http or https with a hostname")
    if parsed.username or parsed.password:
        raise PlaneError("server URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise PlaneError("server URL must not contain query or fragment")
    hostname = parsed.hostname.lower()
    loopback = hostname in {"localhost", "127.0.0.1", "::1"}
    if not loopback and not unsafe_network:
        raise PlaneError("non-loopback cache control requires --unsafe-network")
    port = f":{parsed.port}" if parsed.port else ""
    rendered_host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    base_path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{rendered_host}{port}{base_path}"


def slot_request(
    server_url: str,
    *,
    slot: int,
    action: str,
    filename: str,
    timeout: float = 30.0,
    unsafe_network: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
        raise PlaneError("slot must be a non-negative integer")
    if action not in {"save", "restore"}:
        raise PlaneError("slot action must be save or restore")
    cache_name = safe_filename(filename, "cache filename")
    base = normalize_server_url(server_url, unsafe_network=unsafe_network)
    url = f"{base}/slots/{slot}?action={action}"
    request_body = {"filename": cache_name}
    if dry_run:
        return {
            "dry_run": True,
            "method": "POST",
            "url": url,
            "body": request_body,
        }
    request = Request(
        url,
        method="POST",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PlaneError(f"llama.cpp slot action failed HTTP {exc.code}: {detail}") from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise PlaneError(f"llama.cpp slot action failed: {exc}") from exc
    if not isinstance(value, dict):
        raise PlaneError("llama.cpp slot action returned a non-object")
    if value.get("id_slot") not in {None, slot}:
        raise PlaneError("llama.cpp slot response contradicts requested slot")
    if value.get("filename") not in {None, cache_name}:
        raise PlaneError("llama.cpp slot response contradicts requested filename")
    return value


def _binding(raw_manifest: Any, runtime_id: str, pack_id: str) -> tuple[dict, dict, dict]:
    manifest = validate_manifest(raw_manifest)
    runtimes = {row["id"]: row for row in manifest["runtimes"]}
    packs = {row["id"]: row for row in manifest["context_packs"]}
    if runtime_id not in runtimes:
        raise PlaneError(f"unknown runtime: {runtime_id}")
    if pack_id not in packs:
        raise PlaneError(f"unknown context pack: {pack_id}")
    runtime = runtimes[runtime_id]
    pack = packs[pack_id]
    if runtime["execution_class"] != "local":
        raise PlaneError("persistent slot cache control is only valid for local runtimes")
    if runtime["cache"]["mode"] != "persistent_slot":
        raise PlaneError(
            f"runtime {runtime_id} cache.mode must be persistent_slot for slot save/restore"
        )
    return manifest, runtime, pack


def _registry_path(state_dir: Path) -> Path:
    return state_dir / "kv-cache-registry.jsonl"


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PlaneError(f"invalid cache registry row {number}") from exc
        if not isinstance(row, dict) or row.get("schema") != CACHE_RECEIPT_SCHEMA:
            raise PlaneError(f"invalid cache registry row {number}")
        result.append(row)
    return result


def _base_receipt(
    manifest: dict[str, Any],
    runtime: dict[str, Any],
    pack: dict[str, Any],
    *,
    action: str,
    server_url: str,
    slot: int,
    filename: str,
) -> dict[str, Any]:
    metrics = pack_metrics(pack)
    return {
        "schema": CACHE_RECEIPT_SCHEMA,
        "action": action,
        "plane_id": manifest["id"],
        "manifest_sha256": hash_json(manifest),
        "runtime": {
            "id": runtime["id"],
            "model_id": runtime["model_id"],
            "tokenizer_id": runtime["tokenizer_id"],
            "runtime_id": runtime["runtime_id"],
            "runtime_version": runtime["runtime_version"],
            "quantization": runtime["quantization"],
        },
        "context_pack": {
            "id": pack["id"],
            "pack_fingerprint": metrics.pack_fingerprint,
            "prefix_fingerprint": prefix_fingerprint(runtime, pack),
            "cacheable_tokens": metrics.cacheable_tokens,
            "source_identity": pack["source_identity"],
            "source_revision": pack["source_revision"],
        },
        "server_url": normalize_server_url(server_url, unsafe_network=True),
        "slot": slot,
        "filename": safe_filename(filename, "cache filename"),
        "created_at": now(),
    }


def save_slot_cache(
    raw_manifest: Any,
    *,
    runtime_id: str,
    pack_id: str,
    server_url: str,
    slot: int,
    filename: str,
    state_dir: Path,
    timeout: float = 30.0,
    unsafe_network: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest, runtime, pack = _binding(raw_manifest, runtime_id, pack_id)
    provider = slot_request(
        server_url,
        slot=slot,
        action="save",
        filename=filename,
        timeout=timeout,
        unsafe_network=unsafe_network,
        dry_run=dry_run,
    )
    receipt = _base_receipt(
        manifest,
        runtime,
        pack,
        action="save",
        server_url=server_url,
        slot=slot,
        filename=filename,
    )
    receipt["provider_response"] = provider
    receipt["observed"] = not dry_run
    receipt["receipt_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "created_at"}
    )
    if not dry_run:
        _append(_registry_path(state_dir), receipt)
    return receipt


def _matching_save(
    rows: list[dict[str, Any]],
    *,
    runtime: dict[str, Any],
    pack: dict[str, Any],
    filename: str,
) -> dict[str, Any] | None:
    prefix = prefix_fingerprint(runtime, pack)
    for row in reversed(rows):
        if (
            row.get("action") == "save"
            and row.get("observed") is True
            and row.get("filename") == filename
            and (row.get("runtime") or {}).get("id") == runtime["id"]
            and (row.get("context_pack") or {}).get("prefix_fingerprint") == prefix
        ):
            return row
    return None


def restore_slot_cache(
    raw_manifest: Any,
    *,
    runtime_id: str,
    pack_id: str,
    server_url: str,
    slot: int,
    filename: str,
    state_dir: Path,
    timeout: float = 30.0,
    unsafe_network: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest, runtime, pack = _binding(raw_manifest, runtime_id, pack_id)
    registry = _registry_path(state_dir)
    saved = _matching_save(
        _rows(registry), runtime=runtime, pack=pack, filename=filename
    )
    if saved is None and not dry_run:
        raise PlaneError(
            "no observed save receipt matches this model, tokenizer, runtime, "
            "quantization, context prefix, and filename"
        )
    provider = slot_request(
        server_url,
        slot=slot,
        action="restore",
        filename=filename,
        timeout=timeout,
        unsafe_network=unsafe_network,
        dry_run=dry_run,
    )
    receipt = _base_receipt(
        manifest,
        runtime,
        pack,
        action="restore",
        server_url=server_url,
        slot=slot,
        filename=filename,
    )
    receipt["provider_response"] = provider
    receipt["observed"] = not dry_run
    receipt["save_receipt_sha256"] = saved.get("receipt_sha256") if saved else None
    receipt["receipt_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "created_at"}
    )
    if not dry_run:
        _append(registry, receipt)
    return receipt


def cache_inventory_from_registry(
    raw_manifest: Any, state_dir: Path
) -> list[dict[str, Any]]:
    manifest = validate_manifest(raw_manifest)
    runtimes = {row["id"]: row for row in manifest["runtimes"]}
    packs = {row["id"]: row for row in manifest["context_packs"]}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _rows(_registry_path(state_dir)):
        if row.get("action") != "save" or row.get("observed") is not True:
            continue
        runtime_id = (row.get("runtime") or {}).get("id")
        pack_id = (row.get("context_pack") or {}).get("id")
        if runtime_id not in runtimes or pack_id not in packs:
            continue
        runtime = runtimes[runtime_id]
        pack = packs[pack_id]
        expected = prefix_fingerprint(runtime, pack)
        if (row.get("context_pack") or {}).get("prefix_fingerprint") != expected:
            continue
        latest[(runtime_id, pack_id)] = row
    return [
        {
            "runtime_id": runtime_id,
            "context_pack": pack_id,
            "prefix_fingerprint": (row["context_pack"])["prefix_fingerprint"],
            "tier": "disk",
            "tokens": (row["context_pack"])["cacheable_tokens"],
            "valid": True,
            "receipt_sha256": row["receipt_sha256"],
        }
        for (runtime_id, pack_id), row in sorted(latest.items())
    ]
