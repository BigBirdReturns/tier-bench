"""External benchmark and community data ingestion for the model-floor observatory."""
from __future__ import annotations

import base64
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .model_floor_common import (
    ModelFloorError,
    OBSERVATION_SCHEMA,
    SNAPSHOT_SCHEMA,
    SOURCE_CONFIG_SCHEMA,
    SYNC_RECEIPT_SCHEMA,
    append_jsonl,
    hash_json,
    load_json,
    need_array,
    need_bool,
    need_int,
    need_number,
    need_object,
    need_text,
    nested_get,
    now_utc,
    optional_text,
    read_jsonl,
    safe_id,
    sha256_bytes,
    write_json,
    write_jsonl,
)

SOURCE_KINDS = {
    "hf_leaderboard",
    "hf_official_benchmarks",
    "hf_model_evals",
    "github_search",
    "reddit_oauth",
    "http_json",
    "http_csv",
    "atom",
    "jsonl_import",
}
EVIDENCE_TIERS = {
    "official_benchmark",
    "verified_submission",
    "reproducible_receipt",
    "detailed_report",
    "assertion",
    "speculation",
}
TRAINING_POLICIES = {"prohibited", "unknown", "permitted"}
DIRECTIONS = {"higher", "lower"}
COMMUNITY_METRIC = re.compile(
    r"(?<![A-Za-z0-9._-])(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>tok/s|tokens/s|ms|s|gb|gib|mb|mib|%)",
    re.I,
)
MODEL_TOKEN = re.compile(
    r"\b(?:claude|opus|fable|sonnet|haiku|gpt|gemini|qwen|kimi|deepseek|mistral|llama|glm|minimax)[A-Za-z0-9._:/+-]*\b",
    re.I,
)


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[bytes, dict[str, str], int]:
    request = Request(url, headers=headers or {}, data=data)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        raise ModelFloorError(f"HTTP {exc.code} for {url}: {body}") from exc
    except URLError as exc:
        raise ModelFloorError(f"network failure for {url}: {exc}") from exc
    return payload, response_headers, status


def _request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[Any, dict[str, str], int, bytes]:
    payload, response_headers, status = _request(
        url, headers=headers, data=data, timeout=timeout
    )
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ModelFloorError(f"non-JSON response from {url}: {exc}") from exc
    return value, response_headers, status, payload


def _benchmark(raw: Any, label: str) -> dict[str, Any]:
    value = need_object(raw, label)
    benchmark_id = safe_id(value.get("id"), f"{label}.id", limit=300)
    revision = need_text(value.get("revision", "rolling"), f"{label}.revision", limit=300)
    family = safe_id(value.get("task_family", benchmark_id), f"{label}.task_family", limit=300)
    metric = safe_id(value.get("metric"), f"{label}.metric", limit=300)
    direction = value.get("direction", "higher")
    if direction not in DIRECTIONS:
        raise ModelFloorError(f"{label}.direction must be higher or lower")
    return {
        **value,
        "id": benchmark_id,
        "revision": revision,
        "task_family": family,
        "metric": metric,
        "direction": direction,
        "unit": need_text(value.get("unit", "score"), f"{label}.unit", limit=100),
        "scaffold": need_text(value.get("scaffold", "unspecified"), f"{label}.scaffold", limit=500),
        "tools": need_text(value.get("tools", "unspecified"), f"{label}.tools", limit=500),
        "attempts": need_int(value.get("attempts", 1), f"{label}.attempts", low=1, high=100000),
        "context_policy": need_text(
            value.get("context_policy", "unspecified"),
            f"{label}.context_policy",
            limit=500,
        ),
        "adequacy_threshold": need_number(
            value.get("adequacy_threshold"),
            f"{label}.adequacy_threshold",
            allow_none=True,
        ),
    }


