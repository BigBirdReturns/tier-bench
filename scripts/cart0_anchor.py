#!/usr/bin/env python3
"""Opt-in CART0 catalog-anchor proposal/test harness; zero model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
from typing import Any


SPEC_SCHEMA = "tier-bench/cart0-anchor-spec@0"
CATALOG_SCHEMA = "tier-bench/cart0-card-catalog@0"
RECEIPT_SCHEMA = "tier-bench/cart0-anchor-receipt@1"
AB_SCHEMA = "tier-bench/cart0-anchor-ab-receipt@1"
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}")
CARD_ID = re.compile(r"[0-9]{3}\.[0-9]{3}\.[A-Z0-9_-]{1,48}")
REQUIRED_SPEC_FIELDS = {
    "schema", "anchor_id", "objective", "interpretation", "constraints",
    "position", "authorized_transition", "authority", "resurface_at",
    "evidence_paths",
}
POSITION_FIELDS = {"principal", "role", "lane", "branch", "state"}
CATALOG_FIELDS = {"schema", "catalog_id", "cards"}
CARD_FIELDS = {
    "card_id", "revision", "summary", "token_budget", "sources",
    "supersedes", "freshness", "authority", "review_status", "select_at",
}
SOURCE_FIELDS = {"path", "start_line", "end_line"}
SUPERSEDES_FIELDS = {"card_id", "revision"}


class AnchorError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def metrics(raw: bytes) -> dict[str, int]:
    text = raw.decode("utf-8")
    return {
        "utf8_bytes": len(raw),
        "unicode_characters": len(text),
        "whitespace_tokens": len(re.findall(r"\S+", text)),
        "approx_tokens_bytes_div_4": math.ceil(len(raw) / 4),
    }


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if result.returncode:
        raise AnchorError(
            f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def repo_root(repo: Path) -> Path:
    return Path(git(repo.resolve(), "rev-parse", "--show-toplevel").decode().strip()).resolve()


def safe_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnchorError(f"{label} must be a non-empty repository-relative path")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        normalized != path.as_posix()
        or path.is_absolute()
        or not path.parts
        or "." in path.parts
        or ".." in path.parts
        or path.parts[0].lower() == ".git"
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        raise AnchorError(f"{label} is not a canonical safe path: {value!r}")
    return path.as_posix()


def bounded_string(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnchorError(f"{label} must be a non-empty string")
    normalized = " ".join(value.split())
    if len(normalized.encode()) > limit:
        raise AnchorError(f"{label} exceeds {limit} UTF-8 bytes")
    return normalized


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnchorError(f"cannot read {label}: {exc}") from exc


def load_spec(path: Path) -> dict[str, Any]:
    value = read_json(path, "anchor spec")
    if not isinstance(value, dict) or set(value) != REQUIRED_SPEC_FIELDS:
        raise AnchorError("anchor spec fields do not match the proposal schema")
    if value["schema"] != SPEC_SCHEMA:
        raise AnchorError(f"anchor spec schema must be {SPEC_SCHEMA}")
    if not isinstance(value["anchor_id"], str) or not SAFE_ID.fullmatch(value["anchor_id"]):
        raise AnchorError("anchor_id is unsafe")
    value["objective"] = bounded_string(value["objective"], "objective", 280)
    value["interpretation"] = bounded_string(value["interpretation"], "interpretation", 280)
    value["authorized_transition"] = bounded_string(
        value["authorized_transition"], "authorized_transition", 240
    )
    value["authority"] = bounded_string(value["authority"], "authority", 240)
    constraints = value["constraints"]
    if not isinstance(constraints, list) or not 1 <= len(constraints) <= 6:
        raise AnchorError("constraints must contain between one and six entries")
    value["constraints"] = [
        bounded_string(item, f"constraints[{index}]", 180)
        for index, item in enumerate(constraints)
    ]
    position = value["position"]
    if not isinstance(position, dict) or set(position) != POSITION_FIELDS:
        raise AnchorError("position fields are invalid")
    value["position"] = {
        key: bounded_string(position[key], f"position.{key}", 100)
        for key in sorted(POSITION_FIELDS)
    }
    boundaries = value["resurface_at"]
    if (
        not isinstance(boundaries, list)
        or not boundaries
        or len(boundaries) != len(set(boundaries))
        or not all(isinstance(item, str) and SAFE_ID.fullmatch(item) for item in boundaries)
    ):
        raise AnchorError("resurface_at must contain unique safe boundary IDs")
    evidence = value["evidence_paths"]
    if not isinstance(evidence, list) or not evidence or len(evidence) > 12:
        raise AnchorError("evidence_paths must contain between one and twelve paths")
    normalized = [safe_path(item, f"evidence_paths[{index}]") for index, item in enumerate(evidence)]
    if len(normalized) != len(set(path.casefold() for path in normalized)):
        raise AnchorError("evidence_paths collide under case folding")
    value["evidence_paths"] = normalized
    return value


def load_catalog(path: Path) -> dict[str, Any]:
    value = read_json(path, "card catalog")
    if not isinstance(value, dict) or set(value) != CATALOG_FIELDS:
        raise AnchorError("card catalog fields do not match the proposal schema")
    if value["schema"] != CATALOG_SCHEMA:
        raise AnchorError(f"card catalog schema must be {CATALOG_SCHEMA}")
    if not isinstance(value["catalog_id"], str) or not SAFE_ID.fullmatch(value["catalog_id"]):
        raise AnchorError("catalog_id is unsafe")
    cards = value["cards"]
    if not isinstance(cards, list) or not 1 <= len(cards) <= 64:
        raise AnchorError("catalog must contain between one and 64 card revisions")
    normalized_cards: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for index, card in enumerate(cards):
        label = f"cards[{index}]"
        if not isinstance(card, dict) or set(card) != CARD_FIELDS:
            raise AnchorError(f"{label} fields are invalid")
        card_id = card["card_id"]
        revision = card["revision"]
        if not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
            raise AnchorError(f"{label}.card_id must be a stable Dewey-style ID")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise AnchorError(f"{label}.revision must be a positive integer")
        if (card_id, revision) in seen:
            raise AnchorError(f"duplicate card revision: {card_id} r{revision}")
        seen.add((card_id, revision))
        budget = card["token_budget"]
        if not isinstance(budget, int) or isinstance(budget, bool) or not 16 <= budget <= 256:
            raise AnchorError(f"{label}.token_budget must be between 16 and 256")
        sources = card["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 3:
            raise AnchorError(f"{label}.sources must contain between one and three pointers")
        normalized_sources = []
        for source_index, source in enumerate(sources):
            source_label = f"{label}.sources[{source_index}]"
            if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
                raise AnchorError(f"{source_label} fields are invalid")
            start = source["start_line"]
            end = source["end_line"]
            if (
                not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 1 or end < start
            ):
                raise AnchorError(f"{source_label} line range is invalid")
            normalized_sources.append({
                "path": safe_path(source["path"], f"{source_label}.path"),
                "start_line": start,
                "end_line": end,
            })
        boundaries = card["select_at"]
        if (
            not isinstance(boundaries, list) or not boundaries
            or len(boundaries) != len(set(boundaries))
            or not all(isinstance(item, str) and SAFE_ID.fullmatch(item) for item in boundaries)
        ):
            raise AnchorError(f"{label}.select_at must contain unique boundary IDs")
        supersedes = card["supersedes"]
        if supersedes is not None:
            if not isinstance(supersedes, dict) or set(supersedes) != SUPERSEDES_FIELDS:
                raise AnchorError(f"{label}.supersedes is invalid")
            if not isinstance(supersedes["card_id"], str) or not CARD_ID.fullmatch(supersedes["card_id"]):
                raise AnchorError(f"{label}.supersedes.card_id is invalid")
            if not isinstance(supersedes["revision"], int) or isinstance(supersedes["revision"], bool):
                raise AnchorError(f"{label}.supersedes.revision is invalid")
        normalized_cards.append({
            "card_id": card_id,
            "revision": revision,
            "summary": bounded_string(card["summary"], f"{label}.summary", 480),
            "token_budget": budget,
            "sources": normalized_sources,
            "supersedes": supersedes,
            "freshness": bounded_string(card["freshness"], f"{label}.freshness", 48),
            "authority": bounded_string(card["authority"], f"{label}.authority", 64),
            "review_status": bounded_string(
                card["review_status"], f"{label}.review_status", 48
            ),
            "select_at": boundaries,
        })
    by_id: dict[str, list[dict[str, Any]]] = {}
    for card in normalized_cards:
        by_id.setdefault(card["card_id"], []).append(card)
    for card_id, revisions in by_id.items():
        revisions.sort(key=lambda item: item["revision"])
        for offset, card in enumerate(revisions, 1):
            if card["revision"] != offset:
                raise AnchorError(f"{card_id} revisions must be contiguous from r1")
            expected = None if offset == 1 else {"card_id": card_id, "revision": offset - 1}
            if card["supersedes"] != expected:
                raise AnchorError(f"{card_id} r{offset} must supersede exactly its prior revision")
    value["cards"] = sorted(normalized_cards, key=lambda item: (item["card_id"], item["revision"]))
    return value


def evidence_at_head(repo: Path, head: str, paths: list[str]) -> list[dict[str, Any]]:
    opened = []
    for path in paths:
        raw = git(repo, "show", f"{head}:{path}")
        opened.append({
            "path": path,
            "blob_oid": git(repo, "rev-parse", f"{head}:{path}").decode().strip(),
            "sha256": sha256(raw),
            "utf8_bytes": len(raw),
        })
    return opened


def bind_source(repo: Path, head: str, source: dict[str, Any]) -> dict[str, Any]:
    raw = git(repo, "show", f"{head}:{source['path']}")
    lines = raw.splitlines(keepends=True)
    if source["end_line"] > len(lines):
        raise AnchorError(
            f"source range exceeds {source['path']}: {source['end_line']} > {len(lines)}"
        )
    span = b"".join(lines[source["start_line"] - 1:source["end_line"]])
    return {
        **source,
        "blob_oid": git(repo, "rev-parse", f"{head}:{source['path']}").decode().strip(),
        "file_sha256": sha256(raw),
        "span_sha256": sha256(span),
        "span_utf8_bytes": len(span),
    }


def active_cards(catalog: dict[str, Any], boundary: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for card in catalog["cards"]:
        latest[card["card_id"]] = card
    selected = sorted(
        (card for card in latest.values() if boundary in card["select_at"]),
        key=lambda item: item["card_id"],
    )
    if not selected:
        raise AnchorError(f"catalog selection miss: no cards declared for boundary {boundary!r}")
    if len(selected) > 6:
        raise AnchorError("catalog selected more than six active cards")
    return selected


def render_card(card: dict[str, Any], sources: list[dict[str, Any]]) -> bytes:
    pointers = "; ".join(
        f"{source['path']}:L{source['start_line']}-L{source['end_line']}"
        f"@{source['span_sha256'][:12]}"
        for source in sources
    )
    supersedes = card["supersedes"]
    prior = "-" if supersedes is None else f"{supersedes['card_id']} r{supersedes['revision']}"
    return (
        f"CARD {card['card_id']} r{card['revision']} "
        f"[{card['authority']}; {card['freshness']}; {card['review_status']}]\n"
        f"{card['summary']}\n"
        f"SRC {pointers}; full hashes/OIDs=receipt.json; SUPERSEDES {prior}\n"
    ).encode()


def project_cards(
    repo: Path, head: str, catalog: dict[str, Any], boundary: str
) -> list[tuple[dict[str, Any], bytes]]:
    projected = []
    for card in active_cards(catalog, boundary):
        sources = [bind_source(repo, head, source) for source in card["sources"]]
        raw = render_card(card, sources)
        card_metrics = metrics(raw)
        if card_metrics["approx_tokens_bytes_div_4"] > card["token_budget"]:
            raise AnchorError(
                f"card {card['card_id']} r{card['revision']} exceeds budget: "
                f"{card_metrics['approx_tokens_bytes_div_4']} > {card['token_budget']}"
            )
        filename = f"{card['card_id']}.r{card['revision']}.md"
        projected.append(({
            "card_id": card["card_id"],
            "revision": card["revision"],
            "filename": filename,
            "token_budget": card["token_budget"],
            "metrics": card_metrics,
            "sha256": sha256(raw),
            "authority": card["authority"],
            "freshness": card["freshness"],
            "review_status": card["review_status"],
            "supersedes": card["supersedes"],
            "sources": sources,
        }, raw))
    return projected


def render_anchor(
    spec: dict[str, Any], head: str, cards: list[dict[str, Any]], freshness: str
) -> bytes:
    position = spec["position"]
    card_ids = ",".join(f"{item['card_id']}r{item['revision']}" for item in cards)
    lines = [
        f"CART0 {spec['anchor_id']} [proposal]",
        f"O: {spec['objective']}",
        f"I: {spec['interpretation']}",
        *(f"C: {item}" for item in spec["constraints"]),
        (
            "P: "
            f"{position['principal']} / {position['role']} / {position['lane']} / "
            f"{position['branch']} / {position['state']}"
        ),
        f"N: {spec['authorized_transition']}",
        f"A: {spec['authority']}",
        f"K: {card_ids} (full evidence on demand via receipt.json)",
        f"F: HEAD {head[:12]} / {freshness[:16]}",
    ]
    return ("\n".join(lines) + "\n").encode()


def runtime_sha256() -> str:
    return sha256(Path(__file__).read_bytes())


def build(
    repo: Path,
    spec_path: Path,
    catalog_path: Path,
    output_dir: Path,
    boundary: str,
    max_approx_tokens: int,
) -> dict[str, Any]:
    if max_approx_tokens < 1:
        raise AnchorError("max_approx_tokens must be positive")
    repo = repo_root(repo)
    spec = load_spec(spec_path)
    catalog = load_catalog(catalog_path)
    if boundary not in spec["resurface_at"]:
        raise AnchorError(f"boundary {boundary!r} is not declared by the anchor spec")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    evidence = evidence_at_head(repo, head, spec["evidence_paths"])
    projected = project_cards(repo, head, catalog, boundary)
    cards = [item[0] for item in projected]
    evidence_paths = {item["path"] for item in evidence}
    selected_paths = {source["path"] for card in cards for source in card["sources"]}
    if not selected_paths.issubset(evidence_paths):
        missing = sorted(selected_paths - evidence_paths)
        raise AnchorError(f"selected card sources absent from baseline evidence_paths: {missing}")
    spec_sha = sha256(canonical_json(spec))
    catalog_sha = sha256(canonical_json(catalog))
    tool_sha = runtime_sha256()
    projection_profile_digest = sha256(canonical_json({
        "spec_sha256": spec_sha,
        "catalog_sha256": catalog_sha,
        "boundary": boundary,
    }))
    freshness = sha256(canonical_json({
        "event_head": head,
        "reducer_digest": tool_sha,
        "projection_profile_digest": projection_profile_digest,
    }))
    anchor = render_anchor(spec, head, cards, freshness)
    anchor_metrics = metrics(anchor)
    if anchor_metrics["approx_tokens_bytes_div_4"] > max_approx_tokens:
        raise AnchorError(
            "anchor exceeds the requested auditable proxy budget: "
            f"{anchor_metrics['approx_tokens_bytes_div_4']} > {max_approx_tokens}"
        )
    active_raw = anchor + b"\n" + b"\n".join(raw for _, raw in projected)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "anchor_id": spec["anchor_id"],
        "catalog_id": catalog["catalog_id"],
        "head": head,
        "boundary": boundary,
        "spec_sha256": spec_sha,
        "catalog_sha256": catalog_sha,
        "tool_sha256": tool_sha,
        "event_head": head,
        "reducer_digest": tool_sha,
        "projection_profile_digest": projection_profile_digest,
        "projection_digest": freshness,
        "freshness_sha256": freshness,
        "anchor_sha256": sha256(anchor),
        "anchor_metrics": anchor_metrics,
        "active_anchor_plus_cards_metrics": metrics(active_raw),
        "max_approx_tokens": max_approx_tokens,
        "cards": cards,
        "evidence": evidence,
        "raw_history_rewritten": False,
        "custody": "Git-object/hash-bound proposal; not a Genesis-signed shard",
        "scientific_claim_minted": False,
    }
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise AnchorError("output directory must be empty (append-only: use a new directory)")
    output_dir.mkdir(parents=True, exist_ok=True)
    cards_dir = output_dir / "cards"
    cards_dir.mkdir()
    (output_dir / "spec.json").write_bytes(canonical_json(spec))
    (output_dir / "catalog.json").write_bytes(canonical_json(catalog))
    (output_dir / "anchor.md").write_bytes(anchor)
    for metadata, raw in projected:
        (cards_dir / metadata["filename"]).write_bytes(raw)
    (output_dir / "receipt.json").write_bytes(canonical_json(receipt))
    return receipt


def verify(
    repo: Path, bundle: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes, list[bytes]]:
    repo = repo_root(repo)
    bundle = bundle.resolve()
    spec = load_spec(bundle / "spec.json")
    catalog = load_catalog(bundle / "catalog.json")
    receipt = read_json(bundle / "receipt.json", "anchor receipt")
    try:
        anchor = (bundle / "anchor.md").read_bytes()
    except OSError as exc:
        raise AnchorError(f"cannot open anchor: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise AnchorError("anchor receipt schema is invalid")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    if head != receipt.get("head"):
        raise AnchorError("anchor/cards are stale: repository HEAD changed")
    if head != receipt.get("event_head"):
        raise AnchorError("CART0 event_head drifted")
    if runtime_sha256() != receipt.get("tool_sha256"):
        raise AnchorError("anchor/cards are stale: projection tool bytes changed")
    if receipt.get("reducer_digest") != receipt.get("tool_sha256"):
        raise AnchorError("CART0 reducer digest drifted")
    if sha256(canonical_json(spec)) != receipt.get("spec_sha256"):
        raise AnchorError("anchor spec drifted")
    if sha256(canonical_json(catalog)) != receipt.get("catalog_sha256"):
        raise AnchorError("card catalog drifted")
    evidence = evidence_at_head(repo, head, spec["evidence_paths"])
    if evidence != receipt.get("evidence"):
        raise AnchorError("baseline evidence bindings drifted")
    projected = project_cards(repo, head, catalog, receipt.get("boundary", ""))
    cards = [item[0] for item in projected]
    if cards != receipt.get("cards"):
        raise AnchorError("card source bindings or projections drifted")
    expected_names = {metadata["filename"] for metadata, _ in projected}
    cards_dir = bundle / "cards"
    try:
        actual_names = {path.name for path in cards_dir.iterdir() if path.is_file()}
    except OSError as exc:
        raise AnchorError(f"cannot open projected cards: {exc}") from exc
    if actual_names != expected_names:
        raise AnchorError("projected card set drifted")
    card_raws = []
    for metadata, expected in projected:
        try:
            actual = (cards_dir / metadata["filename"]).read_bytes()
        except OSError as exc:
            raise AnchorError(f"cannot open projected card: {exc}") from exc
        if actual != expected:
            raise AnchorError(f"card projection drifted: {metadata['card_id']} r{metadata['revision']}")
        card_raws.append(actual)
    profile = sha256(canonical_json({
        "spec_sha256": receipt["spec_sha256"],
        "catalog_sha256": receipt["catalog_sha256"],
        "boundary": receipt["boundary"],
    }))
    if profile != receipt.get("projection_profile_digest"):
        raise AnchorError("projection profile digest drifted")
    freshness = sha256(canonical_json({
        "event_head": head,
        "reducer_digest": receipt["tool_sha256"],
        "projection_profile_digest": profile,
    }))
    expected_anchor = render_anchor(spec, head, cards, freshness)
    if (
        freshness != receipt.get("freshness_sha256")
        or freshness != receipt.get("projection_digest")
        or anchor != expected_anchor
    ):
        raise AnchorError("anchor projection or freshness digest drifted")
    if sha256(anchor) != receipt.get("anchor_sha256") or metrics(anchor) != receipt.get("anchor_metrics"):
        raise AnchorError("anchor hash or metrics drifted")
    if receipt["anchor_metrics"]["approx_tokens_bytes_div_4"] > receipt.get("max_approx_tokens", -1):
        raise AnchorError("anchor exceeds its frozen proxy budget")
    return spec, catalog, receipt, anchor, card_raws


def resurface(repo: Path, bundle: Path, boundary: str, task: str, output: Path | None) -> bytes:
    _, _, receipt, anchor, card_raws = verify(repo, bundle)
    if boundary != receipt["boundary"]:
        raise AnchorError(
            f"boundary {boundary!r} does not match bundle boundary {receipt['boundary']!r}; rebuild"
        )
    task = bounded_string(task, "task", 1000)
    prompt = (
        f"TASK BOUNDARY: {boundary}\nCURRENT TASK: {task}\n"
        "Use the active catalog below. Rehydrate a source only on a miss.\n\n"
    ).encode() + anchor + b"\nSELECTED CARDS\n" + b"\n".join(card_raws)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(prompt)
    return prompt


def rehydrate(repo: Path, bundle: Path, card_id: str, output: Path | None) -> bytes:
    repo = repo_root(repo)
    _, _, receipt, _, _ = verify(repo, bundle)
    matches = [card for card in receipt["cards"] if card["card_id"] == card_id]
    if not matches:
        raise AnchorError(f"retrieval miss: card {card_id!r} is not active in this bundle")
    head = receipt["head"]
    card = matches[0]
    sections = [f"REHYDRATED {card_id} r{card['revision']} @ HEAD {head}\n"]
    for source in card["sources"]:
        raw = git(repo, "show", f"{head}:{source['path']}")
        lines = raw.splitlines(keepends=True)
        span = b"".join(lines[source["start_line"] - 1:source["end_line"]]).decode("utf-8")
        sections.append(
            f"\n===== {source['path']}:L{source['start_line']}-L{source['end_line']} "
            f"sha256:{source['span_sha256']} =====\n{span}"
        )
    result = "".join(sections).encode()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(result)
    return result


def full_context_prompt(repo: Path, spec: dict[str, Any], boundary: str, task: str) -> bytes:
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    sections = [
        f"TASK BOUNDARY: {boundary}\nCURRENT TASK: {task}\n",
        "FULL CURRENT-STATE EVIDENCE FOLLOWS. Derive constraints and next action.\n",
    ]
    for path in spec["evidence_paths"]:
        raw = git(repo, "show", f"{head}:{path}")
        sections.append(f"\n===== {path} =====\n")
        sections.append(raw.decode("utf-8"))
    return "".join(sections).encode()


def failure_probes(repo: Path, bundle: Path, output_dir: Path) -> list[dict[str, Any]]:
    probes = []
    try:
        rehydrate(repo, bundle, "999.999.MISSING", None)
    except AnchorError as exc:
        probes.append({"probe": "retrieval_miss", "refused": True, "error": str(exc)})
    else:
        probes.append({"probe": "retrieval_miss", "refused": False, "error": None})
    stale_bundle = output_dir / "probe_stale_bundle"
    shutil.copytree(bundle, stale_bundle)
    card_path = sorted((stale_bundle / "cards").iterdir())[0]
    card_path.write_bytes(card_path.read_bytes() + b"STALE\n")
    try:
        verify(repo, stale_bundle)
    except AnchorError as exc:
        probes.append({"probe": "stale_or_tampered_card", "refused": True, "error": str(exc)})
    else:
        probes.append({"probe": "stale_or_tampered_card", "refused": False, "error": None})
    return probes


def ab_demo(
    repo: Path,
    spec_path: Path,
    catalog_path: Path,
    output_dir: Path,
    boundary: str,
    task: str,
    max_approx_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    repo = repo_root(repo)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise AnchorError("A/B output directory must be empty (append-only: use a new directory)")
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = output_dir / "bundle"
    build(repo, spec_path, catalog_path, bundle, boundary, max_approx_tokens)
    spec, catalog, receipt, _, _ = verify(repo, bundle)
    full_prompt = full_context_prompt(repo, spec, boundary, task)
    catalog_prompt = resurface(repo, bundle, boundary, task, None)
    (output_dir / "raw_input_spec.json").write_bytes(canonical_json(spec))
    (output_dir / "raw_input_catalog.json").write_bytes(canonical_json(catalog))
    (output_dir / "raw_output_A_full_context_prompt.txt").write_bytes(full_prompt)
    (output_dir / "raw_output_B_catalog_prompt.txt").write_bytes(catalog_prompt)
    probes = failure_probes(repo, bundle, output_dir)
    (output_dir / "failure_receipts.json").write_bytes(canonical_json(probes))
    a = metrics(full_prompt)
    b = metrics(catalog_prompt)
    wall_time_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    result = {
        "schema": AB_SCHEMA,
        "head": receipt["head"],
        "boundary": boundary,
        "task": task,
        "anchor_only": receipt["anchor_metrics"],
        "selected_card_count": len(receipt["cards"]),
        "A_full_context": {**a, "sha256": sha256(full_prompt)},
        "B_anchor_plus_selected_cards": {**b, "sha256": sha256(catalog_prompt)},
        "utf8_bytes_saved": a["utf8_bytes"] - b["utf8_bytes"],
        "approx_tokens_saved_bytes_div_4": (
            a["approx_tokens_bytes_div_4"] - b["approx_tokens_bytes_div_4"]
        ),
        "payload_reduction_fraction": round(1 - b["utf8_bytes"] / a["utf8_bytes"], 6),
        "failure_probes": probes,
        "wall_time_ms": wall_time_ms,
        "wall_time_scope": "build+verify, A/B projection/raw writes, and two refusal probes",
        "model_calls": 0,
        "model_output_tokens": None,
        "claim": "prompt-payload reduction and fail-closed lookup only; downstream quality unmeasured",
    }
    (output_dir / "ab_receipt.json").write_bytes(canonical_json(result))
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--repo", type=Path, default=Path("."))
    build_parser.add_argument("--spec", type=Path, required=True)
    build_parser.add_argument("--catalog", type=Path, required=True)
    build_parser.add_argument("--out", type=Path, required=True)
    build_parser.add_argument("--boundary", required=True)
    build_parser.add_argument("--max-approx-tokens", type=int, default=256)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--repo", type=Path, default=Path("."))
    verify_parser.add_argument("--bundle", type=Path, required=True)
    resurface_parser = sub.add_parser("resurface")
    resurface_parser.add_argument("--repo", type=Path, default=Path("."))
    resurface_parser.add_argument("--bundle", type=Path, required=True)
    resurface_parser.add_argument("--boundary", required=True)
    resurface_parser.add_argument("--task", required=True)
    resurface_parser.add_argument("--out", type=Path)
    rehydrate_parser = sub.add_parser("rehydrate")
    rehydrate_parser.add_argument("--repo", type=Path, default=Path("."))
    rehydrate_parser.add_argument("--bundle", type=Path, required=True)
    rehydrate_parser.add_argument("--card-id", required=True)
    rehydrate_parser.add_argument("--out", type=Path)
    ab_parser = sub.add_parser("ab-demo")
    ab_parser.add_argument("--repo", type=Path, default=Path("."))
    ab_parser.add_argument("--spec", type=Path, required=True)
    ab_parser.add_argument("--catalog", type=Path, required=True)
    ab_parser.add_argument("--out", type=Path, required=True)
    ab_parser.add_argument("--boundary", required=True)
    ab_parser.add_argument("--task", required=True)
    ab_parser.add_argument("--max-approx-tokens", type=int, default=256)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            result = build(
                args.repo, args.spec, args.catalog, args.out, args.boundary,
                args.max_approx_tokens,
            )
        elif args.command == "verify":
            _, _, result, _, _ = verify(args.repo, args.bundle)
        elif args.command == "resurface":
            prompt = resurface(args.repo, args.bundle, args.boundary, args.task, args.out)
            result = {"prompt_sha256": sha256(prompt), "prompt_metrics": metrics(prompt)}
        elif args.command == "rehydrate":
            evidence = rehydrate(args.repo, args.bundle, args.card_id, args.out)
            result = {"evidence_sha256": sha256(evidence), "evidence_metrics": metrics(evidence)}
        else:
            result = ab_demo(
                args.repo, args.spec, args.catalog, args.out, args.boundary,
                args.task, args.max_approx_tokens,
            )
    except AnchorError as exc:
        raise SystemExit(f"CART0_ANCHOR_REFUSED: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
