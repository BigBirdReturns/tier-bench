"""Community and upstream intelligence for Kimi K3 open-weight analysis."""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .kimi3_common import (
    CLAIM_SCHEMA,
    COMMUNITY_CONFIG_SCHEMA,
    COMMUNITY_ITEM_SCHEMA,
    COMMUNITY_SYNC_SCHEMA,
    FUSION_SCHEMA,
    KimiObservatoryError,
    append_jsonl,
    hash_json,
    load_json,
    need_array,
    need_bool,
    need_int,
    need_object,
    need_text,
    now_utc,
    read_jsonl,
    safe_id,
    sha256_stream,
    write_json,
)
from .kimi3_weights import DISSECTION_PLAN_SCHEMA

DEFAULT_TIMEOUT = 30.0
DEFAULT_EXCERPT_CHARS = 800
DEFAULT_RETENTION_DAYS = 90
SOURCE_KINDS = {
    "reddit_oauth",
    "github_search",
    "huggingface_model",
    "atom",
    "jsonl_import",
}
TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("download", re.compile(r"(download|shard|snapshot|hf_transfer|aria2)", re.I)),
    ("runtime-support", re.compile(r"(vllm|sglang|llama\.cpp|transformers|tensorrt|ollama|lm studio|runtime)", re.I)),
    ("quantization", re.compile(r"(quant|gguf|mxfp4|fp4|fp8|int4|q[234568]_|awq|gptq|imatrix)", re.I)),
    ("expert-offload", re.compile(r"(expert.*offload|offload.*expert|cpu offload|nvme|ram|paging|expert cache)", re.I)),
    ("router", re.compile(r"(router|routing|expert utilization|load balance|hot expert|cold expert)", re.I)),
    ("long-context", re.compile(r"(1m context|million token|long context|kda|kv cache|prefill|context)", re.I)),
    ("attention-residual", re.compile(r"(attnres|attention residual|residual mixing)", re.I)),
    ("vision", re.compile(r"(vision|image|video|multimodal|moonvit)", re.I)),
    ("tool-use", re.compile(r"(tool call|function call|agent|coding harness|kimi code)", re.I)),
    ("tokenizer", re.compile(r"(tokenizer|chat template|special token|bos|eos)", re.I)),
    ("correctness", re.compile(r"(bug|broken|incorrect|nan|segfault|crash|mismatch|regression)", re.I)),
    ("throughput", re.compile(r"(tok/s|tokens/s|throughput|latency|ttft|speed|slow|fast)", re.I)),
    ("memory", re.compile(r"(vram|memory|ram|gb|gib|oom|out of memory)", re.I)),
    ("license", re.compile(r"(license|commercial|terms|open weight|open source)", re.I)),
    ("benchmark", re.compile(r"(benchmark|score|eval|swe-bench|coding|pass@|accuracy)", re.I)),
    ("distillation", re.compile(r"(distill|lora|adapter|fine[- ]?tune|curriculum|trace dataset)", re.I)),
]
EXPERIMENT_MAP = {
    "download": ["K3-A00-download-convergence", "K3-A01-byte-custody"],
    "runtime-support": ["K3-D01-runtime-module-trace"],
    "quantization": ["K3-B04-precision-map", "K3-E02-ablation-grid"],
    "expert-offload": ["K3-B03-expert-estate", "K3-E01-expert-offload-simulator"],
    "router": ["K3-D02-router-utilization-grid"],
    "long-context": ["K3-D03-long-context-state"],
    "attention-residual": ["K3-B01-source-architecture-map", "K3-E02-ablation-grid"],
    "vision": ["K3-B01-source-architecture-map", "K3-D01-runtime-module-trace"],
    "tool-use": ["K3-F01-desktop-capture"],
    "tokenizer": ["K3-B01-source-architecture-map"],
    "correctness": ["K3-A02-index-concordance", "K3-D01-runtime-module-trace"],
    "throughput": ["K3-D03-long-context-state", "K3-E01-expert-offload-simulator"],
    "memory": ["K3-E01-expert-offload-simulator"],
    "license": [],
    "benchmark": ["K3-E02-ablation-grid"],
    "distillation": ["K3-F01-desktop-capture"],
}


