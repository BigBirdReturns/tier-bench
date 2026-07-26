"""Model Waterline Observatory.

This module turns model substitution claims into bounded, replayable experiments.
It compiles a frozen protocol and task catalog into Frontier Residue Refinery
survey campaigns, then analyzes verified campaign projections without treating
transport failures, runtime fallbacks, or missing attention records as capability
evidence.

The instrument is deliberately provider-neutral. Provider names, prices, model
IDs, and route order are data in the protocol.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Iterable

PROTOCOL_SCHEMA = "tier-bench/model-waterline-protocol@1"
TASKS_SCHEMA = "tier-bench/model-waterline-tasks@1"
COMPILED_SCHEMA = "tier-bench/model-waterline-compiled@1"
REPORT_SCHEMA = "tier-bench/model-waterline-report@1"
CATALOG_SCHEMA = "tier-bench/model-waterline-catalog@1"
CAMPAIGN_SCHEMA = "tier-bench/frontier-residue-campaign@1"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DECISIVE = {"pass", "fail"}
ROLES = {"candidate", "reference"}
LANES = {"native", "augmented"}
ROUTE_STATUS = {"ready", "blocked"}
COST_POLICIES = {"same_basis_only", "official_token_price"}
ATTENTION_POLICIES = {"required", "optional", "not_applicable"}
AUDIT_POLICIES = {"required", "optional", "not_applicable"}


class WaterlineError(RuntimeError):
    """Raised when a waterline artifact violates the frozen protocol."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_json(value: Any) -> str:
    return hashlib.sha256((canonical(value) + "\n").encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WaterlineError(f"cannot load JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WaterlineError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def required_text(value: Any, label: str, limit: int = 500) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise WaterlineError(f"{label} is required and must be at most {limit} characters")
    return text


def safe_id(value: Any, label: str, limit: int = 80) -> str:
    text = required_text(value, label, limit)
    if not SAFE_ID.fullmatch(text):
        raise WaterlineError(
            f"{label} may contain only letters, digits, dot, underscore, and dash"
        )
    return text


def nonnegative_number(value: Any, label: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise WaterlineError(f"{label} must be a non-negative number")
    return float(value)


def positive_int(value: Any, label: str, high: int = 10_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
        raise WaterlineError(f"{label} must be an integer between 1 and {high}")
    return value


def normalize_scope(raw: Any, label: str) -> str:
    text = required_text(raw, label, 500).replace("\\", "/")
    directory = text.endswith("/")
    pure = PurePosixPath(text.rstrip("/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts or pure.parts[0] == ".git":
        raise WaterlineError(f"{label} is not a safe repository-relative scope")
    return pure.as_posix() + ("/" if directory else "")


def validate_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise WaterlineError(f"protocol schema must be {PROTOCOL_SCHEMA}")
    protocol_id = safe_id(protocol.get("id"), "protocol.id", 80)
    required_text(protocol.get("title"), "protocol.title", 200)
    subject = required_text(protocol.get("subject_model"), "protocol.subject_model", 160)
    reference = required_text(protocol.get("reference_model"), "protocol.reference_model", 160)
    if subject == reference:
        raise WaterlineError("subject_model and reference_model must differ")

    settlement = protocol.get("settlement")
    if not isinstance(settlement, dict):
        raise WaterlineError("protocol.settlement must be an object")
    cell_k = positive_int(settlement.get("cell_k"), "settlement.cell_k", 10)
    family_min = positive_int(
        settlement.get("family_min_distinct_tasks"), "settlement.family_min_distinct_tasks", 1000
    )
    if family_min < cell_k:
        raise WaterlineError("family_min_distinct_tasks must be at least cell_k")
    cost_policy = settlement.get("cost_policy", "official_token_price")
    if cost_policy not in COST_POLICIES:
        raise WaterlineError(f"settlement.cost_policy must be one of {sorted(COST_POLICIES)}")
    attention_policy = settlement.get("attention_policy", "required")
    if attention_policy not in ATTENTION_POLICIES:
        raise WaterlineError(
            f"settlement.attention_policy must be one of {sorted(ATTENTION_POLICIES)}"
        )
    audit_policy = settlement.get("audit_policy", "required")
    if audit_policy not in AUDIT_POLICIES:
        raise WaterlineError(f"settlement.audit_policy must be one of {sorted(AUDIT_POLICIES)}")
    if settlement.get("family_claim") not in {"proposal_only", "descriptive_only"}:
        raise WaterlineError(
            "settlement.family_claim must be proposal_only or descriptive_only"
        )
    runtime_required = settlement.get("runtime_attestation_required")
    if runtime_required is not True:
        raise WaterlineError("runtime_attestation_required must be true")

    routes = protocol.get("routes")
    if not isinstance(routes, list) or not 2 <= len(routes) <= 32:
        raise WaterlineError("protocol.routes must contain between 2 and 32 routes")
    seen: set[str] = set()
    normalized_routes: list[dict[str, Any]] = []
    for index, raw in enumerate(routes):
        if not isinstance(raw, dict):
            raise WaterlineError(f"route {index} must be an object")
        route_id = safe_id(raw.get("id"), f"route {index}.id", 40)
        if route_id in seen:
            raise WaterlineError(f"duplicate route id: {route_id}")
        seen.add(route_id)
        role = raw.get("role")
        lane = raw.get("lane")
        status = raw.get("status", "ready")
        if role not in ROLES:
            raise WaterlineError(f"route {route_id}.role must be one of {sorted(ROLES)}")
        if lane not in LANES:
            raise WaterlineError(f"route {route_id}.lane must be one of {sorted(LANES)}")
        if status not in ROUTE_STATUS:
            raise WaterlineError(
                f"route {route_id}.status must be one of {sorted(ROUTE_STATUS)}"
            )
        model_id = required_text(raw.get("model_id"), f"route {route_id}.model_id", 160)
        effort = required_text(raw.get("effort"), f"route {route_id}.effort", 40)
        manifest = normalize_scope(raw.get("manifest"), f"route {route_id}.manifest")
        arm = raw.get("arm", "arm_b")
        if arm not in {"arm_a", "arm_b", "arm_c"}:
            raise WaterlineError(f"route {route_id}.arm is invalid")
        execution_class = raw.get("execution_class", "remote_unknown")
        if execution_class not in {
            "local",
            "remote_open_weight",
            "remote_closed",
            "remote_unknown",
        }:
            raise WaterlineError(f"route {route_id}.execution_class is invalid")
        source_access = raw.get("source_access", "unknown")
        if source_access not in {
            "source_and_weights",
            "weights",
            "runtime_source",
            "api_only",
            "subscription_only",
            "unknown",
        }:
            raise WaterlineError(f"route {route_id}.source_access is invalid")
        capability_basis = raw.get("capability_basis", "unmeasured")
        if capability_basis not in {"measured", "hypothesis", "unmeasured"}:
            raise WaterlineError(f"route {route_id}.capability_basis is invalid")
        resource_key = raw.get("resource_key")
        if resource_key is not None:
            resource_key = required_text(resource_key, f"route {route_id}.resource_key", 80)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:-]*", resource_key):
                raise WaterlineError(f"route {route_id}.resource_key contains unsafe characters")
        max_concurrency = positive_int(
            raw.get("max_concurrency", 1), f"route {route_id}.max_concurrency", 32
        )
        price = raw.get("price")
        if price is not None:
            if not isinstance(price, dict):
                raise WaterlineError(f"route {route_id}.price must be an object")
            for key in ("input_per_million", "output_per_million"):
                nonnegative_number(price.get(key), f"route {route_id}.price.{key}")
            if "cache_read_per_million" in price:
                nonnegative_number(
                    price.get("cache_read_per_million"),
                    f"route {route_id}.price.cache_read_per_million",
                )
            required_text(price.get("basis"), f"route {route_id}.price.basis", 80)
        if lane == "augmented":
            required_text(raw.get("augmentation_id"), f"route {route_id}.augmentation_id", 80)
        normalized_routes.append(
            {
                **raw,
                "id": route_id,
                "role": role,
                "lane": lane,
                "status": status,
                "model_id": model_id,
                "effort": effort,
                "manifest": manifest,
                "arm": arm,
                "execution_class": execution_class,
                "source_access": source_access,
                "capability_basis": capability_basis,
                "resource_key": resource_key,
                "max_concurrency": max_concurrency,
            }
        )

    references = [route for route in normalized_routes if route["role"] == "reference"]
    candidates = [route for route in normalized_routes if route["role"] == "candidate"]
    native_candidates = [route for route in candidates if route["lane"] == "native"]
    if not references or not candidates or not native_candidates:
        raise WaterlineError(
            "protocol needs at least one reference route, one candidate route, "
            "and one native candidate route"
        )
    if not any(route["model_id"] == reference for route in references):
        raise WaterlineError("reference routes do not include protocol.reference_model")
    if not any(route["model_id"] == subject for route in candidates):
        raise WaterlineError("candidate routes do not include protocol.subject_model")

    return {
        **protocol,
        "id": protocol_id,
        "routes": normalized_routes,
        "settlement": {
            **settlement,
            "cell_k": cell_k,
            "family_min_distinct_tasks": family_min,
            "cost_policy": cost_policy,
            "attention_policy": attention_policy,
            "audit_policy": audit_policy,
        },
    }


def validate_task_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("schema") != TASKS_SCHEMA:
        raise WaterlineError(f"task catalog schema must be {TASKS_SCHEMA}")
    safe_id(catalog.get("id"), "tasks.id", 80)
    tasks = catalog.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise WaterlineError("tasks.tasks must be a non-empty array")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(tasks):
        if not isinstance(raw, dict):
            raise WaterlineError(f"task {index} must be an object")
        task_id = safe_id(raw.get("id"), f"task {index}.id", 80)
        if task_id in seen:
            raise WaterlineError(f"duplicate task id: {task_id}")
        seen.add(task_id)
        status = raw.get("status", "ready")
        if status not in {"ready", "operator_task_required", "blocked"}:
            raise WaterlineError(f"task {task_id}.status is invalid")
        kind = raw.get("kind", "explicit")
        if kind not in {"explicit", "task_manifest"}:
            raise WaterlineError(f"task {task_id}.kind is invalid")
        required_text(raw.get("title", task_id), f"task {task_id}.title", 200)
        if kind == "explicit" and status == "ready":
            required_text(raw.get("task"), f"task {task_id}.task", 12_000)
            files = raw.get("files")
            if not isinstance(files, list) or not files:
                raise WaterlineError(f"task {task_id}.files must be a non-empty array")
            for number, scope in enumerate(files):
                normalize_scope(scope, f"task {task_id}.files[{number}]")
            required_text(raw.get("acceptance"), f"task {task_id}.acceptance", 8_000)
        if kind == "task_manifest":
            normalize_scope(raw.get("manifest"), f"task {task_id}.manifest")
        family = raw.get("family")
        if family is not None:
            safe_id(family, f"task {task_id}.family", 80)
        normalized.append({**raw, "id": task_id, "status": status, "kind": kind})
    return {**catalog, "tasks": normalized}


def _git_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise WaterlineError(f"cannot read target repository HEAD: {result.stderr.strip()}")
    head = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise WaterlineError("target repository HEAD is not a full lowercase Git SHA")
    return head


def _committed(repo: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{relative}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _manifest_task(repo: Path, entry: dict[str, Any]) -> dict[str, Any]:
    manifest_rel = normalize_scope(entry["manifest"], f"task {entry['id']}.manifest")
    manifest_path = repo / Path(*PurePosixPath(manifest_rel).parts)
    manifest = load_json(manifest_path)
    fixture_dir = normalize_scope(
        manifest.get("fixture_dir"), f"task {entry['id']}.fixture_dir"
    ).rstrip("/")
    target = normalize_scope(
        f"{fixture_dir}/{manifest.get('target_relpath', '')}",
        f"task {entry['id']}.target",
    )
    hidden = manifest.get("hidden_run_command")
    if not isinstance(hidden, list) or not hidden or not all(
        isinstance(part, str) and part for part in hidden
    ):
        raise WaterlineError(
            f"task {entry['id']} manifest has no usable hidden_run_command"
        )
    command = list(hidden)
    if command[0] in {"python", "python3", "py"} and len(command) >= 2:
        script = PurePosixPath(command[1])
        if script.is_absolute() or ".." in script.parts:
            raise WaterlineError(f"task {entry['id']} hidden grader path is unsafe")
        command[0] = "python"
        command[1] = f"{fixture_dir}/{script.as_posix()}"
    elif "acceptance" not in entry:
        raise WaterlineError(
            f"task {entry['id']} needs explicit acceptance for its hidden command"
        )
    acceptance = entry.get("acceptance") or subprocess.list2cmdline(command)
    prompt = entry.get("task") or (
        f"Implement {target} exactly to its governing written specification. "
        "Preserve all unrelated behavior and modify no other file. "
        "The decisive acceptance is withheld from the solver."
    )
    return {
        "id": entry["id"],
        "title": entry.get("title", entry["id"]),
        "family": entry.get("family"),
        "task": prompt,
        "files": [target],
        "acceptance": acceptance,
        "priority": int(entry.get("priority", 50)),
        "audit": {
            "kind": "hidden_grader",
            "manifest": manifest_rel,
            "hidden_files": manifest.get("hidden_files", []),
            "hidden_run_command": hidden,
        },
    }


def materialize_tasks(repo: Path, task_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for entry in task_catalog["tasks"]:
        if entry["status"] != "ready":
            continue
        if entry["kind"] == "task_manifest":
            task = _manifest_task(repo, entry)
        else:
            task = {
                "id": entry["id"],
                "title": entry.get("title", entry["id"]),
                "family": entry.get("family"),
                "task": required_text(entry.get("task"), f"task {entry['id']}.task", 12_000),
                "files": [
                    normalize_scope(scope, f"task {entry['id']}.files")
                    for scope in entry["files"]
                ],
                "acceptance": required_text(
                    entry.get("acceptance"), f"task {entry['id']}.acceptance", 8_000
                ),
                "priority": int(entry.get("priority", 50)),
                "audit": entry.get("audit", {"kind": "operator_declared"}),
            }
        tasks.append(task)
    if not tasks:
        raise WaterlineError("task catalog has no ready tasks")
    return tasks


def _campaign_id(protocol_id: str, task_id: str) -> str:
    raw = f"wl-{protocol_id}-{task_id}"
    if len(raw) <= 56 and SAFE_ID.fullmatch(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", f"wl-{protocol_id}")[:40].rstrip("-.")
    return f"{prefix}-{digest}"


def compile_campaigns(
    protocol: dict[str, Any],
    task_catalog: dict[str, Any],
    repo: Path,
    *,
    allow_unbound: bool = False,
) -> dict[str, Any]:
    protocol = validate_protocol(protocol)
    task_catalog = validate_task_catalog(task_catalog)
    repo = repo.resolve()
    head = _git_head(repo)
    tasks = materialize_tasks(repo, task_catalog)
    ready_routes = [route for route in protocol["routes"] if route["status"] == "ready"]
    blocked_routes = [route for route in protocol["routes"] if route["status"] != "ready"]
    if not ready_routes:
        raise WaterlineError("protocol has no ready routes")
    unbound = [route["manifest"] for route in ready_routes if not _committed(repo, route["manifest"])]
    if unbound and not allow_unbound:
        raise WaterlineError(
            "route manifests are not committed at target HEAD: " + ", ".join(sorted(unbound))
        )

    settlement = protocol["settlement"]
    max_trials = int(settlement.get("max_trials_per_route", max(3 * settlement["cell_k"], 5)))
    campaign_routes = []
    for route in ready_routes:
        row = {
            "id": route["id"],
            "label": route.get("label", route["id"]),
            "manifest": route["manifest"],
            "arm": route["arm"],
            "execution_class": route["execution_class"],
            "source_access": route["source_access"],
            "capability_basis": route["capability_basis"],
            "estimated_max_cost_usd": route.get("estimated_max_cost_usd"),
        }
        if route.get("resource_key"):
            row["resource_key"] = route["resource_key"]
            row["max_concurrency"] = route["max_concurrency"]
        campaign_routes.append(row)

    campaigns = []
    for task in tasks:
        campaign = {
            "schema": CAMPAIGN_SCHEMA,
            "id": _campaign_id(protocol["id"], task["id"]),
            "title": f"{protocol['title']} · {task['title']}",
            "mode": "survey",
            "k": settlement["cell_k"],
            "max_trials_per_route": max_trials,
            "queue_now": False,
            "task": {
                "task": task["task"],
                "files": task["files"],
                "acceptance": task["acceptance"],
                "priority": task["priority"],
            },
            "policy": {
                "max_total_cost_usd": settlement.get("max_total_cost_usd"),
                "max_remote_trials": settlement.get("max_remote_trials"),
                "materialize_candidates": True,
            },
            "routes": campaign_routes,
            "_waterline": {
                "protocol_id": protocol["id"],
                "protocol_sha256": hash_json(protocol),
                "task_catalog_id": task_catalog["id"],
                "task_id": task["id"],
                "family": task.get("family"),
                "audit": task.get("audit"),
                "target_head": head,
                "blocked_routes": [
                    {
                        "id": route["id"],
                        "reason": route.get("blocked_reason", "route is not yet runnable"),
                    }
                    for route in blocked_routes
                ],
                "unbound_manifests": sorted(unbound),
            },
        }
        campaigns.append(campaign)
    return {
        "schema": COMPILED_SCHEMA,
        "protocol_id": protocol["id"],
        "protocol_sha256": hash_json(protocol),
        "task_catalog_id": task_catalog["id"],
        "task_catalog_sha256": hash_json(task_catalog),
        "target_repo": str(repo),
        "target_head": head,
        "generated_at": datetime.now().astimezone().isoformat(),
        "allow_unbound": allow_unbound,
        "campaigns": campaigns,
    }


def write_compiled(compiled: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    index = {key: value for key, value in compiled.items() if key != "campaigns"}
    index["campaigns"] = []
    for campaign in compiled["campaigns"]:
        path = output_dir / f"{campaign['id']}.json"
        write_json(path, campaign)
        index["campaigns"].append(
            {
                "id": campaign["id"],
                "task_id": campaign["_waterline"]["task_id"],
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    write_json(output_dir / "INDEX.json", index)


def _last_ledger_row(receipt_path: str | None) -> dict[str, Any] | None:
    if not receipt_path:
        return None
    ledger = Path(receipt_path).parent / "ledger.jsonl"
    try:
        rows = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return None
    rows = [row for row in rows if isinstance(row, dict)]
    return rows[-1] if rows else None


def _trial_attestation(trial: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    result = trial.get("result") if isinstance(trial.get("result"), dict) else {}
    attested = result.get("runtime_attestation")
    if not isinstance(attested, dict):
        attested = _last_ledger_row(result.get("receipt_path")) or {}
    extra = attested.get("extra") if isinstance(attested.get("extra"), dict) else {}
    requested = str((route.get("binding") or {}).get("model_id") or route.get("model_id") or "")
    runtime = str(
        result.get("runtime_model_id")
        or extra.get("runtime_model_id")
        or attested.get("runtime_model_id")
        or ""
    )
    telemetry = result.get("telemetry_complete")
    if telemetry is None:
        telemetry = extra.get("telemetry_complete")
    requested_echo = str(attested.get("model") or requested)
    effort_echo = str(attested.get("effort") or (route.get("binding") or {}).get("effort") or "")
    basis = str(
        result.get("cost_basis")
        or extra.get("cost_basis")
        or (route.get("binding") or {}).get("cost_basis")
        or "unknown"
    )
    reasons = []
    if not runtime:
        reasons.append("runtime_model_missing")
    elif requested and runtime != requested:
        reasons.append("runtime_model_mismatch")
    if requested and requested_echo and requested_echo != requested:
        reasons.append("requested_model_echo_mismatch")
    if telemetry is not True:
        reasons.append("telemetry_incomplete")
    return {
        "requested_model_id": requested,
        "runtime_model_id": runtime or None,
        "requested_model_echo": requested_echo or None,
        "effort_echo": effort_echo or None,
        "cost_basis": basis,
        "valid": not reasons,
        "reasons": reasons,
    }


def _priced_cost(route_spec: dict[str, Any], result: dict[str, Any]) -> tuple[float | None, str]:
    price = route_spec.get("price")
    if not isinstance(price, dict):
        return None, "price_unavailable"
    input_tokens = int(result.get("input_tokens", 0) or 0)
    output_tokens = int(result.get("output_tokens", 0) or 0)
    cache_read = int(result.get("cache_read_tokens", 0) or 0)
    uncached = max(input_tokens - cache_read, 0)
    cache_price = price.get("cache_read_per_million")
    note = "official_token_price"
    if cache_price is None:
        cache_price = price["input_per_million"]
        note = "official_token_price_cache_at_full_input_rate"
    value = (
        uncached * float(price["input_per_million"])
        + cache_read * float(cache_price)
        + output_tokens * float(price["output_per_million"])
    ) / 1_000_000
    return value, note


def _pair_interventions(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    open_events: dict[str, dict[str, Any]] = {}
    by_task: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"minutes": 0.0, "clarifications": 0, "rescues": 0, "invalid": []}
    )
    for row in events:
        if not isinstance(row, dict):
            continue
        task_id = str(row.get("task_id") or "")
        intervention_id = str(row.get("intervention_id") or "")
        event = row.get("event")
        if not task_id or not intervention_id or event not in {"start", "stop"}:
            continue
        if event == "start":
            if intervention_id in open_events:
                by_task[task_id]["invalid"].append(f"duplicate_start:{intervention_id}")
            else:
                open_events[intervention_id] = row
            continue
        start = open_events.pop(intervention_id, None)
        if start is None:
            by_task[task_id]["invalid"].append(f"orphan_stop:{intervention_id}")
            continue
        try:
            a = datetime.fromisoformat(str(start["ts"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00"))
            seconds = (b - a).total_seconds()
            if seconds < 0:
                raise ValueError("negative interval")
        except (KeyError, ValueError, TypeError):
            by_task[task_id]["invalid"].append(f"invalid_interval:{intervention_id}")
            continue
        target = by_task[task_id]
        target["minutes"] += seconds / 60.0
        category = str(start.get("category") or row.get("category") or "")
        if category == "clarification":
            target["clarifications"] += 1
        if category == "rescue":
            target["rescues"] += 1
    for intervention_id, row in open_events.items():
        task_id = str(row.get("task_id") or "")
        by_task[task_id]["invalid"].append(f"unclosed:{intervention_id}")
    return dict(by_task)


def _route_summary(
    protocol_route: dict[str, Any],
    campaign_route: dict[str, Any],
    k: int,
    interventions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    valid_decisive: list[str] = []
    invalid_trials = []
    all_trials = campaign_route.get("trials")
    if not isinstance(all_trials, list):
        all_trials = []
    cost_total = 0.0
    observed_cost_total = 0.0
    priced = True
    price_notes: set[str] = set()
    successes = 0
    attention_minutes = 0.0
    clarifications = 0
    rescues = 0
    attention_invalid: list[str] = []
    for trial in all_trials:
        if not isinstance(trial, dict):
            continue
        result = trial.get("result") if isinstance(trial.get("result"), dict) else {}
        attestation = _trial_attestation(trial, campaign_route)
        outcome = trial.get("outcome")
        trial_id = str(trial.get("id") or trial.get("trial_id") or "")
        if outcome in DECISIVE and attestation["valid"]:
            valid_decisive.append(outcome)
            if outcome == "pass":
                successes += 1
        else:
            invalid_trials.append(
                {
                    "trial_id": trial_id,
                    "outcome": outcome,
                    "attestation": attestation,
                    "classification": (
                        "transport_or_attestation"
                        if outcome not in DECISIVE or not attestation["valid"]
                        else "unknown"
                    ),
                }
            )
        observed_cost_total += float(result.get("cost_usd", 0) or 0)
        trial_cost, price_note = _priced_cost(protocol_route, result)
        if trial_cost is None:
            priced = False
        else:
            cost_total += trial_cost
            price_notes.add(price_note)
        task_id = str(trial.get("task_id") or result.get("task_id") or "")
        attention = interventions.get(task_id)
        if attention:
            attention_minutes += float(attention["minutes"])
            clarifications += int(attention["clarifications"])
            rescues += int(attention["rescues"])
            attention_invalid.extend(attention["invalid"])
    window = valid_decisive[-k:]
    if len(window) < k:
        state = "collecting" if all_trials else "unmeasured"
    elif window.count("pass") == k:
        state = "clears"
    elif window.count("fail") == k:
        state = "wall"
    else:
        state = "unstable"
    return {
        "route_id": protocol_route["id"],
        "role": protocol_route["role"],
        "lane": protocol_route["lane"],
        "model_id": protocol_route["model_id"],
        "effort": protocol_route["effort"],
        "state": state,
        "k": k,
        "trial_count": len(all_trials),
        "valid_decisive": len(valid_decisive),
        "passes": valid_decisive.count("pass"),
        "failures": valid_decisive.count("fail"),
        "invalid_trials": invalid_trials,
        "priced_cost_usd": round(cost_total, 8) if priced else None,
        "priced_cost_basis": sorted(price_notes) if priced else ["price_unavailable"],
        "observed_cost_usd": round(observed_cost_total, 8),
        "cost_per_verified_success_usd": (
            round(cost_total / successes, 8) if priced and successes else None
        ),
        "attention_minutes": round(attention_minutes, 4) if interventions else None,
        "attention_per_verified_success": (
            round(attention_minutes / successes, 4)
            if interventions and successes and not attention_invalid
            else None
        ),
        "clarifications": clarifications if interventions else None,
        "rescues": rescues if interventions else None,
        "attention_invalid": sorted(set(attention_invalid)),
    }


def _audit_index(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        campaign_id = str(row.get("campaign_id") or "")
        route_id = str(row.get("route_id") or "")
        if campaign_id and route_id:
            result[(campaign_id, route_id)] = row
    return result


def _audit_for(
    campaign: dict[str, Any],
    route_id: str,
    external: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    campaign_id = str(campaign.get("id") or "")
    if (campaign_id, route_id) in external:
        return external[(campaign_id, route_id)]
    audits = campaign.get("waterline_audits")
    if not isinstance(audits, dict):
        return None
    value = audits.get(route_id)
    return value if isinstance(value, dict) else None


def _task_metadata(
    protocol: dict[str, Any],
    task_catalog: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if task_catalog is None:
        return {}
    catalog = validate_task_catalog(task_catalog)
    result = {}
    for task in catalog["tasks"]:
        result[_campaign_id(protocol["id"], task["id"])] = {
            "task_id": task["id"],
            "family": task.get("family"),
            "title": task.get("title", task["id"]),
            "status": task.get("status"),
        }
    return result


def _ratio(candidate: float | None, reference: float | None) -> float | None:
    if candidate is None or reference is None:
        return None
    if reference == 0:
        return 1.0 if candidate == 0 else None
    return candidate / reference


def _comparison_status(
    candidate: float | None,
    reference: float | None,
    *,
    tolerance: float = 1e-12,
) -> tuple[str, float | None]:
    ratio = _ratio(candidate, reference)
    if ratio is None:
        return "unmeasured", None
    return ("no_worse" if candidate <= reference + tolerance else "worse"), round(ratio, 6)


def analyze(
    protocol: dict[str, Any],
    campaigns: list[dict[str, Any]],
    *,
    task_catalog: dict[str, Any] | None = None,
    intervention_events: Iterable[dict[str, Any]] = (),
    audit_records: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    protocol = validate_protocol(protocol)
    k = int(protocol["settlement"]["cell_k"])
    intervention_map = _pair_interventions(intervention_events)
    audit_map = _audit_index(audit_records)
    metadata = _task_metadata(protocol, task_catalog)
    task_rows = []
    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue
        campaign_id = str(campaign.get("id") or "")
        waterline = (
            campaign.get("_waterline")
            if isinstance(campaign.get("_waterline"), dict)
            else {}
        )
        fallback_meta = metadata.get(campaign_id, {})
        task_id = str(
            waterline.get("task_id")
            or fallback_meta.get("task_id")
            or campaign_id
        )
        family = waterline.get("family")
        if family is None:
            family = fallback_meta.get("family")
        campaign_routes = campaign.get("routes")
        if not isinstance(campaign_routes, list):
            campaign_routes = []
        c_by_id = {
            str(route.get("route_id") or route.get("id")): route
            for route in campaign_routes
            if isinstance(route, dict)
        }
        summaries = []
        for route in protocol["routes"]:
            if route["status"] != "ready":
                continue
            campaign_route = c_by_id.get(
                route["id"], {"route_id": route["id"], "trials": []}
            )
            summaries.append(_route_summary(route, campaign_route, k, intervention_map))
        summary_by_id = {row["route_id"]: row for row in summaries}
        reference_clear = [
            route
            for route in protocol["routes"]
            if route["role"] == "reference"
            and route["status"] == "ready"
            and summary_by_id.get(route["id"], {}).get("state") == "clears"
        ]
        native_clear = [
            route
            for route in protocol["routes"]
            if route["role"] == "candidate"
            and route["lane"] == "native"
            and route["status"] == "ready"
            and summary_by_id.get(route["id"], {}).get("state") == "clears"
        ]
        augmented_clear = [
            route
            for route in protocol["routes"]
            if route["role"] == "candidate"
            and route["lane"] == "augmented"
            and route["status"] == "ready"
            and summary_by_id.get(route["id"], {}).get("state") == "clears"
        ]
        selected_reference = reference_clear[0]["id"] if reference_clear else None
        if not reference_clear:
            classification = "REFERENCE_NOT_CLEAR"
            selected = None
        elif native_clear:
            classification = "REPLICATED_NATIVE"
            selected = native_clear[0]["id"]
        elif augmented_clear:
            classification = "REPLICATED_AUGMENTED"
            selected = augmented_clear[0]["id"]
        else:
            candidate_states = [
                row["state"] for row in summaries if row["role"] == "candidate"
            ]
            classification = (
                "REFERENCE_RESIDUE"
                if candidate_states
                and all(state == "wall" for state in candidate_states)
                else "NO_DECISION"
            )
            selected = None

        economic_status = "not_applicable"
        economic_ratio = None
        attention_status = "not_applicable"
        attention_ratio = None
        audit_status = "not_applicable"
        candidate_audit = None
        reference_audit = None
        if selected and selected_reference:
            candidate_summary = summary_by_id[selected]
            reference_summary = summary_by_id[selected_reference]
            economic_status, economic_ratio = _comparison_status(
                candidate_summary["cost_per_verified_success_usd"],
                reference_summary["cost_per_verified_success_usd"],
            )
            attention_status, attention_ratio = _comparison_status(
                candidate_summary["attention_per_verified_success"],
                reference_summary["attention_per_verified_success"],
            )
            candidate_audit = _audit_for(campaign, selected, audit_map)
            reference_audit = _audit_for(campaign, selected_reference, audit_map)
            if candidate_audit is None or reference_audit is None:
                audit_status = "unmeasured"
            else:
                candidate_critical = int(
                    candidate_audit.get("critical_escaped_defects", 0) or 0
                )
                reference_critical = int(
                    reference_audit.get("critical_escaped_defects", 0) or 0
                )
                audit_status = (
                    "no_worse"
                    if candidate_critical <= reference_critical
                    else "worse"
                )

        task_rows.append(
            {
                "task_id": task_id,
                "family": family,
                "campaign_id": campaign_id,
                "classification": classification,
                "selected_route": selected,
                "selected_reference_route": selected_reference,
                "reference_routes_clear": [route["id"] for route in reference_clear],
                "economic_status": economic_status,
                "economic_cost_ratio": economic_ratio,
                "attention_status": attention_status,
                "attention_ratio": attention_ratio,
                "audit_status": audit_status,
                "candidate_audit": candidate_audit,
                "reference_audit": reference_audit,
                "route_summaries": summaries,
            }
        )

    comparable = [row for row in task_rows if row["reference_routes_clear"]]
    replicated = [
        row
        for row in comparable
        if row["classification"] in {"REPLICATED_NATIVE", "REPLICATED_AUGMENTED"}
    ]
    native = [
        row for row in comparable if row["classification"] == "REPLICATED_NATIVE"
    ]
    augmented = [
        row
        for row in comparable
        if row["classification"] == "REPLICATED_AUGMENTED"
    ]
    residue = [
        row for row in comparable if row["classification"] == "REFERENCE_RESIDUE"
    ]
    no_decision = [
        row
        for row in task_rows
        if row["classification"] in {"NO_DECISION", "REFERENCE_NOT_CLEAR"}
    ]
    settlement = protocol["settlement"]
    enough = len(comparable) >= int(settlement["family_min_distinct_tasks"])
    capability_status = (
        "INSUFFICIENT_DISTINCT_TASKS"
        if not enough
        else "PROPOSED_NATIVE_WATERLINE"
        if len(native) == len(comparable)
        else "PROPOSED_AUGMENTED_WATERLINE"
        if len(native) + len(augmented) == len(comparable)
        else "REFERENCE_RESIDUE_REMAINS"
    )

    blocked_reasons = []
    if not enough:
        blocked_reasons.append("insufficient_distinct_tasks")
    if capability_status in {
        "PROPOSED_NATIVE_WATERLINE",
        "PROPOSED_AUGMENTED_WATERLINE",
    }:
        economic_states = {row["economic_status"] for row in replicated}
        if "worse" in economic_states:
            blocked_reasons.append("economic_cost_worse")
        elif "unmeasured" in economic_states:
            blocked_reasons.append("economic_cost_unmeasured")

        if settlement["attention_policy"] == "required":
            attention_states = {row["attention_status"] for row in replicated}
            if "worse" in attention_states:
                blocked_reasons.append("attention_worse")
            elif "unmeasured" in attention_states:
                blocked_reasons.append("attention_unmeasured")

        if settlement["audit_policy"] == "required":
            audit_states = {row["audit_status"] for row in replicated}
            if "worse" in audit_states:
                blocked_reasons.append("escaped_defect_audit_worse")
            elif "unmeasured" in audit_states:
                blocked_reasons.append("escaped_defect_audit_unmeasured")

    attention_measured = bool(replicated) and all(
        row["attention_status"] in {"no_worse", "worse"} for row in replicated
    )
    audits_measured = bool(replicated) and all(
        row["audit_status"] in {"no_worse", "worse"} for row in replicated
    )
    economics_measured = bool(replicated) and all(
        row["economic_status"] in {"no_worse", "worse"} for row in replicated
    )
    waterline_status = capability_status if not blocked_reasons else "PARTIAL"
    return {
        "schema": REPORT_SCHEMA,
        "protocol_id": protocol["id"],
        "protocol_sha256": hash_json(protocol),
        "generated_at": datetime.now().astimezone().isoformat(),
        "waterline_status": waterline_status,
        "capability_status": capability_status,
        "claim_boundary": (
            "A proposed routing waterline is bounded to these distinct tasks. "
            "It is not a universal equivalence or non-inferiority claim."
        ),
        "blocked_reasons": blocked_reasons,
        "counts": {
            "campaigns": len(task_rows),
            "reference_clear_tasks": len(comparable),
            "native_replications": len(native),
            "augmented_replications": len(augmented),
            "reference_residue": len(residue),
            "no_decision": len(no_decision),
            "family_min_distinct_tasks": settlement["family_min_distinct_tasks"],
        },
        "economics_measured": economics_measured,
        "attention_measured": attention_measured,
        "audits_measured": audits_measured,
        "tasks": task_rows,
    }


def validate_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise WaterlineError(f"catalog schema must be {CATALOG_SCHEMA}")
    experiments = catalog.get("experiments")
    if not isinstance(experiments, list) or not experiments:
        raise WaterlineError("catalog.experiments must be a non-empty array")
    seen: set[str] = set()
    for index, row in enumerate(experiments):
        if not isinstance(row, dict):
            raise WaterlineError(f"catalog experiment {index} must be an object")
        experiment_id = safe_id(row.get("id"), f"catalog experiment {index}.id", 100)
        if experiment_id in seen:
            raise WaterlineError(f"duplicate catalog experiment id: {experiment_id}")
        seen.add(experiment_id)
        required_text(row.get("domain"), f"catalog {experiment_id}.domain", 80)
        required_text(row.get("question"), f"catalog {experiment_id}.question", 500)
        status = row.get("status")
        if status not in {"ready", "needs_adapter", "needs_tasks", "research"}:
            raise WaterlineError(f"catalog {experiment_id}.status is invalid")
        acceptance = row.get("acceptance")
        if acceptance not in {"deterministic", "hidden_audit", "blinded_human", "mixed"}:
            raise WaterlineError(f"catalog {experiment_id}.acceptance is invalid")
    return catalog


def _read_campaigns(path: Path) -> list[dict[str, Any]]:
    if path.is_file():
        value = load_json(path)
        if value.get("schema") == COMPILED_SCHEMA:
            return value.get("campaigns", [])
        return [value]
    campaigns = []
    for item in sorted(path.glob("*.json")):
        if item.name == "INDEX.json":
            continue
        value = load_json(item)
        if value.get("schema") == CAMPAIGN_SCHEMA or "routes" in value:
            campaigns.append(value)
    return campaigns


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WaterlineError(f"cannot read {path}: {exc}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WaterlineError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("validate", help="validate protocol, tasks, or catalog")
    check.add_argument("--protocol", type=Path)
    check.add_argument("--tasks", type=Path)
    check.add_argument("--catalog", type=Path)

    compile_parser = sub.add_parser(
        "compile", help="compile a protocol and tasks into residue survey campaigns"
    )
    compile_parser.add_argument("--protocol", type=Path, required=True)
    compile_parser.add_argument("--tasks", type=Path, required=True)
    compile_parser.add_argument("--repo", type=Path, required=True)
    compile_parser.add_argument("--out", type=Path, required=True)
    compile_parser.add_argument("--allow-unbound", action="store_true")

    analyze_parser = sub.add_parser(
        "analyze", help="analyze completed campaign projections"
    )
    analyze_parser.add_argument("--protocol", type=Path, required=True)
    analyze_parser.add_argument("--campaigns", type=Path, required=True)
    analyze_parser.add_argument(
        "--tasks", type=Path, help="task catalog used to restore task ids from live projections"
    )
    analyze_parser.add_argument("--interventions", type=Path)
    analyze_parser.add_argument("--audits", type=Path)
    analyze_parser.add_argument("--out", type=Path)

    catalog_parser = sub.add_parser("catalog", help="validate and summarize experiment catalog")
    catalog_parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            if not any((args.protocol, args.tasks, args.catalog)):
                raise WaterlineError("validate requires at least one input")
            result = {}
            if args.protocol:
                result["protocol"] = validate_protocol(load_json(args.protocol))["id"]
            if args.tasks:
                result["tasks"] = len(validate_task_catalog(load_json(args.tasks))["tasks"])
            if args.catalog:
                result["catalog"] = len(validate_catalog(load_json(args.catalog))["experiments"])
            print(json.dumps({"ok": True, **result}, indent=2))
            return 0
        if args.command == "compile":
            compiled = compile_campaigns(
                load_json(args.protocol),
                load_json(args.tasks),
                args.repo,
                allow_unbound=args.allow_unbound,
            )
            write_compiled(compiled, args.out)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "campaigns": len(compiled["campaigns"]),
                        "out": str(args.out),
                        "allow_unbound": compiled["allow_unbound"],
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "analyze":
            report = analyze(
                load_json(args.protocol),
                _read_campaigns(args.campaigns),
                task_catalog=load_json(args.tasks) if args.tasks else None,
                intervention_events=_read_jsonl(args.interventions),
                audit_records=_read_jsonl(args.audits),
            )
            if args.out:
                write_json(args.out, report)
            print(json.dumps(report, indent=2))
            return 0
        if args.command == "catalog":
            catalog = validate_catalog(load_json(args.catalog))
            domains: dict[str, int] = defaultdict(int)
            statuses: dict[str, int] = defaultdict(int)
            for row in catalog["experiments"]:
                domains[row["domain"]] += 1
                statuses[row["status"]] += 1
            print(
                json.dumps(
                    {
                        "ok": True,
                        "experiments": len(catalog["experiments"]),
                        "domains": dict(sorted(domains.items())),
                        "statuses": dict(sorted(statuses.items())),
                    },
                    indent=2,
                )
            )
            return 0
    except (WaterlineError, OSError, ValueError) as exc:
        print(f"tierwaterline: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
