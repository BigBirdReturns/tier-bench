"""Deterministic synthetic probe construction.

The public plan records only generator parameters and hashes. Prompt text is
materialized transiently for request construction and retained only inside the
private run artifact.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes, sha256_bytes, sha256_object
from .contracts import api_contract_hash, probe_contract_hash

GENERATOR_VERSION = "frontier-synthetic-v1"
_VOCAB = (
    "amber",
    "birch",
    "cobalt",
    "delta",
    "ember",
    "fjord",
    "granite",
    "harbor",
    "indigo",
    "juniper",
    "kepler",
    "lattice",
    "magnet",
    "nebula",
    "onyx",
    "prairie",
    "quartz",
    "radar",
    "saffron",
    "tundra",
    "umbra",
    "vector",
    "willow",
    "xenon",
    "yarrow",
    "zephyr",
)


@dataclass(frozen=True)
class PromptMaterial:
    system_text: str
    prefix_text: str
    suffix_text: str
    expected_anchor: str | None
    tools: list[dict[str, Any]]
    effort: str | None
    cache_key: str

    @property
    def public_descriptor(self) -> dict[str, Any]:
        return {
            "system_utf8_bytes": len(self.system_text.encode("utf-8")),
            "prefix_utf8_bytes": len(self.prefix_text.encode("utf-8")),
            "suffix_utf8_bytes": len(self.suffix_text.encode("utf-8")),
            "expected_anchor_sha256": (
                sha256_bytes(self.expected_anchor.encode("utf-8"))
                if self.expected_anchor is not None
                else None
            ),
            "tool_contract_sha256": sha256_object(self.tools),
            "effort": self.effort,
            "cache_key_sha256": sha256_bytes(self.cache_key.encode("utf-8")),
        }


def _words(units: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [f"{_VOCAB[rng.randrange(len(_VOCAB))]}{index:06d}" for index in range(units)]


def _render_words(units: int, seed: int, *, mutation_index: int | None = None) -> str:
    words = _words(units, seed)
    if mutation_index is not None and words:
        bounded = max(0, min(len(words) - 1, mutation_index))
        words[bounded] = f"mutation{seed:08x}_{bounded:06d}"
    return " ".join(words)


def _anchor(seed: int, block: int, position: float) -> str:
    digest = sha256_object({"seed": seed, "block": block, "position": position})
    return f"AXM_ANCHOR_{digest[:24].upper()}"


def _insert_anchor(text: str, anchor: str, position: float) -> str:
    words = text.split(" ") if text else []
    index = max(0, min(len(words), round(len(words) * position)))
    words.insert(index, anchor)
    return " ".join(words)


def _base_tools(description: str) -> list[dict[str, Any]]:
    return [
        {
            "name": "lookup_synthetic_record",
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": {"record_id": {"type": "string"}},
                "required": ["record_id"],
                "additionalProperties": False,
            },
        }
    ]


def _observation(
    *,
    campaign_id: str,
    probe: Mapping[str, Any],
    ordinal: int,
    block: int,
    condition: str,
    sequence_in_block: int,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    observation_id = f"{campaign_id}.{ordinal:04d}.{probe['id']}.{condition}"
    return {
        "observation_id": observation_id,
        "ordinal": ordinal,
        "probe_id": probe["id"],
        "probe_kind": probe["kind"],
        "probe_contract_sha256": probe_contract_hash(probe),
        "block": block,
        "condition": condition,
        "sequence_in_block": sequence_in_block,
        "generator_version": GENERATOR_VERSION,
        "parameters": dict(parameters),
    }


def build_schedule(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build a deterministic, interleaved observation schedule."""

    schedule: list[dict[str, Any]] = []
    ordinal = 1
    campaign_id = manifest["campaign_id"]

    for probe in manifest["probes"]:
        kind = probe["kind"]
        repeats = int(probe.get("repeats", 1))
        seed = int(probe.get("seed", 1))

        if kind == "cache_reuse":
            for block in range(repeats):
                base = {
                    "seed": seed,
                    "prefix_seed": seed * 100_003 + block,
                    "prefix_units": probe["prefix_units"],
                    "suffix_units": probe.get("suffix_units", 16),
                    "mutation_fraction": probe.get("mutation_fraction", 0.25),
                }
                order = ["prime", "warm", "mutated"] if block % 2 == 0 else ["prime", "mutated", "warm"]
                for sequence, condition in enumerate(order):
                    params = dict(base)
                    params["suffix_seed"] = seed * 1_000_003 + block * 10 + sequence
                    params["cache_namespace"] = f"{campaign_id}:{probe['id']}:{block}"
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=condition,
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "cache_threshold":
            thresholds = list(probe["threshold_units"])
            for block in range(repeats):
                ordered = thresholds if block % 2 == 0 else list(reversed(thresholds))
                for size_index, size in enumerate(ordered):
                    for sequence, condition in enumerate(("prime", "warm")):
                        params = {
                            "seed": seed,
                            "prefix_seed": seed * 100_003 + block * 10_000 + int(size),
                            "prefix_units": int(size),
                            "suffix_units": probe.get("suffix_units", 16),
                            "suffix_seed": seed * 1_000_003 + block * 1000 + size_index * 10 + sequence,
                            "threshold_units": int(size),
                            "cache_namespace": f"{campaign_id}:{probe['id']}:{block}:{size}",
                        }
                        schedule.append(
                            _observation(
                                campaign_id=campaign_id,
                                probe=probe,
                                ordinal=ordinal,
                                block=block,
                                condition=f"threshold-{size}-{condition}",
                                sequence_in_block=size_index * 2 + sequence,
                                parameters=params,
                            )
                        )
                        ordinal += 1
        elif kind == "prefix_boundary":
            fractions = list(probe["mutation_fractions"])
            for block in range(repeats):
                conditions: list[tuple[str, float | None]] = [("prime", None)]
                mutable = [(f"mutate-{fraction:.4f}", float(fraction)) for fraction in fractions]
                if block % 2:
                    mutable.reverse()
                conditions.extend(mutable)
                for sequence, (condition, fraction) in enumerate(conditions):
                    params = {
                        "seed": seed,
                        "prefix_seed": seed * 100_003 + block,
                        "prefix_units": probe["prefix_units"],
                        "suffix_units": probe.get("suffix_units", 16),
                        "suffix_seed": seed * 1_000_003 + block * 100 + sequence,
                        "mutation_fraction": fraction,
                        "cache_namespace": f"{campaign_id}:{probe['id']}:{block}",
                    }
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=condition,
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "context_sweep":
            sizes = list(probe["context_units"])
            for block in range(repeats):
                ordered = sizes if block % 2 == 0 else list(reversed(sizes))
                for sequence, size in enumerate(ordered):
                    params = {
                        "seed": seed,
                        "prefix_seed": seed * 100_003 + block * 100 + int(size),
                        "prefix_units": int(size),
                        "suffix_units": probe.get("suffix_units", 16),
                        "suffix_seed": seed * 1_000_003 + block * 100 + sequence,
                        "cache_namespace": f"{campaign_id}:{probe['id']}:{block}:{size}",
                    }
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=f"context-{size}",
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "retention":
            positions = list(probe["anchor_positions"])
            for block in range(repeats):
                ordered = positions if block % 2 == 0 else list(reversed(positions))
                for sequence, position in enumerate(ordered):
                    params = {
                        "seed": seed,
                        "prefix_seed": seed * 100_003 + block,
                        "prefix_units": probe["context_units"],
                        "suffix_units": probe.get("suffix_units", 24),
                        "suffix_seed": seed * 1_000_003 + block * 100 + sequence,
                        "anchor_position": float(position),
                        "cache_namespace": f"{campaign_id}:{probe['id']}:{block}:{position}",
                    }
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=f"anchor-{position:.4f}",
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "serialization":
            variants = list(probe.get("variants", ["canonical", "pretty", "reordered"]))
            for block in range(repeats):
                ordered = variants if block % 2 == 0 else list(reversed(variants))
                for sequence, variant in enumerate(ordered):
                    params = {
                        "seed": seed,
                        "prefix_seed": seed * 100_003 + block,
                        "prefix_units": probe["prefix_units"],
                        "suffix_units": probe.get("suffix_units", 16),
                        "suffix_seed": seed * 1_000_003 + block * 100 + sequence,
                        "serialization_variant": variant,
                        "cache_namespace": f"{campaign_id}:{probe['id']}:{block}",
                    }
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=str(variant),
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "tool_schema":
            variants = list(probe.get("variants", ["stable", "description_mutated"]))
            for block in range(repeats):
                ordered = variants if block % 2 == 0 else list(reversed(variants))
                for sequence, variant in enumerate(ordered):
                    params = {
                        "seed": seed,
                        "prefix_seed": seed * 100_003 + block,
                        "prefix_units": probe["prefix_units"],
                        "suffix_units": probe.get("suffix_units", 16),
                        "suffix_seed": seed * 1_000_003 + block * 100 + sequence,
                        "tool_variant": variant,
                        "cache_namespace": f"{campaign_id}:{probe['id']}:{block}",
                    }
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=str(variant),
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "effort":
            levels = list(probe["levels"])
            for block in range(repeats):
                ordered = levels if block % 2 == 0 else list(reversed(levels))
                for sequence, level in enumerate(ordered):
                    params = {
                        "seed": seed,
                        "prefix_seed": seed * 100_003 + block,
                        "prefix_units": probe.get("prefix_units", 128),
                        "suffix_units": probe.get("suffix_units", 16),
                        "suffix_seed": seed * 1_000_003 + block * 100 + sequence,
                        "effort": level,
                        "cache_namespace": f"{campaign_id}:{probe['id']}:{block}:{level}",
                    }
                    schedule.append(
                        _observation(
                            campaign_id=campaign_id,
                            probe=probe,
                            ordinal=ordinal,
                            block=block,
                            condition=str(level),
                            sequence_in_block=sequence,
                            parameters=params,
                        )
                    )
                    ordinal += 1
        elif kind == "identity":
            for block in range(repeats):
                params = {
                    "seed": seed,
                    "prefix_seed": seed * 100_003 + block,
                    "prefix_units": probe.get("prefix_units", 64),
                    "suffix_units": probe.get("suffix_units", 8),
                    "suffix_seed": seed * 1_000_003 + block,
                    "cache_namespace": f"{campaign_id}:{probe['id']}:{block}",
                }
                schedule.append(
                    _observation(
                        campaign_id=campaign_id,
                        probe=probe,
                        ordinal=ordinal,
                        block=block,
                        condition="identity-sample",
                        sequence_in_block=0,
                        parameters=params,
                    )
                )
                ordinal += 1
        else:  # validated earlier; retained as a defensive stop.
            raise ValueError(f"unsupported probe kind: {kind}")

    return schedule