def validate_source_config(raw: Any, *, config_path: Path | None = None) -> dict[str, Any]:
    value = need_object(raw, "source config")
    if value.get("schema") != SOURCE_CONFIG_SCHEMA:
        raise ModelFloorError(f"source config schema must be {SOURCE_CONFIG_SCHEMA}")
    source_id = safe_id(value.get("id"), "source config.id")
    excerpt_chars = need_int(
        value.get("excerpt_chars", 1200), "source config.excerpt_chars", low=0, high=10000
    )
    retention_days = need_int(
        value.get("retention_days", 180),
        "source config.retention_days",
        low=1,
        high=3650,
    )
    sources = []
    seen: set[str] = set()
    base = config_path.parent.resolve() if config_path else Path.cwd()
    for index, raw_source in enumerate(
        need_array(value.get("sources"), "source config.sources", nonempty=True)
    ):
        row = need_object(raw_source, f"sources[{index}]")
        identifier = safe_id(row.get("id"), f"sources[{index}].id")
        if identifier in seen:
            raise ModelFloorError(f"duplicate source id: {identifier}")
        seen.add(identifier)
        kind = need_text(row.get("kind"), f"{identifier}.kind", limit=100)
        if kind not in SOURCE_KINDS:
            raise ModelFloorError(f"{identifier}.kind must be one of {sorted(SOURCE_KINDS)}")
        evidence_tier = row.get("evidence_tier", "assertion")
        if evidence_tier not in EVIDENCE_TIERS:
            raise ModelFloorError(
                f"{identifier}.evidence_tier must be one of {sorted(EVIDENCE_TIERS)}"
            )
        training_use = row.get("training_use", "prohibited")
        if training_use not in TRAINING_POLICIES:
            raise ModelFloorError(
                f"{identifier}.training_use must be one of {sorted(TRAINING_POLICIES)}"
            )
        normalized = {
            **row,
            "id": identifier,
            "kind": kind,
            "enabled": need_bool(row.get("enabled", True), f"{identifier}.enabled"),
            "evidence_tier": evidence_tier,
            "training_use": training_use,
            "verified": need_bool(row.get("verified", False), f"{identifier}.verified"),
        }
        if kind in {"hf_leaderboard", "hf_model_evals"}:
            normalized["benchmark"] = _benchmark(row.get("benchmark"), f"{identifier}.benchmark")
        if kind == "hf_leaderboard":
            normalized["dataset_id"] = need_text(
                row.get("dataset_id"), f"{identifier}.dataset_id", limit=500
            )
            normalized["token_env"] = need_text(
                row.get("token_env", "HF_TOKEN"), f"{identifier}.token_env", limit=100
            )
        elif kind == "hf_official_benchmarks":
            normalized["token_env"] = need_text(
                row.get("token_env", "HF_TOKEN"), f"{identifier}.token_env", limit=100
            )
        elif kind == "hf_model_evals":
            normalized["model_ids"] = [
                need_text(item, f"{identifier}.model_ids[]", limit=500)
                for item in need_array(
                    row.get("model_ids"), f"{identifier}.model_ids", nonempty=True
                )
            ]
            normalized["token_env"] = need_text(
                row.get("token_env", "HF_TOKEN"), f"{identifier}.token_env", limit=100
            )
        elif kind == "github_search":
            normalized["queries"] = [
                need_text(item, f"{identifier}.queries[]", limit=1000)
                for item in need_array(
                    row.get("queries"), f"{identifier}.queries", nonempty=True
                )
            ]
            normalized["token_env"] = need_text(
                row.get("token_env", "GITHUB_TOKEN"), f"{identifier}.token_env", limit=100
            )
            normalized["max_items_per_query"] = need_int(
                row.get("max_items_per_query", 50),
                f"{identifier}.max_items_per_query",
                low=1,
                high=100,
            )
        elif kind == "reddit_oauth":
            normalized["approval_confirmed"] = need_bool(
                row.get("approval_confirmed", False),
                f"{identifier}.approval_confirmed",
            )
            normalized["subreddits"] = [
                need_text(item, f"{identifier}.subreddits[]", limit=100)
                for item in need_array(
                    row.get("subreddits"), f"{identifier}.subreddits", nonempty=True
                )
            ]
            normalized["queries"] = [
                need_text(item, f"{identifier}.queries[]", limit=500)
                for item in need_array(
                    row.get("queries"), f"{identifier}.queries", nonempty=True
                )
            ]
            normalized["max_posts_per_query"] = need_int(
                row.get("max_posts_per_query", 50),
                f"{identifier}.max_posts_per_query",
                low=1,
                high=100,
            )
            for key, default in (
                ("client_id_env", "REDDIT_CLIENT_ID"),
                ("client_secret_env", "REDDIT_CLIENT_SECRET"),
                ("user_agent_env", "REDDIT_USER_AGENT"),
            ):
                normalized[key] = need_text(
                    row.get(key, default), f"{identifier}.{key}", limit=100
                )
        elif kind in {"http_json", "http_csv"}:
            normalized["url"] = need_text(row.get("url"), f"{identifier}.url", limit=2000)
            normalized["benchmark"] = _benchmark(row.get("benchmark"), f"{identifier}.benchmark")
            normalized["mapping"] = need_object(row.get("mapping"), f"{identifier}.mapping")
            normalized["token_env"] = optional_text(
                row.get("token_env"), f"{identifier}.token_env", limit=100
            )
        elif kind == "atom":
            normalized["urls"] = [
                need_text(item, f"{identifier}.urls[]", limit=2000)
                for item in need_array(row.get("urls"), f"{identifier}.urls", nonempty=True)
            ]
        elif kind == "jsonl_import":
            paths = []
            for item in need_array(row.get("paths"), f"{identifier}.paths", nonempty=True):
                raw_path = Path(need_text(item, f"{identifier}.paths[]", limit=2000))
                paths.append(str(raw_path.resolve() if raw_path.is_absolute() else (base / raw_path).resolve()))
            normalized["paths"] = paths
            if row.get("benchmark") is not None:
                normalized["benchmark"] = _benchmark(
                    row.get("benchmark"), f"{identifier}.benchmark"
                )
        sources.append(normalized)
    return {
        **value,
        "id": source_id,
        "excerpt_chars": excerpt_chars,
        "retention_days": retention_days,
        "sources": sources,
    }