def _clean_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _iso_from_unix(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def validate_community_config(raw: Any) -> dict[str, Any]:
    config = need_object(raw, "community config")
    if config.get("schema") != COMMUNITY_CONFIG_SCHEMA:
        raise KimiObservatoryError(f"community config schema must be {COMMUNITY_CONFIG_SCHEMA}")
    unknown = set(config) - {
        "schema",
        "id",
        "excerpt_chars",
        "retention_days",
        "training_use",
        "sources",
    }
    if unknown:
        raise KimiObservatoryError(f"unknown community config fields: {sorted(unknown)}")
    identifier = safe_id(config.get("id"), "community config id")
    excerpt_chars = need_int(
        config.get("excerpt_chars", DEFAULT_EXCERPT_CHARS),
        "excerpt_chars",
        low=0,
        high=4000,
    )
    retention_days = need_int(
        config.get("retention_days", DEFAULT_RETENTION_DAYS),
        "retention_days",
        low=1,
        high=3650,
    )
    if config.get("training_use") != "prohibited":
        raise KimiObservatoryError(
            "training_use must be 'prohibited'; community content is hypothesis input only"
        )
    sources_raw = need_array(config.get("sources"), "sources", nonempty=True)
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(sources_raw):
        row = need_object(value, f"sources[{index}]")
        source_id = safe_id(row.get("id"), f"sources[{index}].id")
        if source_id in seen:
            raise KimiObservatoryError(f"duplicate community source id: {source_id}")
        seen.add(source_id)
        kind = need_text(row.get("kind"), f"sources[{index}].kind")
        if kind not in SOURCE_KINDS:
            raise KimiObservatoryError(f"unsupported community source kind: {kind}")
        normalized = dict(row)
        normalized["id"] = source_id
        normalized["kind"] = kind
        normalized["enabled"] = need_bool(row.get("enabled", True), f"{source_id}.enabled")
        if kind == "reddit_oauth":
            normalized["approval_confirmed"] = need_bool(
                row.get("approval_confirmed", False),
                f"{source_id}.approval_confirmed",
            )
            normalized["subreddits"] = [
                need_text(item, f"{source_id}.subreddits", limit=50)
                for item in need_array(row.get("subreddits"), f"{source_id}.subreddits", nonempty=True)
            ]
            normalized["queries"] = [
                need_text(item, f"{source_id}.queries", limit=300)
                for item in need_array(row.get("queries"), f"{source_id}.queries", nonempty=True)
            ]
            normalized["include_comments"] = need_bool(
                row.get("include_comments", True),
                f"{source_id}.include_comments",
            )
            normalized["max_posts_per_query"] = need_int(
                row.get("max_posts_per_query", 50),
                f"{source_id}.max_posts_per_query",
                low=1,
                high=100,
            )
            normalized["max_comments_per_post"] = need_int(
                row.get("max_comments_per_post", 50),
                f"{source_id}.max_comments_per_post",
                low=0,
                high=500,
            )
            normalized["client_id_env"] = need_text(
                row.get("client_id_env", "REDDIT_CLIENT_ID"),
                f"{source_id}.client_id_env",
                limit=100,
            )
            normalized["client_secret_env"] = need_text(
                row.get("client_secret_env", "REDDIT_CLIENT_SECRET"),
                f"{source_id}.client_secret_env",
                limit=100,
            )
            normalized["user_agent_env"] = need_text(
                row.get("user_agent_env", "REDDIT_USER_AGENT"),
                f"{source_id}.user_agent_env",
                limit=100,
            )
        elif kind == "github_search":
            normalized["queries"] = [
                need_text(item, f"{source_id}.queries", limit=500)
                for item in need_array(row.get("queries"), f"{source_id}.queries", nonempty=True)
            ]
            normalized["token_env"] = need_text(
                row.get("token_env", "GITHUB_TOKEN"),
                f"{source_id}.token_env",
                limit=100,
            )
            normalized["max_items_per_query"] = need_int(
                row.get("max_items_per_query", 50),
                f"{source_id}.max_items_per_query",
                low=1,
                high=100,
            )
        elif kind == "huggingface_model":
            normalized["repos"] = [
                need_text(item, f"{source_id}.repos", limit=200)
                for item in need_array(row.get("repos"), f"{source_id}.repos", nonempty=True)
            ]
            normalized["token_env"] = need_text(
                row.get("token_env", "HF_TOKEN"),
                f"{source_id}.token_env",
                limit=100,
            )
        elif kind == "atom":
            normalized["urls"] = [
                need_text(item, f"{source_id}.urls", limit=1000)
                for item in need_array(row.get("urls"), f"{source_id}.urls", nonempty=True)
            ]
        elif kind == "jsonl_import":
            normalized["paths"] = [
                need_text(item, f"{source_id}.paths", limit=1000)
                for item in need_array(row.get("paths"), f"{source_id}.paths", nonempty=True)
            ]
        sources.append(normalized)
    return {
        "schema": COMMUNITY_CONFIG_SCHEMA,
        "id": identifier,
        "excerpt_chars": excerpt_chars,
        "retention_days": retention_days,
        "training_use": "prohibited",
        "sources": sources,
    }


def _request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any, dict[str, str]]:
    request = Request(url, headers=headers or {}, data=data)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        raise KimiObservatoryError(f"HTTP {exc.code} for {url}: {body}") from exc
    except URLError as exc:
        raise KimiObservatoryError(f"network failure for {url}: {exc}") from exc
    try:
        return json.loads(payload), response_headers
    except json.JSONDecodeError as exc:
        raise KimiObservatoryError(f"non-JSON response from {url}: {exc}") from exc