def materialize_prompt(spec: Mapping[str, Any]) -> PromptMaterial:
    parameters = spec["parameters"]
    kind = spec["probe_kind"]
    prefix_units = int(parameters.get("prefix_units", 64))
    prefix_seed = int(parameters["prefix_seed"])
    mutation_index: int | None = None
    fraction = parameters.get("mutation_fraction")
    if spec["condition"] == "mutated" or spec["condition"].startswith("mutate-"):
        if fraction is None:
            fraction = 0.25
        mutation_index = int(prefix_units * float(fraction))

    prefix = _render_words(prefix_units, prefix_seed, mutation_index=mutation_index)
    expected_anchor: str | None = None
    if kind == "retention":
        position = float(parameters["anchor_position"])
        expected_anchor = _anchor(int(parameters["seed"]), int(spec["block"]), position)
        prefix = _insert_anchor(prefix, expected_anchor, position)

    suffix_units = int(parameters.get("suffix_units", 16))
    suffix = _render_words(suffix_units, int(parameters["suffix_seed"]))
    if kind == "retention":
        suffix = (
            suffix
            + "\nReturn one JSON object with exactly one key named anchor and the exact "
            "AXM_ANCHOR value found in the preceding material."
        )
    elif kind == "identity":
        suffix += "\nReply with the single word READY."
    else:
        suffix += "\nReply with the single word ACK."

    if kind == "serialization":
        semantic = {"alpha": 1, "beta": [2, 3], "gamma": {"delta": True}}
        variant = parameters.get("serialization_variant")
        if variant == "pretty":
            suffix += "\n" + json.dumps(semantic, indent=2, sort_keys=True)
        elif variant == "reordered":
            suffix += "\n" + json.dumps(
                {"gamma": semantic["gamma"], "beta": semantic["beta"], "alpha": 1},
                separators=(", ", ": "),
            )
        else:
            suffix += "\n" + canonical_json_bytes(semantic).decode("utf-8")

    tools: list[dict[str, Any]] = []
    if kind == "tool_schema":
        variant = parameters.get("tool_variant")
        description = "Look up a synthetic record by its opaque identifier."
        if variant == "description_mutated":
            description = "Retrieve one synthetic record using an opaque record identifier."
        tools = _base_tools(description)

    system_text = (
        "This is a deterministic synthetic measurement request. Do not infer personal "
        "information. Follow the requested output form exactly."
    )
    return PromptMaterial(
        system_text=system_text,
        prefix_text=prefix,
        suffix_text=suffix,
        expected_anchor=expected_anchor,
        tools=tools,
        effort=parameters.get("effort"),
        cache_key=str(parameters["cache_namespace"]),
    )


def public_plan(manifest: Mapping[str, Any], model_display: str) -> dict[str, Any]:
    schedule = build_schedule(manifest)
    cells: list[dict[str, Any]] = []
    for spec in schedule:
        material = materialize_prompt(spec)
        cells.append(
            {
                **spec,
                "requested_model": model_display,
                "api_contract_sha256": api_contract_hash(manifest),
                "prompt_descriptor": material.public_descriptor,
            }
        )
    return {
        "schema": "tier-bench/frontier-fingerprint-plan@1",
        "campaign_id": manifest["campaign_id"],
        "manifest_sha256": sha256_object(manifest),
        "api_contract_sha256": api_contract_hash(manifest),
        "model_binding": model_display,
        "generator_version": GENERATOR_VERSION,
        "request_count": len(cells),
        "latency_design": {
            "cache_reuse": "within-block prime followed by alternating warm/mutated order",
            "latency_role": "corroborating_only",
            "primary_cache_signal": "provider_reported_usage_counters",
        },
        "cells": cells,
    }


def schedule_by_probe(schedule: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for spec in schedule:
        grouped.setdefault(str(spec["probe_id"]), []).append(spec)
    return grouped
