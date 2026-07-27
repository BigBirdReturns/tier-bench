"""Model identity, alias, surface, and runtime-attestation contracts."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .model_floor_common import (
    IDENTITY_AUDIT_SCHEMA,
    ModelFloorError,
    REGISTRY_SCHEMA,
    hash_json,
    need_array,
    need_bool,
    need_int,
    need_number,
    need_object,
    need_text,
    now_utc,
    optional_text,
    safe_id,
    unique_by_id,
)

ACCESS_CLASSES = {"closed", "open_weight", "open_source", "mixed", "unknown"}
SURFACE_KINDS = {
    "api",
    "subscription_cli",
    "subscription_app",
    "local_runtime",
    "hosted_open_weight",
    "benchmark_report",
    "composite",
    "unknown",
}
SURFACE_STATUS = {"ready", "blocked", "retired", "unmeasured"}


@dataclass(frozen=True)
class RegistryIndex:
    registry: dict[str, Any]
    models: dict[str, dict[str, Any]]
    aliases: dict[str, str]
    surfaces: dict[str, tuple[str, dict[str, Any]]]


def _price(raw: Any, label: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = need_object(raw, label)
    allowed = {
        "input_per_million",
        "output_per_million",
        "cache_read_per_million",
        "cache_write_per_million",
        "basis",
        "currency",
        "effective_from",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ModelFloorError(f"{label} has unknown fields: {sorted(unknown)}")
    result: dict[str, Any] = {
        "input_per_million": need_number(
            value.get("input_per_million"), f"{label}.input_per_million", low=0
        ),
        "output_per_million": need_number(
            value.get("output_per_million"), f"{label}.output_per_million", low=0
        ),
        "basis": need_text(value.get("basis"), f"{label}.basis", limit=200),
        "currency": need_text(value.get("currency", "USD"), f"{label}.currency", limit=10),
    }
    for key in ("cache_read_per_million", "cache_write_per_million"):
        result[key] = need_number(value.get(key), f"{label}.{key}", low=0, allow_none=True)
    result["effective_from"] = optional_text(
        value.get("effective_from"), f"{label}.effective_from", limit=100
    )
    return result


def validate_registry(raw: Any) -> RegistryIndex:
    value = need_object(raw, "model registry")
    if value.get("schema") != REGISTRY_SCHEMA:
        raise ModelFloorError(f"model registry schema must be {REGISTRY_SCHEMA}")
    registry_id = safe_id(value.get("id"), "registry.id")
    models_raw = need_array(value.get("models"), "registry.models", nonempty=True)
    normalized: list[dict[str, Any]] = []
    alias_owner: dict[str, str] = {}
    surfaces: dict[str, tuple[str, dict[str, Any]]] = {}
    for index, item in enumerate(models_raw):
        row = need_object(item, f"models[{index}]")
        model_id = safe_id(row.get("id"), f"models[{index}].id")
        provider = safe_id(row.get("provider"), f"{model_id}.provider")
        family = safe_id(row.get("family", model_id), f"{model_id}.family")
        access = row.get("access", "unknown")
        if access not in ACCESS_CLASSES:
            raise ModelFloorError(f"{model_id}.access must be one of {sorted(ACCESS_CLASSES)}")
        aliases = [
            need_text(alias, f"{model_id}.aliases[]", limit=300)
            for alias in need_array(row.get("aliases", []), f"{model_id}.aliases")
        ]
        official_ids = [
            need_text(alias, f"{model_id}.official_ids[]", limit=300)
            for alias in need_array(row.get("official_ids", []), f"{model_id}.official_ids")
        ]
        for alias in [model_id, *aliases, *official_ids]:
            key = alias.casefold()
            existing = alias_owner.get(key)
            if existing and existing != model_id:
                raise ModelFloorError(
                    f"model alias {alias!r} belongs to both {existing} and {model_id}"
                )
            alias_owner[key] = model_id
        surface_rows = []
        for surface_index, surface_raw in enumerate(
            need_array(row.get("surfaces"), f"{model_id}.surfaces", nonempty=True)
        ):
            surface = need_object(surface_raw, f"{model_id}.surfaces[{surface_index}]")
            surface_id = safe_id(surface.get("id"), f"{model_id}.surfaces[{surface_index}].id")
            if surface_id in surfaces:
                raise ModelFloorError(f"duplicate surface id: {surface_id}")
            kind = surface.get("kind", "unknown")
            if kind not in SURFACE_KINDS:
                raise ModelFloorError(
                    f"{surface_id}.kind must be one of {sorted(SURFACE_KINDS)}"
                )
            status = surface.get("status", "unmeasured")
            if status not in SURFACE_STATUS:
                raise ModelFloorError(
                    f"{surface_id}.status must be one of {sorted(SURFACE_STATUS)}"
                )
            runtime_patterns = [
                need_text(pattern, f"{surface_id}.runtime_patterns[]", limit=500)
                for pattern in need_array(
                    surface.get("runtime_patterns", []), f"{surface_id}.runtime_patterns"
                )
            ]
            for pattern in runtime_patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ModelFloorError(
                        f"{surface_id}.runtime_patterns contains invalid regex {pattern!r}: {exc}"
                    ) from exc
            normalized_surface = {
                **surface,
                "id": surface_id,
                "kind": kind,
                "status": status,
                "runtime_patterns": runtime_patterns,
                "price": _price(surface.get("price"), f"{surface_id}.price"),
                "context_tokens": (
                    need_int(
                        surface.get("context_tokens"),
                        f"{surface_id}.context_tokens",
                        low=1,
                    )
                    if surface.get("context_tokens") is not None
                    else None
                ),
                "max_output_tokens": (
                    need_int(
                        surface.get("max_output_tokens"),
                        f"{surface_id}.max_output_tokens",
                        low=1,
                    )
                    if surface.get("max_output_tokens") is not None
                    else None
                ),
                "runtime_attestation_required": need_bool(
                    surface.get(
                        "runtime_attestation_required",
                        kind not in {"benchmark_report", "unknown"},
                    ),
                    f"{surface_id}.runtime_attestation_required",
                ),
            }
            surfaces[surface_id] = (model_id, normalized_surface)
            surface_rows.append(normalized_surface)
        normalized.append(
            {
                **row,
                "id": model_id,
                "provider": provider,
                "family": family,
                "access": access,
                "aliases": aliases,
                "official_ids": official_ids,
                "surfaces": surface_rows,
            }
        )
    models = unique_by_id(normalized, "model")
    registry = {
        **value,
        "id": registry_id,
        "models": normalized,
    }
    return RegistryIndex(registry=registry, models=models, aliases=alias_owner, surfaces=surfaces)


def resolve_identity(raw: Any, index: RegistryIndex) -> dict[str, Any]:
    value = need_object(raw, "observation.model")
    declared = need_text(value.get("declared_id"), "observation.model.declared_id", limit=300)
    runtime = optional_text(
        value.get("runtime_id"), "observation.model.runtime_id", limit=500
    )
    surface_id = optional_text(
        value.get("surface_id"), "observation.model.surface_id", limit=300
    )
    reasons: list[str] = []
    canonical = index.aliases.get(declared.casefold())
    if canonical is None:
        reasons.append("declared_model_unknown")
    surface: dict[str, Any] | None = None
    if surface_id:
        binding = index.surfaces.get(surface_id)
        if binding is None:
            reasons.append("surface_unknown")
        else:
            owner, surface = binding
            if canonical and owner != canonical:
                reasons.append("surface_model_mismatch")
            elif canonical is None:
                canonical = owner
    elif canonical:
        model = index.models[canonical]
        if len(model["surfaces"]) == 1:
            surface = model["surfaces"][0]
            surface_id = surface["id"]
        else:
            reasons.append("surface_missing")
    required = bool(surface and surface["runtime_attestation_required"])
    runtime_match = None
    if required and not runtime:
        reasons.append("runtime_model_missing")
    if runtime and canonical:
        model = index.models[canonical]
        candidates = [canonical, *model["aliases"], *model["official_ids"]]
        exact = runtime.casefold() in {item.casefold() for item in candidates}
        pattern_match = bool(
            surface
            and any(re.fullmatch(pattern, runtime) for pattern in surface["runtime_patterns"])
        )
        runtime_match = exact or pattern_match
        if not runtime_match:
            reasons.append("runtime_model_mismatch")
    if canonical is None:
        status = "unknown"
    elif reasons:
        conflict_reasons = {
            "surface_model_mismatch",
            "runtime_model_mismatch",
        }
        status = "conflicted" if conflict_reasons.intersection(reasons) else "unattested"
    else:
        status = "attested" if runtime or not required else "unattested"
    model = index.models.get(canonical) if canonical else None
    return {
        "declared_id": declared,
        "runtime_id": runtime,
        "surface_id": surface_id,
        "canonical_id": canonical,
        "provider": model["provider"] if model else value.get("provider"),
        "family": model["family"] if model else None,
        "revision": value.get("revision"),
        "effort": value.get("effort"),
        "quantization": value.get("quantization"),
        "hardware": value.get("hardware"),
        "identity_status": status,
        "runtime_match": runtime_match,
        "reasons": sorted(set(reasons)),
        "source_identity": {
            key: value.get(key)
            for key in (
                "declared_id",
                "runtime_id",
                "surface_id",
                "revision",
                "effort",
                "quantization",
                "hardware",
            )
            if value.get(key) is not None
        },
    }


def audit_identities(observations: list[dict[str, Any]], index: RegistryIndex) -> dict[str, Any]:
    rows = []
    counts: dict[str, int] = {}
    for observation in observations:
        model = observation.get("model")
        resolved = resolve_identity(model, index)
        status = resolved["identity_status"]
        counts[status] = counts.get(status, 0) + 1
        rows.append(
            {
                "observation_id": observation.get("id"),
                "source_id": (observation.get("source") or {}).get("id"),
                "benchmark_id": (observation.get("benchmark") or {}).get("id"),
                "identity": resolved,
            }
        )
    report = {
        "schema": IDENTITY_AUDIT_SCHEMA,
        "created_at": now_utc(),
        "registry_id": index.registry["id"],
        "registry_sha256": hash_json(index.registry),
        "counts": counts,
        "rows": rows,
    }
    report["report_sha256"] = hash_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def registry_from_models_json(
    raw: Any,
    *,
    registry_id: str = "tier-bench-models",
    overrides: Any | None = None,
) -> dict[str, Any]:
    source = need_object(raw, "models.json")
    models = need_object(source.get("models"), "models.json.models")
    rows = []
    for model_id in sorted(models):
        value = need_object(models[model_id], f"models.{model_id}")
        provider = str(value.get("provider") or "unknown")
        local = provider == "ollama"
        surface_kind = "local_runtime" if local else "api"
        price = {
            "input_per_million": float(value.get("input_per_1M", 0) or 0),
            "output_per_million": float(value.get("output_per_1M", 0) or 0),
            "basis": "models.json declared price",
            "currency": "USD",
        }
        rows.append(
            {
                "id": model_id,
                "provider": provider,
                "family": model_id,
                "access": "open_weight" if local else "closed",
                "aliases": [],
                "official_ids": [model_id],
                "metadata": {
                    "declared_tier_ceiling": value.get("tier_ceiling"),
                    "measured": value.get("measured"),
                    "source_measured_status": value.get("measured_status"),
                    "params_B": value.get("params_B"),
                },
                "surfaces": [
                    {
                        "id": f"{provider}:{model_id}",
                        "kind": surface_kind,
                        "status": "unmeasured",
                        "runtime_patterns": [re.escape(model_id)],
                        "runtime_attestation_required": True,
                        "context_tokens": value.get("context_tokens"),
                        "max_output_tokens": value.get("max_output_tokens"),
                        "price": price,
                    }
                ],
            }
        )
    registry = {
        "schema": REGISTRY_SCHEMA,
        "id": registry_id,
        "created_at": now_utc(),
        "source": "models.json",
        "models": rows,
    }
    if overrides is not None:
        overlay = need_object(overrides, "registry overrides")
        if overlay.get("schema") != "tier-bench/model-floor-registry-overrides@1":
            raise ModelFloorError(
                "registry overrides schema must be "
                "tier-bench/model-floor-registry-overrides@1"
            )
        by_id = {row["id"]: row for row in registry["models"]}
        for index, raw_override in enumerate(
            need_array(overlay.get("models", []), "registry overrides.models")
        ):
            override = need_object(raw_override, f"registry overrides.models[{index}]")
            model_id = safe_id(
                override.get("id"), f"registry overrides.models[{index}].id"
            )
            if model_id not in by_id:
                required = {"provider", "family", "access", "surfaces"}
                missing = required - set(override)
                if missing:
                    raise ModelFloorError(
                        f"new override model {model_id} is missing {sorted(missing)}"
                    )
                by_id[model_id] = {
                    "id": model_id,
                    "provider": override["provider"],
                    "family": override["family"],
                    "access": override["access"],
                    "aliases": list(override.get("aliases", [])),
                    "official_ids": list(override.get("official_ids", [])),
                    "surfaces": list(override["surfaces"]),
                    "metadata": override.get("metadata", {}),
                }
                continue
            target = by_id[model_id]
            for key in ("provider", "family", "access"):
                if key in override:
                    target[key] = override[key]
            for key in ("aliases", "official_ids"):
                if key in override:
                    target[key] = sorted(
                        set(target.get(key, [])) | set(override.get(key, []))
                    )
            if "surfaces" in override:
                surface_by_id = {
                    surface["id"]: surface for surface in target.get("surfaces", [])
                }
                for surface in override["surfaces"]:
                    surface = need_object(surface, f"{model_id}.override.surfaces")
                    surface_id = safe_id(surface.get("id"), f"{model_id}.override.surface.id")
                    if surface_id in surface_by_id:
                        surface_by_id[surface_id] = {
                            **surface_by_id[surface_id],
                            **surface,
                        }
                    else:
                        surface_by_id[surface_id] = surface
                target["surfaces"] = [
                    surface_by_id[key] for key in sorted(surface_by_id)
                ]
            if "metadata" in override:
                target["metadata"] = {
                    **target.get("metadata", {}),
                    **need_object(override["metadata"], f"{model_id}.override.metadata"),
                }
        registry["models"] = [by_id[key] for key in sorted(by_id)]
        registry["overrides_sha256"] = hash_json(overlay)
    validate_registry(registry)
    return registry