def _observation_id(source_id: str, external_id: str, benchmark_id: str, model_id: str) -> str:
    digest = hashlib.sha256(
        f"{source_id}\0{external_id}\0{benchmark_id}\0{model_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"ext-{digest}"


def _comparison_key(benchmark: dict[str, Any]) -> str:
    fields = {
        key: benchmark.get(key)
        for key in (
            "id",
            "revision",
            "task_family",
            "metric",
            "direction",
            "unit",
            "scaffold",
            "tools",
            "attempts",
            "context_policy",
        )
    }
    return hash_json(fields)


def _make_observation(
    *,
    source: dict[str, Any],
    external_id: str,
    model_id: str,
    runtime_id: str | None,
    surface_id: str | None,
    benchmark: dict[str, Any],
    value: float,
    rank: int | None = None,
    sample_size: int | None = None,
    cost_usd: float | None = None,
    latency_ms: float | None = None,
    attention_minutes: float | None = None,
    verified: bool | None = None,
    metadata: dict[str, Any] | None = None,
    uri: str | None = None,
    snapshot_sha256: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    result = {
        "value": value,
        "rank": rank,
        "sample_size": sample_size,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "attention_minutes": attention_minutes,
    }
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "id": _observation_id(source["id"], external_id, benchmark["id"], model_id),
        "observed_at": observed_at or now_utc(),
        "source": {
            "id": source["id"],
            "kind": source["kind"],
            "uri": uri,
            "snapshot_sha256": snapshot_sha256,
        },
        "model": {
            "declared_id": model_id,
            "runtime_id": runtime_id,
            "surface_id": surface_id,
            "revision": (metadata or {}).get("model_revision"),
            "effort": (metadata or {}).get("effort"),
            "quantization": (metadata or {}).get("quantization"),
            "hardware": (metadata or {}).get("hardware"),
        },
        "benchmark": {
            **benchmark,
            "comparison_key": _comparison_key(benchmark),
        },
        "result": result,
        "evidence": {
            "tier": source["evidence_tier"],
            "verified": source["verified"] if verified is None else bool(verified),
            "training_use": source["training_use"],
            "tainted": source["kind"] in {"reddit_oauth", "github_search", "atom"},
        },
        "metadata": metadata or {},
    }
    observation["observation_sha256"] = hash_json(
        {key: value for key, value in observation.items() if key != "observation_sha256"}
    )
    return observation


def _snapshot(
    source: dict[str, Any],
    *,
    uri: str,
    payload: bytes,
    status: int | None,
    response_headers: dict[str, str] | None,
    state_dir: Path,
) -> tuple[dict[str, Any], Path]:
    digest = sha256_bytes(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = state_dir / "raw" / source["id"]
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / f"{stamp}-{digest[:16]}.raw"
    if not raw_path.exists():
        raw_path.write_bytes(payload)
    receipt = {
        "schema": SNAPSHOT_SCHEMA,
        "source_id": source["id"],
        "source_kind": source["kind"],
        "captured_at": now_utc(),
        "uri": uri,
        "http_status": status,
        "response_headers": {
            key: value
            for key, value in (response_headers or {}).items()
            if key in {"etag", "last-modified", "x-ratelimit-remaining", "x-ratelimit-reset"}
        },
        "payload_sha256": digest,
        "payload_bytes": len(payload),
        "raw_path": str(raw_path),
    }
    receipt["snapshot_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "snapshot_sha256"}
    )
    receipt_path = directory / f"{stamp}-{digest[:16]}.snapshot.json"
    write_json(receipt_path, receipt)
    return receipt, raw_path


def _hf_headers(source: dict[str, Any]) -> dict[str, str]:
    token = os.environ.get(source.get("token_env", "HF_TOKEN"))
    return {"Authorization": f"Bearer {token}"} if token else {}


def _sync_hf_leaderboard(
    source: dict[str, Any], *, state_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dataset_id = source["dataset_id"]
    uri = f"https://huggingface.co/api/datasets/{quote(dataset_id, safe='/')}/leaderboard"
    value, headers, status, payload = _request_json(uri, headers=_hf_headers(source))
    receipt, _ = _snapshot(
        source, uri=uri, payload=payload, status=status, response_headers=headers, state_dir=state_dir
    )
    if not isinstance(value, list):
        raise ModelFloorError(f"{source['id']} leaderboard response must be an array")
    observations = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            continue
        model_id = row.get("model_id")
        score = row.get("value")
        if not isinstance(model_id, str) or isinstance(score, bool) or not isinstance(
            score, (int, float)
        ):
            continue
        observations.append(
            _make_observation(
                source=source,
                external_id=str(row.get("pull_request") or row.get("filename") or index),
                model_id=model_id,
                runtime_id=None,
                surface_id=None,
                benchmark=source["benchmark"],
                value=float(score),
                rank=int(row["rank"]) if isinstance(row.get("rank"), int) else None,
                verified=bool(row.get("verified")),
                metadata={
                    "submission_source": row.get("source"),
                    "filename": row.get("filename"),
                    "pull_request": row.get("pull_request"),
                    "notes": row.get("notes"),
                    "dataset_id": dataset_id,
                },
                uri=uri,
                snapshot_sha256=receipt["snapshot_sha256"],
            )
        )
    return observations, [], [receipt]


def _sync_hf_official(
    source: dict[str, Any], *, state_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    uri = "https://huggingface.co/api/datasets?filter=benchmark:official&limit=1000"
    value, headers, status, payload = _request_json(uri, headers=_hf_headers(source))
    receipt, _ = _snapshot(
        source, uri=uri, payload=payload, status=status, response_headers=headers, state_dir=state_dir
    )
    rows = value if isinstance(value, list) else []
    community = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dataset_id = row.get("id")
        if not isinstance(dataset_id, str):
            continue
        community.append(
            {
                "id": f"hf-benchmark-{hashlib.sha256(dataset_id.encode()).hexdigest()[:20]}",
                "source_id": source["id"],
                "source_kind": source["kind"],
                "observed_at": now_utc(),
                "url": f"https://huggingface.co/datasets/{dataset_id}",
                "title": dataset_id,
                "excerpt": _clean_text(row.get("description") or "", 1200),
                "score": None,
                "topics": ["official-benchmark-catalog"],
                "metrics": [],
                "model_tokens": [],
                "evidence_tier": source["evidence_tier"],
                "verified": source["verified"],
                "training_use": source["training_use"],
                "snapshot_sha256": receipt["snapshot_sha256"],
                "metadata": {
                    "downloads": row.get("downloads"),
                    "likes": row.get("likes"),
                    "last_modified": row.get("lastModified"),
                },
            }
        )
    return [], community, [receipt]


def _sync_hf_model_evals(
    source: dict[str, Any], *, state_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    observations = []
    receipts = []
    for model_id in source["model_ids"]:
        uri = (
            f"https://huggingface.co/api/models/{quote(model_id, safe='/')}"
            "?expand=evalResults"
        )
        value, headers, status, payload = _request_json(uri, headers=_hf_headers(source))
        receipt, _ = _snapshot(
            source,
            uri=uri,
            payload=payload,
            status=status,
            response_headers=headers,
            state_dir=state_dir,
        )
        receipts.append(receipt)
        evals = value.get("evalResults") if isinstance(value, dict) else []
        if not isinstance(evals, list):
            continue
        for index, row in enumerate(evals):
            if not isinstance(row, dict):
                continue
            score = row.get("value")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            dataset_id = str(row.get("dataset_id") or source["benchmark"]["id"])
            benchmark = {
                **source["benchmark"],
                "id": dataset_id,
                "revision": str(row.get("dataset_revision") or source["benchmark"]["revision"]),
            }
            observations.append(
                _make_observation(
                    source=source,
                    external_id=f"{model_id}:{dataset_id}:{index}",
                    model_id=model_id,
                    runtime_id=None,
                    surface_id=None,
                    benchmark=benchmark,
                    value=float(score),
                    metadata=row,
                    uri=uri,
                    snapshot_sha256=receipt["snapshot_sha256"],
                )
            )
    return observations, [], receipts


def _community_row(
    source: dict[str, Any],
    *,
    external_id: str,
    title: str,
    body: str,
    url: str,
    observed_at: str | None,
    score: int | float | None,
    snapshot_sha256: str | None,
    metadata: dict[str, Any],
    excerpt_chars: int,
) -> dict[str, Any]:
    text = _clean_text(f"{title}\n{body}", max(excerpt_chars * 3, 4000))
    metrics = [
        {
            "value": float(match.group("value")),
            "unit": match.group("unit").lower(),
            "text": match.group(0),
        }
        for match in COMMUNITY_METRIC.finditer(text)
    ][:50]
    model_tokens = sorted({match.group(0) for match in MODEL_TOKEN.finditer(text)})
    topics = []
    topic_patterns = {
        "coding": r"\b(code|coding|swe-bench|aider|repo|patch|compile|test)\b",
        "reasoning": r"\b(reasoning|math|aime|gpqa|logic)\b",
        "long-context": r"\b(long context|1m context|million token|kv cache|prefill)\b",
        "throughput": r"\b(tok/s|tokens/s|latency|throughput|ttft)\b",
        "memory": r"\b(vram|ram|memory|oom|offload|nvme)\b",
        "tool-use": r"\b(tool call|function call|agent|browser|shell)\b",
        "pricing": r"\b(price|cost|token price|subscription|api)\b",
        "correctness": r"\b(bug|wrong|incorrect|regression|crash|nan)\b",
    }
    for topic, pattern in topic_patterns.items():
        if re.search(pattern, text, re.I):
            topics.append(topic)
    identifier = hashlib.sha256(
        f"{source['id']}\0{external_id}".encode("utf-8")
    ).hexdigest()[:24]
    row = {
        "id": f"community-{identifier}",
        "source_id": source["id"],
        "source_kind": source["kind"],
        "external_id": external_id,
        "observed_at": observed_at or now_utc(),
        "url": url,
        "title": _clean_text(title, 500),
        "excerpt": _clean_text(body, excerpt_chars),
        "score": score,
        "topics": topics,
        "metrics": metrics,
        "model_tokens": model_tokens,
        "evidence_tier": source["evidence_tier"],
        "verified": source["verified"],
        "training_use": source["training_use"],
        "tainted": True,
        "snapshot_sha256": snapshot_sha256,
        "metadata": metadata,
    }
    row["item_sha256"] = hash_json(
        {key: value for key, value in row.items() if key != "item_sha256"}
    )
    return row


def _sync_github(
    source: dict[str, Any], *, state_dir: Path, excerpt_chars: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    token = os.environ.get(source["token_env"])
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tier-bench-model-floor-v1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    items = []
    receipts = []
    for query in source["queries"]:
        uri = (
            "https://api.github.com/search/issues?"
            + urlencode({"q": query, "per_page": source["max_items_per_query"]})
        )
        value, response_headers, status, payload = _request_json(uri, headers=headers)
        receipt, _ = _snapshot(
            source,
            uri=uri,
            payload=payload,
            status=status,
            response_headers=response_headers,
            state_dir=state_dir,
        )
        receipts.append(receipt)
        rows = value.get("items") if isinstance(value, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            external_id = str(row.get("id") or row.get("html_url") or "")
            if not external_id:
                continue
            items.append(
                _community_row(
                    source,
                    external_id=external_id,
                    title=str(row.get("title") or ""),
                    body=str(row.get("body") or ""),
                    url=str(row.get("html_url") or ""),
                    observed_at=row.get("updated_at") or row.get("created_at"),
                    score=row.get("score"),
                    snapshot_sha256=receipt["snapshot_sha256"],
                    metadata={
                        "query": query,
                        "state": row.get("state"),
                        "comments": row.get("comments"),
                        "repository_url": row.get("repository_url"),
                        "is_pull_request": "pull_request" in row,
                    },
                    excerpt_chars=excerpt_chars,
                )
            )
    return [], items, receipts


class RedditClient:
    def __init__(self, source: dict[str, Any]) -> None:
        if not source["approval_confirmed"]:
            raise ModelFloorError(
                f"{source['id']} is blocked: Reddit API approval has not been confirmed"
            )
        client_id = os.environ.get(source["client_id_env"])
        secret = os.environ.get(source["client_secret_env"])
        user_agent = os.environ.get(source["user_agent_env"])
        if not client_id or not secret or not user_agent:
            raise ModelFloorError(
                f"{source['id']} needs {source['client_id_env']}, "
                f"{source['client_secret_env']}, and {source['user_agent_env']}"
            )
        if user_agent.lower().strip() in {"python", "requests"}:
            raise ModelFloorError("Reddit user agent must be unique and descriptive")
        self.source = source
        self.client_id = client_id
        self.secret = secret
        self.user_agent = user_agent
        self.token: str | None = None

    def authenticate(self) -> None:
        auth = base64.b64encode(
            f"{self.client_id}:{self.secret}".encode("utf-8")
        ).decode("ascii")
        payload, _, _, _ = _request_json(
            "https://www.reddit.com/api/v1/access_token",
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode({"grant_type": "client_credentials"}).encode("ascii"),
        )
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise ModelFloorError("Reddit OAuth response did not contain access_token")
        self.token = token

    def search(self, subreddit: str, query: str, limit: int) -> tuple[Any, dict[str, str], int, bytes, str]:
        if not self.token:
            self.authenticate()
        uri = (
            f"https://oauth.reddit.com/r/{quote(subreddit)}/search?"
            + urlencode(
                {
                    "q": query,
                    "restrict_sr": "on",
                    "sort": "new",
                    "t": "all",
                    "limit": limit,
                    "raw_json": 1,
                }
            )
        )
        value, headers, status, payload = _request_json(
            uri,
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": self.user_agent,
            },
        )
        return value, headers, status, payload, uri


def _sync_reddit(
    source: dict[str, Any], *, state_dir: Path, excerpt_chars: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    client = RedditClient(source)
    items = []
    receipts = []
    for subreddit in source["subreddits"]:
        for query in source["queries"]:
            value, headers, status, payload, uri = client.search(
                subreddit, query, source["max_posts_per_query"]
            )
            receipt, _ = _snapshot(
                source,
                uri=uri,
                payload=payload,
                status=status,
                response_headers=headers,
                state_dir=state_dir,
            )
            receipts.append(receipt)
            children = nested_get(value, "data.children", [])
            if not isinstance(children, list):
                continue
            for child in children:
                row = child.get("data") if isinstance(child, dict) else None
                if not isinstance(row, dict):
                    continue
                external_id = str(row.get("name") or row.get("id") or "")
                if not external_id:
                    continue
                permalink = str(row.get("permalink") or "")
                items.append(
                    _community_row(
                        source,
                        external_id=external_id,
                        title=str(row.get("title") or ""),
                        body=str(row.get("selftext") or ""),
                        url=("https://www.reddit.com" + permalink) if permalink else "",
                        observed_at=(
                            datetime.fromtimestamp(
                                float(row["created_utc"]), tz=timezone.utc
                            ).isoformat().replace("+00:00", "Z")
                            if isinstance(row.get("created_utc"), (int, float))
                            else None
                        ),
                        score=row.get("score"),
                        snapshot_sha256=receipt["snapshot_sha256"],
                        metadata={
                            "subreddit": subreddit,
                            "query": query,
                            "num_comments": row.get("num_comments"),
                            "upvote_ratio": row.get("upvote_ratio"),
                        },
                        excerpt_chars=excerpt_chars,
                    )
                )
    return [], items, receipts


def _mapped_observations(
    source: dict[str, Any],
    records: list[Any],
    *,
    snapshot_sha256: str,
    uri: str,
) -> list[dict[str, Any]]:
    mapping = source["mapping"]
    observations = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            continue
        model_id = nested_get(raw, mapping.get("model"))
        score = nested_get(raw, mapping.get("score"))
        if not isinstance(model_id, str) or isinstance(score, bool) or not isinstance(
            score, (int, float)
        ):
            continue
        benchmark = dict(source["benchmark"])
        for target, mapping_key in (
            ("revision", "revision"),
            ("scaffold", "scaffold"),
            ("tools", "tools"),
            ("context_policy", "context_policy"),
        ):
            path = mapping.get(mapping_key)
            mapped = nested_get(raw, path) if path else None
            if mapped is not None:
                benchmark[target] = str(mapped)
        observations.append(
            _make_observation(
                source=source,
                external_id=str(nested_get(raw, mapping.get("id"), index)),
                model_id=model_id,
                runtime_id=(
                    str(nested_get(raw, mapping.get("runtime_id")))
                    if mapping.get("runtime_id")
                    and nested_get(raw, mapping.get("runtime_id")) is not None
                    else None
                ),
                surface_id=(
                    str(nested_get(raw, mapping.get("surface_id")))
                    if mapping.get("surface_id")
                    and nested_get(raw, mapping.get("surface_id")) is not None
                    else None
                ),
                benchmark=benchmark,
                value=float(score),
                rank=(
                    int(nested_get(raw, mapping.get("rank")))
                    if mapping.get("rank")
                    and isinstance(nested_get(raw, mapping.get("rank")), int)
                    else None
                ),
                sample_size=(
                    int(nested_get(raw, mapping.get("sample_size")))
                    if mapping.get("sample_size")
                    and isinstance(nested_get(raw, mapping.get("sample_size")), int)
                    else None
                ),
                cost_usd=(
                    float(nested_get(raw, mapping.get("cost_usd")))
                    if mapping.get("cost_usd")
                    and isinstance(nested_get(raw, mapping.get("cost_usd")), (int, float))
                    else None
                ),
                latency_ms=(
                    float(nested_get(raw, mapping.get("latency_ms")))
                    if mapping.get("latency_ms")
                    and isinstance(nested_get(raw, mapping.get("latency_ms")), (int, float))
                    else None
                ),
                verified=(
                    bool(nested_get(raw, mapping.get("verified")))
                    if mapping.get("verified")
                    else None
                ),
                metadata={"raw": raw},
                uri=uri,
                snapshot_sha256=snapshot_sha256,
            )
        )
    return observations


def _sync_http_json(
    source: dict[str, Any], *, state_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    headers = {"User-Agent": "tier-bench-model-floor-v1"}
    token_env = source.get("token_env")
    if token_env and os.environ.get(token_env):
        headers["Authorization"] = f"Bearer {os.environ[token_env]}"
    value, response_headers, status, payload = _request_json(source["url"], headers=headers)
    receipt, _ = _snapshot(
        source,
        uri=source["url"],
        payload=payload,
        status=status,
        response_headers=response_headers,
        state_dir=state_dir,
    )
    records_path = source["mapping"].get("records")
    records = nested_get(value, records_path) if records_path else value
    if not isinstance(records, list):
        raise ModelFloorError(f"{source['id']} mapped records must be an array")
    return (
        _mapped_observations(
            source,
            records,
            snapshot_sha256=receipt["snapshot_sha256"],
            uri=source["url"],
        ),
        [],
        [receipt],
    )


def _sync_http_csv(
    source: dict[str, Any], *, state_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    headers = {"User-Agent": "tier-bench-model-floor-v1"}
    token_env = source.get("token_env")
    if token_env and os.environ.get(token_env):
        headers["Authorization"] = f"Bearer {os.environ[token_env]}"
    payload, response_headers, status = _request(source["url"], headers=headers)
    receipt, _ = _snapshot(
        source,
        uri=source["url"],
        payload=payload,
        status=status,
        response_headers=response_headers,
        state_dir=state_dir,
    )
    text = payload.decode("utf-8-sig")
    records = list(csv.DictReader(io.StringIO(text)))
    mapping = source["mapping"]
    converted = []
    numeric_fields = {"score", "cost_usd", "latency_ms", "sample_size", "rank"}
    for row in records:
        value = dict(row)
        for field in numeric_fields:
            column = mapping.get(field)
            if column and value.get(column) not in {None, ""}:
                try:
                    value[column] = float(value[column])
                    if field in {"sample_size", "rank"}:
                        value[column] = int(value[column])
                except ValueError:
                    pass
        converted.append(value)
    return (
        _mapped_observations(
            source,
            converted,
            snapshot_sha256=receipt["snapshot_sha256"],
            uri=source["url"],
        ),
        [],
        [receipt],
    )


def _sync_atom(
    source: dict[str, Any], *, state_dir: Path, excerpt_chars: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items = []
    receipts = []
    namespaces = {"atom": "http://www.w3.org/2005/Atom"}
    for uri in source["urls"]:
        payload, headers, status = _request(
            uri, headers={"User-Agent": "tier-bench-model-floor-v1"}
        )
        receipt, _ = _snapshot(
            source,
            uri=uri,
            payload=payload,
            status=status,
            response_headers=headers,
            state_dir=state_dir,
        )
        receipts.append(receipt)
        try:
            tree = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ModelFloorError(f"invalid Atom feed {uri}: {exc}") from exc
        entries = tree.findall("atom:entry", namespaces) or tree.findall("item")
        for index, entry in enumerate(entries):
            def text(name: str) -> str:
                node = entry.find(f"atom:{name}", namespaces) or entry.find(name)
                return node.text.strip() if node is not None and node.text else ""
            link_node = entry.find("atom:link", namespaces) or entry.find("link")
            link = ""
            if link_node is not None:
                link = link_node.attrib.get("href") or (link_node.text or "")
            external_id = text("id") or text("guid") or link or str(index)
            items.append(
                _community_row(
                    source,
                    external_id=external_id,
                    title=text("title"),
                    body=text("summary") or text("content") or text("description"),
                    url=link,
                    observed_at=text("updated") or text("published") or text("pubDate") or None,
                    score=None,
                    snapshot_sha256=receipt["snapshot_sha256"],
                    metadata={"feed": uri},
                    excerpt_chars=excerpt_chars,
                )
            )
    return [], items, receipts


def _sync_import(
    source: dict[str, Any], *, state_dir: Path, excerpt_chars: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    observations = []
    community = []
    receipts = []
    for path_text in source["paths"]:
        path = Path(path_text)
        payload = path.read_bytes()
        receipt, _ = _snapshot(
            source,
            uri=path.resolve().as_uri(),
            payload=payload,
            status=None,
            response_headers=None,
            state_dir=state_dir,
        )
        receipts.append(receipt)
        for index, row in enumerate(read_jsonl(path)):
            if row.get("schema") == OBSERVATION_SCHEMA:
                record = dict(row)
                record.setdefault("source", {})
                record["source"] = {
                    **record["source"],
                    "id": source["id"],
                    "kind": source["kind"],
                    "snapshot_sha256": receipt["snapshot_sha256"],
                }
                record.setdefault("evidence", {})
                record["evidence"] = {
                    **record["evidence"],
                    "tier": source["evidence_tier"],
                    "verified": source["verified"],
                    "training_use": source["training_use"],
                }
                record["observation_sha256"] = hash_json(
                    {key: value for key, value in record.items() if key != "observation_sha256"}
                )
                observations.append(record)
                continue
            if source.get("benchmark") and isinstance(row.get("model_id"), str) and isinstance(
                row.get("score"), (int, float)
            ):
                observations.append(
                    _make_observation(
                        source=source,
                        external_id=str(row.get("id") or index),
                        model_id=row["model_id"],
                        runtime_id=row.get("runtime_id"),
                        surface_id=row.get("surface_id"),
                        benchmark={
                            **source["benchmark"],
                            **(row.get("benchmark") if isinstance(row.get("benchmark"), dict) else {}),
                        },
                        value=float(row["score"]),
                        rank=row.get("rank") if isinstance(row.get("rank"), int) else None,
                        sample_size=(
                            row.get("sample_size")
                            if isinstance(row.get("sample_size"), int)
                            else None
                        ),
                        cost_usd=(
                            float(row["cost_usd"])
                            if isinstance(row.get("cost_usd"), (int, float))
                            else None
                        ),
                        latency_ms=(
                            float(row["latency_ms"])
                            if isinstance(row.get("latency_ms"), (int, float))
                            else None
                        ),
                        attention_minutes=(
                            float(row["attention_minutes"])
                            if isinstance(row.get("attention_minutes"), (int, float))
                            else None
                        ),
                        verified=bool(row.get("verified", source["verified"])),
                        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                        uri=row.get("url") or path.resolve().as_uri(),
                        snapshot_sha256=receipt["snapshot_sha256"],
                        observed_at=row.get("observed_at"),
                    )
                )
                continue
            community.append(
                _community_row(
                    source,
                    external_id=str(row.get("id") or index),
                    title=str(row.get("title") or ""),
                    body=str(row.get("body") or row.get("excerpt") or ""),
                    url=str(row.get("url") or path.resolve().as_uri()),
                    observed_at=row.get("observed_at"),
                    score=row.get("score"),
                    snapshot_sha256=receipt["snapshot_sha256"],
                    metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                    excerpt_chars=excerpt_chars,
                )
            )
    return observations, community, receipts


def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = str(row.get(key) or "")
        if identifier:
            by_id[identifier] = row
    return [by_id[identifier] for identifier in sorted(by_id)]


def sync_sources(
    raw_config: Any,
    *,
    config_path: Path,
    state_dir: Path,
) -> dict[str, Any]:
    config = validate_source_config(raw_config, config_path=config_path)
    state_dir.mkdir(parents=True, exist_ok=True)
    existing_observations = read_jsonl(state_dir / "observations.jsonl", missing_ok=True)
    existing_community = read_jsonl(state_dir / "community.jsonl", missing_ok=True)
    observations = list(existing_observations)
    community = list(existing_community)
    source_receipts = []
    blocked = []
    errors = []
    for source in config["sources"]:
        if not source["enabled"]:
            blocked.append({"source_id": source["id"], "reason": "disabled"})
            continue
        try:
            if source["kind"] == "hf_leaderboard":
                result = _sync_hf_leaderboard(source, state_dir=state_dir)
            elif source["kind"] == "hf_official_benchmarks":
                result = _sync_hf_official(source, state_dir=state_dir)
            elif source["kind"] == "hf_model_evals":
                result = _sync_hf_model_evals(source, state_dir=state_dir)
            elif source["kind"] == "github_search":
                result = _sync_github(
                    source, state_dir=state_dir, excerpt_chars=config["excerpt_chars"]
                )
            elif source["kind"] == "reddit_oauth":
                if not source["approval_confirmed"]:
                    blocked.append(
                        {
                            "source_id": source["id"],
                            "reason": "reddit_api_approval_not_confirmed",
                        }
                    )
                    continue
                result = _sync_reddit(
                    source, state_dir=state_dir, excerpt_chars=config["excerpt_chars"]
                )
            elif source["kind"] == "http_json":
                result = _sync_http_json(source, state_dir=state_dir)
            elif source["kind"] == "http_csv":
                result = _sync_http_csv(source, state_dir=state_dir)
            elif source["kind"] == "atom":
                result = _sync_atom(
                    source, state_dir=state_dir, excerpt_chars=config["excerpt_chars"]
                )
            elif source["kind"] == "jsonl_import":
                result = _sync_import(
                    source, state_dir=state_dir, excerpt_chars=config["excerpt_chars"]
                )
            else:
                raise ModelFloorError(f"unsupported source kind: {source['kind']}")
            new_observations, new_community, receipts = result
            observations.extend(new_observations)
            community.extend(new_community)
            source_receipts.append(
                {
                    "source_id": source["id"],
                    "observations": len(new_observations),
                    "community_items": len(new_community),
                    "snapshots": [receipt["snapshot_sha256"] for receipt in receipts],
                }
            )
        except (ModelFloorError, OSError, ValueError) as exc:
            errors.append({"source_id": source["id"], "error": str(exc)})
    observations = _dedupe(observations, "id")
    community = _dedupe(community, "id")
    write_jsonl(state_dir / "observations.jsonl", observations)
    write_jsonl(state_dir / "community.jsonl", community)
    receipt = {
        "schema": SYNC_RECEIPT_SCHEMA,
        "created_at": now_utc(),
        "config_id": config["id"],
        "config_sha256": hash_json(config),
        "sources": source_receipts,
        "blocked": blocked,
        "errors": errors,
        "totals": {
            "observations": len(observations),
            "community_items": len(community),
            "sources_succeeded": len(source_receipts),
            "sources_blocked": len(blocked),
            "sources_failed": len(errors),
        },
    }
    receipt["sync_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "sync_sha256"}
    )
    write_json(state_dir / "last-sync.json", receipt)
    return receipt


def purge_state(state_dir: Path, *, retention_days: int) -> dict[str, Any]:
    threshold = time.time() - retention_days * 86400
    removed = []
    raw_root = state_dir / "raw"
    if raw_root.exists():
        for path in raw_root.rglob("*"):
            if path.is_file() and path.stat().st_mtime < threshold:
                path.unlink()
                removed.append(str(path))
    receipt = {
        "schema": "tier-bench/model-floor-purge@1",
        "created_at": now_utc(),
        "retention_days": retention_days,
        "removed": sorted(removed),
    }
    receipt["purge_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "purge_sha256"}
    )
    return receipt
