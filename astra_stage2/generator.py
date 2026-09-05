"""Deterministic fixed-envelope generators and calibration-plan compiler."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

from .canonical import Stage2Error, canonical_json_bytes, sha256_object

SCHEMA_GENERATOR_MANIFEST = "tier-bench/astra-stage2-generator-manifest@2"
SCHEMA_PLAN = "tier-bench/astra-stage2-calibration-plan@2"
SCHEMA_TASK = "tier-bench/astra-stage2-task@2"
SCHEMA_OBSERVATION = "tier-bench/astra-stage2-observation@2"

FAMILIES = ("pointer_chase", "coupled_ring", "branch_reconcile")
K_LEVELS = (1, 8, 32)
R_LEVELS = (1, 4, 16)
REPLICATES = tuple(range(4))
EFFORTS = ("low", "high")
CONTROL_ROLES = (
    "lotus_3b_recurrent",
    "loopcoder_v2_7b_parallel",
    "conventional_transformer_negative",
)
LANE_COUNT = 32
TABLE_SIZE = 16
EXPECTED_CASE_COUNT = len(FAMILIES) * len(K_LEVELS) * len(R_LEVELS) * len(REPLICATES)
EXPECTED_OBSERVATION_COUNT = EXPECTED_CASE_COUNT * len(CONTROL_ROLES) * len(EFFORTS)
GENERATOR_SEED_VERSION = "astra-stage2-generator-v1"
GENERATOR_VERSION = "astra-stage2-generator-v2"
CHECKSUM_HEX_LENGTH = 16


def _digest(seed: str, label: str) -> bytes:
    return hashlib.sha256(f"{GENERATOR_SEED_VERSION}|{seed}|{label}".encode("utf-8")).digest()


def _uint(seed: str, label: str, modulus: int) -> int:
    if modulus <= 0:
        raise Stage2Error("modulus must be positive")
    return int.from_bytes(_digest(seed, label)[:8], "big") % modulus


def _permutation(seed: str, label: str, size: int) -> list[int]:
    return sorted(range(size), key=lambda value: _digest(seed, f"{label}:{value}"))


def _active_indices(seed: str, k: int) -> list[int]:
    if k not in K_LEVELS:
        raise Stage2Error(f"unsupported K level: {k}")
    order = _permutation(seed, "active-order", LANE_COUNT)
    return sorted(order[:k])


def _lane(seed: str, lane_index: int) -> dict[str, Any]:
    return {
        "index": lane_index,
        "start": _uint(seed, f"lane:{lane_index}:start", TABLE_SIZE),
        "transition": _permutation(seed, f"lane:{lane_index}:transition", TABLE_SIZE),
        "salt": _uint(seed, f"lane:{lane_index}:salt", 2**31 - 1),
    }


def _evaluate_pointer(task: dict[str, Any]) -> dict[str, Any]:
    active = set(task["active_lanes"])
    finals: list[dict[str, int]] = []
    for lane in task["lanes"]:
        if lane["index"] not in active:
            continue
        state = lane["start"]
        for _ in range(task["r"]):
            state = lane["transition"][state]
        finals.append({"lane": lane["index"], "state": state})
    return {"family": task["family"], "finals": finals}


def _evaluate_ring(task: dict[str, Any]) -> dict[str, Any]:
    active_indices = task["active_lanes"]
    lane_by_index = {lane["index"]: lane for lane in task["lanes"]}
    states = {index: lane_by_index[index]["start"] for index in active_indices}
    for round_index in range(task["r"]):
        previous = dict(states)
        updated: dict[int, int] = {}
        for position, lane_index in enumerate(active_indices):
            neighbor_index = active_indices[(position - 1) % len(active_indices)]
            lane = lane_by_index[lane_index]
            selector = (
                previous[lane_index]
                + previous[neighbor_index]
                + round_index
                + lane["salt"]
            ) % TABLE_SIZE
            updated[lane_index] = lane["transition"][selector]
        states = updated
    return {
        "family": task["family"],
        "finals": [{"lane": index, "state": states[index]} for index in active_indices],
    }


def _evaluate_branch(task: dict[str, Any]) -> dict[str, Any]:
    active_indices = task["active_lanes"]
    lane_by_index = {lane["index"]: lane for lane in task["lanes"]}
    states = {index: lane_by_index[index]["start"] for index in active_indices}
    nonce_int = int(task["nonce"], 16)
    for round_index in range(task["r"]):
        updated: dict[int, int] = {}
        parity = sum(states.values()) % TABLE_SIZE
        for position, lane_index in enumerate(active_indices):
            lane = lane_by_index[lane_index]
            branch = (nonce_int >> ((round_index + position) % 32)) & 1
            selector = (
                states[lane_index]
                + parity
                + branch * (position + 1)
                + lane["salt"]
            ) % TABLE_SIZE
            updated[lane_index] = lane["transition"][selector]
        states = updated
    witness_position = (sum(states.values()) + nonce_int) % len(active_indices)
    witness_lane = active_indices[witness_position]
    return {
        "family": task["family"],
        "witness_lane": witness_lane,
        "witness_state": states[witness_lane],
        "finals": [{"lane": index, "state": states[index]} for index in active_indices],
    }


def _evaluate_task_result(task: dict[str, Any]) -> dict[str, Any]:
    family = task.get("family")
    if family == "pointer_chase":
        return _evaluate_pointer(task)
    if family == "coupled_ring":
        return _evaluate_ring(task)
    if family == "branch_reconcile":
        return _evaluate_branch(task)
    raise Stage2Error(f"unsupported task family: {family!r}")


def _checksum_result(result: dict[str, Any]) -> str:
    """Return the frozen model-computable 16-nibble checksum."""
    buckets = [0] * CHECKSUM_HEX_LENGTH
    for item in result["finals"]:
        lane = int(item["lane"])
        state = int(item["state"])
        bucket = lane % CHECKSUM_HEX_LENGTH
        buckets[bucket] = (buckets[bucket] + state + 7 * (lane // 16) + 1) % 16
    if result["family"] == "branch_reconcile":
        buckets[14] = (buckets[14] + int(result["witness_lane"])) % 16
        buckets[15] = (buckets[15] + int(result["witness_state"]) + 1) % 16
    return "".join(format(value, "x") for value in buckets)


def evaluate_task(task: dict[str, Any]) -> str:
    return _checksum_result(_evaluate_task_result(task))


_PROMPT_HEADER = (
    "ASTRA-STAGE2-REQUEST-V2\n"
    "Return exactly 16 lowercase hexadecimal characters and nothing else.\n"
    "All state arithmetic is modulo 16. Use only lanes whose A field is 1.\n"
    "F=P: repeat R times independently per active lane: state=T[state].\n"
    "F=C: each round uses previous states; predecessor is previous active lane cyclically; "
    "selector=(self+pred+round+salt) mod 16; state=T[selector].\n"
    "F=B: each round parity=sum(active states) mod16; for active position p from 0 upward, "
    "branch=(nonce >> ((round+p) mod32))&1; selector=(state+parity+branch*(p+1)+salt) mod16; "
    "state=T[selector]. After R rounds witness position=(sum(states)+nonce) mod K.\n"
    "Checksum: start 16 zero nibbles. For each active lane i final state s, bucket i mod16 "
    "becomes (bucket+s+7*floor(i/16)+1) mod16. For F=B also add witness lane to bucket14 "
    "and witness state+1 to bucket15, modulo16. Emit buckets 0..15.\n"
    "Fields are fixed-width hex except CASE and MASK. T is 16 two-hex transition states.\n"
)


def render_task_prompt(task: dict[str, Any]) -> bytes:
    family_codes = {
        "pointer_chase": "P",
        "coupled_ring": "C",
        "branch_reconcile": "B",
    }
    family = task.get("family")
    if family not in family_codes:
        raise Stage2Error(f"unsupported task family: {family!r}")
    active = set(task["active_lanes"])
    mask = "".join("1" if index in active else "0" for index in range(LANE_COUNT))
    lines = [
        _PROMPT_HEADER.rstrip("\n"),
        (
            f"CASE={task['case_id']};F={family_codes[family]};K={int(task['k']):02x};"
            f"R={int(task['r']):02x};REP={int(task['replicate']):x};"
            f"NONCE={task['nonce']};MASK={mask}"
        ),
    ]
    for lane in task["lanes"]:
        index = int(lane["index"])
        transition = "".join(f"{int(value):02x}" for value in lane["transition"])
        lines.append(
            f"L={index:02x};A={1 if index in active else 0};S={int(lane['start']):02x};"
            f"Z={int(lane['salt']):08x};T={transition}"
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def build_task(*, family: str, k: int, r: int, replicate: int) -> dict[str, Any]:
    if family not in FAMILIES:
        raise Stage2Error(f"unsupported family: {family}")
    if k not in K_LEVELS or r not in R_LEVELS or replicate not in REPLICATES:
        raise Stage2Error("case coordinate is outside the frozen lattice")
    coordinate = {
        "family": family,
        "k": k,
        "r": r,
        "replicate": replicate,
        "generator_version": GENERATOR_SEED_VERSION,
    }
    seed = sha256_object(coordinate)
    task: dict[str, Any] = {
        "schema": SCHEMA_TASK,
        "generator_version": GENERATOR_VERSION,
        "family": family,
        "k": k,
        "r": r,
        "replicate": replicate,
        "lane_count": LANE_COUNT,
        "table_size": TABLE_SIZE,
        "active_lanes": _active_indices(seed, k),
        "lanes": [_lane(seed, index) for index in range(LANE_COUNT)],
        "nonce": _digest(seed, "nonce")[:8].hex(),
    }
    task["case_id"] = "s2case_" + sha256_object(
        {key: task[key] for key in ("generator_version", "family", "k", "r", "replicate")}
    )[:24]
    task["expected_checksum"] = evaluate_task(task)
    return task


def iter_tasks() -> Iterable[dict[str, Any]]:
    for family in FAMILIES:
        for k in K_LEVELS:
            for r in R_LEVELS:
                for replicate in REPLICATES:
                    yield build_task(family=family, k=k, r=r, replicate=replicate)


def reconstruct_task(summary: dict[str, Any]) -> dict[str, Any]:
    task = build_task(
        family=summary["family"],
        k=int(summary["k"]),
        r=int(summary["r"]),
        replicate=int(summary["replicate"]),
    )
    request = render_task_prompt(task)
    expected = {
        "case_id": task["case_id"],
        "task_sha256": sha256_object(task),
        "expected_checksum": task["expected_checksum"],
        "request_sha256": hashlib.sha256(request).hexdigest(),
        "request_bytes": len(request),
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise Stage2Error(f"generator reconstruction mismatch for {key}")
    return task


def build_generator_manifest() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for task in iter_tasks():
        cases.append(
            {
                "case_id": task["case_id"],
                "family": task["family"],
                "k": task["k"],
                "r": task["r"],
                "replicate": task["replicate"],
                "task_sha256": sha256_object(task),
                "task_bytes": len(canonical_json_bytes(task)),
                "expected_checksum": task["expected_checksum"],
                "request_sha256": hashlib.sha256(render_task_prompt(task)).hexdigest(),
                "request_bytes": len(render_task_prompt(task)),
            }
        )
    manifest: dict[str, Any] = {
        "schema": SCHEMA_GENERATOR_MANIFEST,
        "generator_version": GENERATOR_VERSION,
        "families": list(FAMILIES),
        "k_levels": list(K_LEVELS),
        "r_levels": list(R_LEVELS),
        "replicates": list(REPLICATES),
        "lane_count": LANE_COUNT,
        "table_size": TABLE_SIZE,
        "case_count": len(cases),
        "cases": cases,
    }
    manifest["payload_sha256"] = sha256_object(manifest)
    return manifest


def fixture_control_manifest() -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    for role in CONTROL_ROLES:
        identity = {
            "evidence_class": "fixture_synthetic",
            "role": role,
            "source_repository": f"fixture://{role}",
            "source_commit_sha1": hashlib.sha1(role.encode()).hexdigest(),  # fixture only
            "model_revision_sha256": hashlib.sha256(f"model:{role}".encode()).hexdigest(),
            "weights_sha256": hashlib.sha256(f"weights:{role}".encode()).hexdigest(),
            "tokenizer_sha256": hashlib.sha256(f"tokenizer:{role}".encode()).hexdigest(),
            "runtime_sha256": hashlib.sha256(f"runtime:{role}".encode()).hexdigest(),
            "adapter_sha256": hashlib.sha256(f"adapter:{role}".encode()).hexdigest(),
            "hardware_sha256": hashlib.sha256(f"hardware:{role}".encode()).hexdigest(),
        }
        controls.append(
            {
                "control_id": role,
                "class_label": (
                    "recurrent_latent"
                    if role.startswith("lotus")
                    else "parallel_latent"
                    if role.startswith("loopcoder")
                    else "conventional_negative"
                ),
                "identity": identity,
                "identity_sha256": sha256_object(identity),
            }
        )
    manifest: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-control-manifest@1",
        "evidence_class": "fixture_synthetic",
        "stage1_join_head": "60bca963d63edca267106bc5c7725c2cc1df8dd7",
        "controls": controls,
    }
    manifest["payload_sha256"] = sha256_object(manifest)
    return manifest


def empirical_control_template() -> dict[str, Any]:
    controls = []
    public_sources = {
        "lotus_3b_recurrent": {
            "source_repository": "yingfan-bot/lotus",
            "source_commit_sha1": "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
        },
        "loopcoder_v2_7b_parallel": {
            "source_repository": "CSJianYang/LoopCoder",
            "source_commit_sha1": "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c",
        },
        "conventional_transformer_negative": {
            "source_repository": "yingfan-bot/lotus",
            "source_commit_sha1": "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
        },
    }
    for role in CONTROL_ROLES:
        controls.append(
            {
                "control_id": role,
                "class_label": (
                    "recurrent_latent"
                    if role.startswith("lotus")
                    else "parallel_latent"
                    if role.startswith("loopcoder")
                    else "conventional_negative"
                ),
                "identity": {
                    "evidence_class": "empirical_local",
                    "role": role,
                    **public_sources[role],
                    "model_revision_sha256": None,
                    "weights_sha256": None,
                    "tokenizer_sha256": None,
                    "runtime_sha256": None,
                    "adapter_sha256": None,
                    "hardware_sha256": None,
                },
                "identity_sha256": None,
            }
        )
    return {
        "schema": "tier-bench/astra-stage2-control-manifest@1",
        "evidence_class": "empirical_local",
        "stage1_join_head": "60bca963d63edca267106bc5c7725c2cc1df8dd7",
        "controls": controls,
        "payload_sha256": None,
        "status": "UNBOUND_TEMPLATE",
    }


def build_calibration_plan(
    generator_manifest: dict[str, Any], control_manifest: dict[str, Any]
) -> dict[str, Any]:
    cases = generator_manifest.get("cases", [])
    controls = control_manifest.get("controls", [])
    rows: list[dict[str, Any]] = []
    for case in cases:
        reconstruct_task(case)
        for control in controls:
            for effort in EFFORTS:
                coordinate = {
                    "case_id": case["case_id"],
                    "control_id": control["control_id"],
                    "effort": effort,
                    "generator_manifest_sha256": generator_manifest["payload_sha256"],
                    "control_manifest_sha256": control_manifest["payload_sha256"],
                }
                block_coordinate = {
                    "family": case["family"], "replicate": case["replicate"],
                    "control_id": control["control_id"], "effort": effort,
                    "generator_manifest_sha256": generator_manifest["payload_sha256"],
                    "control_manifest_sha256": control_manifest["payload_sha256"],
                }
                block_id = "s2block_" + sha256_object(block_coordinate)[:16]
                rows.append(
                    {
                        "observation_id": "s2obs_" + sha256_object(coordinate)[:24],
                        "case_id": case["case_id"],
                        "family": case["family"],
                        "k": case["k"],
                        "r": case["r"],
                        "replicate": case["replicate"],
                        "task_sha256": case["task_sha256"],
                        "expected_checksum": case["expected_checksum"],
                        "request_sha256": case["request_sha256"],
                        "request_bytes": case["request_bytes"],
                        "control_id": control["control_id"],
                        "control_class": control["class_label"],
                        "control_identity_sha256": control["identity_sha256"],
                        "effort": effort,
                        "block_id": block_id,
                        "order_index": -1,
                    }
                )
    by_block: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_block.setdefault(row["block_id"], []).append(row)
    for block_id, block_rows in by_block.items():
        ordered = sorted(
            block_rows,
            key=lambda row: sha256_object({"block_id": block_id, "case_id": row["case_id"]}),
        )
        for index, row in enumerate(ordered):
            row["order_index"] = index
    plan: dict[str, Any] = {
        "schema": SCHEMA_PLAN,
        "stage1_join_head": control_manifest["stage1_join_head"],
        "generator_manifest_sha256": generator_manifest["payload_sha256"],
        "control_manifest_sha256": control_manifest["payload_sha256"],
        "case_count": len(cases),
        "control_count": len(controls),
        "effort_count": len(EFFORTS),
        "observation_count": len(rows),
        "observations": rows,
    }
    plan["payload_sha256"] = sha256_object(plan)
    return plan


def build_plan_index(plan: dict[str, Any]) -> dict[str, Any]:
    index: dict[str, Any] = {
        "schema": "tier-bench/astra-stage2-calibration-plan-index@1",
        "stage1_join_head": plan["stage1_join_head"],
        "generator_manifest_sha256": plan["generator_manifest_sha256"],
        "control_manifest_sha256": plan["control_manifest_sha256"],
        "case_count": plan["case_count"],
        "control_count": plan["control_count"],
        "effort_count": plan["effort_count"],
        "observation_count": plan["observation_count"],
        "observations_sha256": sha256_object(plan["observations"]),
        "calibration_plan_payload_sha256": plan["payload_sha256"],
    }
    index["payload_sha256"] = sha256_object(index)
    return index


def _jitter(observation_id: str, scale: float = 0.015) -> float:
    raw = int.from_bytes(hashlib.sha256(observation_id.encode()).digest()[:4], "big")
    unit = raw / (2**32 - 1)
    return (unit * 2.0 - 1.0) * scale


def _fixture_latency(role: str, k: int, r: int, effort: str, observation_id: str) -> tuple[float, float]:
    lk = math.log2(k)
    lr = math.log2(r)
    effort_factor = 1.0 if effort == "low" else 1.16
    if role == "lotus_3b_recurrent":
        latency = 900.0 * (1.0 + 0.025 * lk + 0.20 * lr)
        ttft = 220.0 * (1.0 + 0.018 * lk + 0.10 * lr)
    elif role == "loopcoder_v2_7b_parallel":
        k_effect = {1: 0.0, 8: 0.015, 32: 0.28}[k]
        r_effect = {1: 0.0, 4: 0.31, 16: 0.18}[r]
        latency = 850.0 * (1.0 + k_effect + r_effect)
        ttft = 205.0 * (1.0 + k_effect * 0.5 + r_effect * 0.3)
    elif role == "conventional_transformer_negative":
        latency = 820.0 * (1.0 + 0.007 * lk + 0.006 * lr)
        ttft = 195.0 * (1.0 + 0.004 * lk + 0.003 * lr)
    else:
        raise Stage2Error(f"unknown fixture control: {role}")
    noise = 1.0 + _jitter(observation_id)
    return latency * effort_factor * noise, ttft * (1.0 if effort == "low" else 1.22) * noise


def build_fixture_observations(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in plan["observations"]:
        latency, ttft = _fixture_latency(
            item["control_id"], item["k"], item["r"], item["effort"], item["observation_id"]
        )
        reasoning_tokens = 64 if item["effort"] == "low" else 128
        seed = int(item["observation_id"].split("_", 1)[1][:12], 16)
        request_start_ns = seed * 1_000
        first_header_ns = request_start_ns + 500_000
        first_event_ns = first_header_ns + 250_000
        first_visible_ns = request_start_ns + int(ttft * 1_000_000)
        final_token_ns = request_start_ns + int(latency * 1_000_000)
        raw_evidence = {
            "request_start_ns": request_start_ns,
            "first_response_header_ns": first_header_ns,
            "first_event_ns": first_event_ns,
            "first_visible_token_ns": first_visible_ns,
            "final_token_ns": final_token_ns,
        }
        body: dict[str, Any] = {
            "schema": SCHEMA_OBSERVATION,
            "observation_id": item["observation_id"],
            "evidence_class": "fixture_synthetic",
            "case_id": item["case_id"],
            "family": item["family"],
            "k": item["k"],
            "r": item["r"],
            "replicate": item["replicate"],
            "task_sha256": item["task_sha256"],
            "expected_checksum": item["expected_checksum"],
            "request_sha256": item["request_sha256"],
            "request_bytes": item["request_bytes"],
            "block_id": item["block_id"],
            "order_index": item["order_index"],
            "control_id": item["control_id"],
            "control_class": item["control_class"],
            "control_identity_sha256": item["control_identity_sha256"],
            "effort": item["effort"],
            "route_identity_sha256": hashlib.sha256(
                f"fixture-route:{item['control_id']}".encode()
            ).hexdigest(),
            "api_contract_sha256": hashlib.sha256(b"fixture-local-contract-v2").hexdigest(),
            "raw_evidence_sha256": sha256_object(raw_evidence),
            "selected_headers_sha256": hashlib.sha256(b"fixture-no-headers").hexdigest(),
            "inter_event_times_sha256": sha256_object([first_event_ns, first_visible_ns, final_token_ns]),
            "request_id_sha256": hashlib.sha256(item["observation_id"].encode()).hexdigest(),
            "response_model_sha256": hashlib.sha256(
                f"fixture-model:{item['control_id']}".encode()
            ).hexdigest(),
            "backend_fingerprint_sha256": hashlib.sha256(
                f"fixture-backend:{item['control_id']}:{item['effort']}".encode()
            ).hexdigest(),
            "stop_state": "completed",
            "request_start_ns": request_start_ns,
            "first_response_header_ns": first_header_ns,
            "first_event_ns": first_event_ns,
            "first_visible_token_ns": first_visible_ns,
            "final_token_ns": final_token_ns,
            "input_tokens": 4096,
            "cached_input_tokens": 0,
            "output_tokens": 12,
            "reasoning_tokens": reasoning_tokens,
            "ttft_ms": round(ttft, 6),
            "latency_ms": round(latency, 6),
            "observed_checksum": item["expected_checksum"],
            "accepted": True,
            "provider_error": False,
        }
        body["record_sha256"] = sha256_object(body)
        rows.append(body)
    return rows