class RedditClient:
    def __init__(self, source: dict[str, Any], *, timeout: float) -> None:
        if not source["approval_confirmed"]:
            raise KimiObservatoryError(
                f"{source['id']} is blocked: Reddit API approval has not been confirmed"
            )
        client_id = os.environ.get(source["client_id_env"])
        client_secret = os.environ.get(source["client_secret_env"])
        user_agent = os.environ.get(source["user_agent_env"])
        if not client_id or not client_secret or not user_agent:
            raise KimiObservatoryError(
                f"{source['id']} needs {source['client_id_env']}, "
                f"{source['client_secret_env']}, and {source['user_agent_env']}"
            )
        if "python" == user_agent.lower().strip():
            raise KimiObservatoryError("Reddit user agent must be unique and descriptive")
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.timeout = timeout
        self.token: str | None = None
        self.token_expiry = 0.0
        self.last_rate: dict[str, str] = {}

    def _authenticate(self) -> None:
        encoded = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")
        payload, _ = _request_json(
            "https://www.reddit.com/api/v1/access_token",
            headers={
                "Authorization": "Basic " + encoded,
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode({"grant_type": "client_credentials", "scope": "read"}).encode(),
            timeout=self.timeout,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise KimiObservatoryError("Reddit OAuth response did not contain access_token")
        self.token = payload["access_token"]
        expires = payload.get("expires_in", 3600)
        self.token_expiry = time.time() + max(60, int(expires) - 60)

    def get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.token or time.time() >= self.token_expiry:
            self._authenticate()
        url = "https://oauth.reddit.com" + path + "?" + urlencode(params)
        payload, headers = _request_json(
            url,
            headers={
                "Authorization": "bearer " + str(self.token),
                "User-Agent": self.user_agent,
            },
            timeout=self.timeout,
        )
        self.last_rate = {
            key: headers[key]
            for key in ("x-ratelimit-used", "x-ratelimit-remaining", "x-ratelimit-reset")
            if key in headers
        }
        try:
            remaining = float(headers.get("x-ratelimit-remaining", "999"))
            reset = float(headers.get("x-ratelimit-reset", "0"))
        except ValueError:
            remaining, reset = 999.0, 0.0
        if remaining < 2 and reset > 0:
            time.sleep(min(reset + 1, 60))
        return payload


def _normalize_item(
    *,
    source_id: str,
    source_kind: str,
    external_id: str,
    url: str,
    title: str,
    excerpt: str,
    created_at: str | None,
    score: int | float | None,
    comment_count: int | None,
    metadata: dict[str, Any],
    excerpt_chars: int,
) -> dict[str, Any]:
    title = _clean_text(title, limit=500)
    excerpt = _clean_text(excerpt, limit=excerpt_chars)
    content_hash = hash_json(
        {
            "source_id": source_id,
            "external_id": external_id,
            "url": url,
            "title": title,
            "excerpt": excerpt,
        }
    )
    return {
        "schema": COMMUNITY_ITEM_SCHEMA,
        "id": f"{source_id}:{external_id}",
        "source_id": source_id,
        "source_kind": source_kind,
        "external_id": external_id,
        "url": url,
        "title": title,
        "excerpt": excerpt,
        "created_at": created_at,
        "fetched_at": now_utc(),
        "score": score,
        "comment_count": comment_count,
        "metadata": metadata,
        "content_sha256": content_hash,
        "taint": "untrusted_community_content",
        "training_use": "prohibited",
        "deleted": False,
    }


def _reddit_children(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    children = data.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


def _reddit_comment_rows(
    listing: Any,
    *,
    post_id: str,
    source: dict[str, Any],
    excerpt_chars: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stack = list(reversed(_reddit_children(listing)))
    while stack and len(rows) < limit:
        child = stack.pop()
        kind = child.get("kind")
        data = child.get("data")
        if kind != "t1" or not isinstance(data, dict):
            continue
        comment_id = data.get("name") or ("t1_" + str(data.get("id", "")))
        body = data.get("body", "")
        if body in {"[deleted]", "[removed]"}:
            continue
        permalink = data.get("permalink")
        url = "https://www.reddit.com" + permalink if isinstance(permalink, str) else ""
        rows.append(
            _normalize_item(
                source_id=source["id"],
                source_kind="reddit_comment",
                external_id=str(comment_id),
                url=url,
                title=f"Comment on {post_id}",
                excerpt=str(body),
                created_at=_iso_from_unix(data.get("created_utc")),
                score=data.get("score") if isinstance(data.get("score"), (int, float)) else None,
                comment_count=None,
                metadata={
                    "post_id": post_id,
                    "subreddit": data.get("subreddit"),
                    "parent_id": data.get("parent_id"),
                },
                excerpt_chars=excerpt_chars,
            )
        )
        replies = data.get("replies")
        if isinstance(replies, dict):
            stack.extend(reversed(_reddit_children(replies)))
    return rows


def _sync_reddit(
    source: dict[str, Any],
    *,
    excerpt_chars: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = RedditClient(source, timeout=timeout)
    subreddits = "+".join(source["subreddits"])
    items: dict[str, dict[str, Any]] = {}
    requests = 0
    for query in source["queries"]:
        payload = client.get(
            f"/r/{subreddits}/search",
            {
                "q": query,
                "restrict_sr": "on",
                "sort": "new",
                "t": "all",
                "limit": source["max_posts_per_query"],
                "raw_json": 1,
            },
        )
        requests += 1
        for child in _reddit_children(payload):
            if child.get("kind") != "t3" or not isinstance(child.get("data"), dict):
                continue
            data = child["data"]
            external_id = str(data.get("name") or ("t3_" + str(data.get("id", ""))))
            permalink = data.get("permalink")
            url = (
                "https://www.reddit.com" + permalink
                if isinstance(permalink, str)
                else str(data.get("url", ""))
            )
            item = _normalize_item(
                source_id=source["id"],
                source_kind="reddit_post",
                external_id=external_id,
                url=url,
                title=str(data.get("title", "")),
                excerpt=str(data.get("selftext", "")),
                created_at=_iso_from_unix(data.get("created_utc")),
                score=data.get("score") if isinstance(data.get("score"), (int, float)) else None,
                comment_count=(
                    data.get("num_comments") if isinstance(data.get("num_comments"), int) else None
                ),
                metadata={
                    "subreddit": data.get("subreddit"),
                    "query": query,
                    "is_self": data.get("is_self"),
                    "domain": data.get("domain"),
                },
                excerpt_chars=excerpt_chars,
            )
            items[item["id"]] = item
            if source["include_comments"] and source["max_comments_per_post"]:
                post_id = str(data.get("id", ""))
                comments = client.get(
                    f"/comments/{post_id}",
                    {
                        "limit": source["max_comments_per_post"],
                        "depth": 8,
                        "sort": "confidence",
                        "raw_json": 1,
                    },
                )
                requests += 1
                if isinstance(comments, list) and len(comments) > 1:
                    for comment in _reddit_comment_rows(
                        comments[1],
                        post_id=external_id,
                        source=source,
                        excerpt_chars=excerpt_chars,
                        limit=source["max_comments_per_post"],
                    ):
                        items[comment["id"]] = comment
    return list(items.values()), {
        "requests": requests,
        "rate": client.last_rate,
    }


def _sync_github(
    source: dict[str, Any],
    *,
    excerpt_chars: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = os.environ.get(source["token_env"])
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tier-bench-kimi3-observatory/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    items: dict[str, dict[str, Any]] = {}
    requests = 0
    rate: dict[str, str] = {}
    for query in source["queries"]:
        payload, response_headers = _request_json(
            "https://api.github.com/search/issues?"
            + urlencode(
                {
                    "q": query,
                    "sort": "updated",
                    "order": "desc",
                    "per_page": source["max_items_per_query"],
                }
            ),
            headers=headers,
            timeout=timeout,
        )
        requests += 1
        rate = {
            key: response_headers[key]
            for key in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")
            if key in response_headers
        }
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            continue
        for row in payload["items"]:
            if not isinstance(row, dict):
                continue
            external_id = str(row.get("node_id") or row.get("id"))
            item = _normalize_item(
                source_id=source["id"],
                source_kind="github_issue_or_pr",
                external_id=external_id,
                url=str(row.get("html_url", "")),
                title=str(row.get("title", "")),
                excerpt=str(row.get("body", "")),
                created_at=row.get("created_at") if isinstance(row.get("created_at"), str) else None,
                score=row.get("comments") if isinstance(row.get("comments"), int) else None,
                comment_count=row.get("comments") if isinstance(row.get("comments"), int) else None,
                metadata={
                    "query": query,
                    "updated_at": row.get("updated_at"),
                    "state": row.get("state"),
                    "labels": [
                        label.get("name")
                        for label in row.get("labels", [])
                        if isinstance(label, dict) and isinstance(label.get("name"), str)
                    ],
                    "repository_url": row.get("repository_url"),
                    "is_pull_request": isinstance(row.get("pull_request"), dict),
                },
                excerpt_chars=excerpt_chars,
            )
            items[item["id"]] = item
    return list(items.values()), {"requests": requests, "rate": rate}


def _sync_huggingface(
    source: dict[str, Any],
    *,
    excerpt_chars: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = os.environ.get(source["token_env"])
    headers = {"User-Agent": "tier-bench-kimi3-observatory/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    items: list[dict[str, Any]] = []
    requests = 0
    for repo in source["repos"]:
        payload, _ = _request_json(
            f"https://huggingface.co/api/models/{quote(repo, safe='/')}",
            headers=headers,
            timeout=timeout,
        )
        requests += 1
        if not isinstance(payload, dict):
            continue
        siblings = [
            {
                "rfilename": row.get("rfilename"),
                "size": row.get("size"),
                "blobId": row.get("blobId"),
            }
            for row in payload.get("siblings", [])
            if isinstance(row, dict)
        ]
        summary = {
            "sha": payload.get("sha"),
            "lastModified": payload.get("lastModified"),
            "private": payload.get("private"),
            "gated": payload.get("gated"),
            "downloads": payload.get("downloads"),
            "likes": payload.get("likes"),
            "library_name": payload.get("library_name"),
            "pipeline_tag": payload.get("pipeline_tag"),
            "tags": payload.get("tags", []),
            "siblings": siblings,
        }
        items.append(
            _normalize_item(
                source_id=source["id"],
                source_kind="huggingface_model_revision",
                external_id=repo + ":" + str(payload.get("sha", "unknown")),
                url=f"https://huggingface.co/{repo}",
                title=f"Hugging Face model revision: {repo}",
                excerpt=json.dumps(summary, sort_keys=True),
                created_at=(
                    payload.get("lastModified")
                    if isinstance(payload.get("lastModified"), str)
                    else None
                ),
                score=payload.get("downloads") if isinstance(payload.get("downloads"), int) else None,
                comment_count=None,
                metadata={"repo": repo, "revision": payload.get("sha"), "siblings": siblings},
                excerpt_chars=excerpt_chars,
            )
        )
    return items, {"requests": requests}


def _atom_text(entry: ET.Element, names: list[str]) -> str:
    for name in names:
        for child in entry.iter():
            if child.tag.rsplit("}", 1)[-1] == name and child.text:
                return child.text
    return ""


def _sync_atom(
    source: dict[str, Any],
    *,
    excerpt_chars: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    requests = 0
    for url in source["urls"]:
        request = Request(url, headers={"User-Agent": "tier-bench-kimi3-observatory/1"})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
        except (HTTPError, URLError) as exc:
            raise KimiObservatoryError(f"cannot fetch Atom/RSS feed {url}: {exc}") from exc
        requests += 1
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise KimiObservatoryError(f"invalid Atom/RSS feed {url}: {exc}") from exc
        entries = [
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] in {"entry", "item"}
        ]
        for entry in entries:
            external_id = _atom_text(entry, ["id", "guid", "link"])
            link = ""
            for child in entry.iter():
                if child.tag.rsplit("}", 1)[-1] == "link":
                    link = child.attrib.get("href") or (child.text or "")
                    if link:
                        break
            if not link:
                link = external_id
            title = _atom_text(entry, ["title"])
            excerpt = _atom_text(entry, ["summary", "content", "description"])
            created = _atom_text(entry, ["updated", "published", "pubDate"])
            item = _normalize_item(
                source_id=source["id"],
                source_kind="atom",
                external_id=external_id or hash_json({"url": url, "title": title, "created": created}),
                url=link,
                title=title,
                excerpt=excerpt,
                created_at=created or None,
                score=None,
                comment_count=None,
                metadata={"feed_url": url},
                excerpt_chars=excerpt_chars,
            )
            items.append(item)
    return items, {"requests": requests}


def _sync_jsonl_import(
    source: dict[str, Any],
    *,
    excerpt_chars: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    files = 0
    for raw_path in source["paths"]:
        path = Path(raw_path).expanduser().resolve()
        for row in read_jsonl(path):
            files += 1
            if row.get("schema") == COMMUNITY_ITEM_SCHEMA:
                item = dict(row)
                item["excerpt"] = _clean_text(item.get("excerpt"), limit=excerpt_chars)
                item["training_use"] = "prohibited"
                item["taint"] = "untrusted_community_content"
                items.append(item)
                continue
            external_id = str(row.get("id") or row.get("url") or hash_json(row))
            items.append(
                _normalize_item(
                    source_id=source["id"],
                    source_kind=str(row.get("source_kind", "manual_import")),
                    external_id=external_id,
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    excerpt=str(row.get("excerpt") or row.get("body") or row.get("text") or ""),
                    created_at=row.get("created_at") if isinstance(row.get("created_at"), str) else None,
                    score=row.get("score") if isinstance(row.get("score"), (int, float)) else None,
                    comment_count=(
                        row.get("comment_count") if isinstance(row.get("comment_count"), int) else None
                    ),
                    metadata={"import_path": str(path), "import_sha256": sha256_stream(path)},
                    excerpt_chars=excerpt_chars,
                )
            )
    return items, {"files": files}


def _latest_items(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        if row.get("schema") == COMMUNITY_ITEM_SCHEMA and isinstance(row.get("id"), str):
            latest[row["id"]] = row
    return latest


def sync_community(
    config_raw: Any,
    *,
    state_dir: Path,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    config = validate_community_config(config_raw)
    state_dir = state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    item_path = state_dir / "items.jsonl"
    existing = _latest_items(item_path)
    added = 0
    updated = 0
    unchanged = 0
    errors: list[dict[str, Any]] = []
    source_receipts: list[dict[str, Any]] = []

    for source in config["sources"]:
        if not source["enabled"]:
            source_receipts.append(
                {"source_id": source["id"], "status": "DISABLED", "items": 0}
            )
            continue
        try:
            if source["kind"] == "reddit_oauth":
                rows, details = _sync_reddit(
                    source,
                    excerpt_chars=config["excerpt_chars"],
                    timeout=timeout,
                )
            elif source["kind"] == "github_search":
                rows, details = _sync_github(
                    source,
                    excerpt_chars=config["excerpt_chars"],
                    timeout=timeout,
                )
            elif source["kind"] == "huggingface_model":
                rows, details = _sync_huggingface(
                    source,
                    excerpt_chars=config["excerpt_chars"],
                    timeout=timeout,
                )
            elif source["kind"] == "atom":
                rows, details = _sync_atom(
                    source,
                    excerpt_chars=config["excerpt_chars"],
                    timeout=timeout,
                )
            else:
                rows, details = _sync_jsonl_import(
                    source,
                    excerpt_chars=config["excerpt_chars"],
                )
            for row in rows:
                previous = existing.get(row["id"])
                if previous is None:
                    added += 1
                    append_jsonl(item_path, row)
                    existing[row["id"]] = row
                elif previous.get("content_sha256") != row.get("content_sha256"):
                    updated += 1
                    append_jsonl(item_path, row)
                    existing[row["id"]] = row
                else:
                    unchanged += 1
            source_receipts.append(
                {
                    "source_id": source["id"],
                    "kind": source["kind"],
                    "status": "SYNCED",
                    "items": len(rows),
                    "details": details,
                }
            )
        except KimiObservatoryError as exc:
            errors.append({"source_id": source["id"], "error": str(exc)})
            source_receipts.append(
                {
                    "source_id": source["id"],
                    "kind": source["kind"],
                    "status": "BLOCKED",
                    "items": 0,
                    "error": str(exc),
                }
            )

    receipt = {
        "schema": COMMUNITY_SYNC_SCHEMA,
        "created_at": now_utc(),
        "config_id": config["id"],
        "config_sha256": hash_json(config),
        "state_dir": str(state_dir),
        "item_ledger": {
            "path": str(item_path),
            "latest_items": len(existing),
            "sha256": sha256_stream(item_path) if item_path.exists() else None,
        },
        "sources": source_receipts,
        "totals": {
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "blocked_sources": len(errors),
        },
        "errors": errors,
        "training_use": "prohibited",
    }
    receipt["sync_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "sync_sha256"}
    )
    write_json(state_dir / "last-sync.json", receipt)
    return receipt


def purge_community(
    *,
    state_dir: Path,
    retention_days: int,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    item_path = state_dir / "items.jsonl"
    latest = _latest_items(item_path)
    current = as_of or datetime.now(timezone.utc)
    keep: list[dict[str, Any]] = []
    purged = 0
    for row in latest.values():
        fetched = row.get("fetched_at")
        try:
            stamp = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
        except ValueError:
            stamp = current
        if row.get("deleted") or (current - stamp).days > retention_days:
            purged += 1
            continue
        keep.append(row)
    temporary = item_path.with_suffix(".jsonl.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as handle:
        for row in sorted(keep, key=lambda item: item["id"]):
            handle.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
    temporary.replace(item_path)
    return {
        "schema": "tier-bench/kimi3-community-purge@1",
        "created_at": now_utc(),
        "retention_days": retention_days,
        "kept": len(keep),
        "purged": purged,
        "item_ledger_sha256": sha256_stream(item_path),
    }


def _topic_tags(text: str) -> list[str]:
    return sorted(topic for topic, pattern in TOPIC_PATTERNS if pattern.search(text))


def _evidence_tier(item: dict[str, Any], text: str) -> tuple[str, int, list[str]]:
    signals: list[str] = []
    lower = text.lower()
    official = item["source_kind"] in {"huggingface_model_revision"} or any(
        host in item.get("url", "")
        for host in ("kimi.com", "moonshot.ai", "github.com/MoonshotAI/")
    )
    if official:
        return "official_release", 90, ["official_source"]
    numeric = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:tok/s|tokens/s|gb|gib|mb|ms|s|%)\b", lower))
    hardware = bool(re.search(r"\b(3090|4090|5090|h100|h200|b200|a100|mi300|cpu|vram|ram)\b", lower))
    version = bool(re.search(r"\b(v?\d+\.\d+(?:\.\d+)?|commit|sha|revision|docker|cuda|rocm)\b", lower))
    command = bool(re.search(r"(--[a-z0-9_-]+|python |pip |git |docker |llama-cli|vllm|sglang)", lower))
    first_person = bool(re.search(r"\b(i ran|i tested|my result|on my|we measured|we ran)\b", lower))
    speculation = bool(re.search(r"\b(maybe|probably|i think|rumou?r|could be|might be|guess)\b", lower))
    for name, present in (
        ("numeric_measurement", numeric),
        ("hardware_named", hardware),
        ("version_named", version),
        ("command_or_recipe", command),
        ("first_person", first_person),
    ):
        if present:
            signals.append(name)
    if numeric and hardware and version and command:
        return "reproducible_receipt", 85, signals
    if (numeric and hardware) or (command and version) or (first_person and numeric):
        return "detailed_report", 65, signals
    if speculation:
        return "speculation", 20, signals + ["speculative_language"]
    return "assertion", 40, signals


def extract_claims(
    *,
    state_dir: Path,
    minimum_score: int = 0,
) -> dict[str, Any]:
    items = _latest_items(state_dir / "items.jsonl")
    claims: list[dict[str, Any]] = []
    for item in items.values():
        if item.get("deleted"):
            continue
        text = (item.get("title", "") + " " + item.get("excerpt", "")).strip()
        topics = _topic_tags(text)
        if not topics:
            continue
        tier, evidence_score, signals = _evidence_tier(item, text)
        social_score = item.get("score")
        social_component = 0
        if isinstance(social_score, (int, float)) and social_score > 0:
            social_component = min(10, int(math_log1p(float(social_score)) * 2))
        relevance = 20 if any(
            topic in topics
            for topic in (
                "runtime-support",
                "quantization",
                "expert-offload",
                "router",
                "long-context",
                "memory",
                "correctness",
            )
        ) else 10
        priority = min(100, evidence_score + social_component + relevance)
        if priority < minimum_score:
            continue
        claim_id = "claim-" + hash_json(
            {
                "item_id": item["id"],
                "content_sha256": item["content_sha256"],
                "topics": topics,
            }
        )[:20]
        claims.append(
            {
                "schema": CLAIM_SCHEMA,
                "id": claim_id,
                "created_at": now_utc(),
                "item_id": item["id"],
                "url": item["url"],
                "title": item["title"],
                "excerpt": item["excerpt"],
                "topics": topics,
                "evidence_tier": tier,
                "evidence_signals": signals,
                "priority": priority,
                "proposed_experiments": sorted(
                    {
                        experiment
                        for topic in topics
                        for experiment in EXPERIMENT_MAP.get(topic, [])
                    }
                ),
                "status": "UNVERIFIED",
                "taint": "untrusted_community_claim",
                "training_use": "prohibited",
            }
        )
    claims.sort(key=lambda row: (-row["priority"], row["id"]))
    claim_path = state_dir / "claims.jsonl"
    with claim_path.open("wb") as handle:
        for claim in claims:
            handle.write((json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n").encode())
    report = {
        "schema": "tier-bench/kimi3-community-claims@1",
        "created_at": now_utc(),
        "claims": len(claims),
        "by_tier": dict(Counter(row["evidence_tier"] for row in claims)),
        "by_topic": dict(
            Counter(topic for row in claims for topic in row["topics"])
        ),
        "claim_ledger": {
            "path": str(claim_path),
            "sha256": sha256_stream(claim_path),
        },
    }
    write_json(state_dir / "claim-report.json", report)
    return report


def math_log1p(value: float) -> float:
    # Local helper avoids importing math only for one bounded scoring operation.
    import math

    return math.log1p(value)


def fuse_claims_with_plan(
    *,
    claims_path: Path,
    dissection_plan_path: Path,
) -> dict[str, Any]:
    claims = read_jsonl(claims_path)
    plan = load_json(dissection_plan_path)
    if plan.get("schema") != DISSECTION_PLAN_SCHEMA:
        raise KimiObservatoryError("dissection plan has the wrong schema")
    orders = {row["id"]: row for row in plan.get("work_orders", [])}
    queue: list[dict[str, Any]] = []
    for claim in claims:
        if claim.get("schema") != CLAIM_SCHEMA:
            continue
        experiments = [
            experiment
            for experiment in claim.get("proposed_experiments", [])
            if experiment in orders
        ]
        queue.append(
            {
                "id": "hyp-" + claim["id"].removeprefix("claim-"),
                "claim_id": claim["id"],
                "priority": claim["priority"],
                "evidence_tier": claim["evidence_tier"],
                "topics": claim["topics"],
                "url": claim["url"],
                "status": "PROPOSED",
                "work_orders": experiments,
                "local_control_questions": [
                    _control_question(topic) for topic in claim["topics"]
                ],
                "promotion_rule": (
                    "No community claim is promoted until at least one frozen local or "
                    "full-runtime experiment reproduces it with receipts."
                ),
            }
        )
    queue.sort(key=lambda row: (-row["priority"], row["id"]))
    result = {
        "schema": FUSION_SCHEMA,
        "created_at": now_utc(),
        "claims_sha256": sha256_stream(claims_path),
        "dissection_plan_sha256": plan["plan_sha256"],
        "hypotheses": queue,
        "totals": {
            "hypotheses": len(queue),
            "with_work_orders": sum(1 for row in queue if row["work_orders"]),
            "unmapped": sum(1 for row in queue if not row["work_orders"]),
        },
        "laws": [
            "Social score never substitutes for evidence tier.",
            "A Reddit post or comment may open an experiment but cannot close it.",
            "Community content is excluded from training artifacts unless separately licensed.",
            "Conflicting reports remain visible and are resolved by frozen local experiments.",
        ],
    }
    result["queue_sha256"] = hash_json(
        {key: value for key, value in result.items() if key != "queue_sha256"}
    )
    return result


def _control_question(topic: str) -> str:
    questions = {
        "download": "Are the observed shard names, sizes, and revisions complete and stable?",
        "runtime-support": "Which exact runtime commit executes the frozen K3 revision correctly?",
        "quantization": "Does the proposed quantization preserve the frozen grid at lower resource cost?",
        "expert-offload": "Does observed routing locality make the proposed expert tier faster than recomputation?",
        "router": "Does the reported expert specialization recur across frozen task families?",
        "long-context": "Does the claimed context gain survive source-grounded retrieval and correctness checks?",
        "attention-residual": "Which measured behavior changes when AttnRes is ablated under the same baseline?",
        "vision": "Does the exact open-weight runtime preserve native visual behavior and tool contracts?",
        "tool-use": "Does the claimed harness advantage survive equal tools, schemas, and acceptance?",
        "tokenizer": "Does the tokenizer or template change alter runtime behavior or baseline acceptance?",
        "correctness": "Can the reported failure be reproduced at the named revision and runtime?",
        "throughput": "Is throughput measured with the same precision, context, batch, and acceptance?",
        "memory": "What is the complete VRAM, RAM, NVMe, and transfer ledger for the claimed configuration?",
        "license": "What exact license text governs the downloaded revision and intended artifact?",
        "benchmark": "Does the benchmark result reproduce on the frozen task and grader revision?",
        "distillation": "Does the derived artifact clear fresh tasks without teacher calls?",
    }
    return questions.get(topic, f"Can the {topic} claim be reproduced under a frozen control?")
