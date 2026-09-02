"""Canonical serialization and stable identifiers for Estate Lab artifacts.

The laboratory intentionally keeps timestamps and machine-local paths outside of
identity-bearing projections. Two runs over the same manifest, scenario, route,
and semantic state should produce the same identities even when they execute on
different machines.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Return UTF-8 canonical JSON bytes.

    The encoding is deliberately small and language-portable: sorted keys,
    compact separators, UTF-8, and no NaN/Infinity values.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    """Hash a JSON-compatible value or raw bytes with SHA-256."""

    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    """Derive a short, namespaced, content-bound identifier."""

    if not prefix or not prefix.replace("_", "").isalnum():
        raise ValueError(f"invalid stable-id prefix: {prefix!r}")
    if length < 12 or length > 64:
        raise ValueError("stable-id length must be between 12 and 64")
    return f"{prefix}_{sha256_hex(value)[:length]}"


def load_json(path: Path) -> Any:
    """Load strict JSON, rejecting duplicate object keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=reject_duplicates)


def write_json(path: Path, value: Any) -> None:
    """Write stable, human-inspectable JSON with a trailing newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    )
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
