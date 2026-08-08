"""Content-addressed desktop-to-<dual-3090-node> work exchange for Conditional Memory Lab.

The desktop owns orchestration, mutable state, collection, and final acceptance. The
<dual-3090-node> owns two independent RTX 3090 execution seats. Hosts may mount the same SMB
or Tailscale share at different local paths, so packets bind only relative paths and
content hashes. No tensor, KV-cache, or model-parallel traffic crosses the network.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Iterator

from .conditional_memory_common import (
    MemoryLabError,
    canonical,
    hash_file,
    hash_json,
    load_json,
    now_utc,
    safe_id,
    without_hash,
)
from .conditional_memory_hardware import query_nvidia, resolve_seat_environment
from .conditional_memory_plan import compile_plan, trial_by_id, verify_plan
from .conditional_memory_report import build_report, validate_receipt

CLUSTER_SCHEMA = "tier-bench/conditional-memory-cluster@1"
FLIGHT_SCHEMA = "tier-bench/conditional-memory-flight@1"
PACKET_SCHEMA = "tier-bench/conditional-memory-work-packet@1"
CLAIM_SCHEMA = "tier-bench/conditional-memory-claim@1"
SUBMISSION_SCHEMA = "tier-bench/conditional-memory-submission@1"
CROSS_VERIFY_SCHEMA = "tier-bench/conditional-memory-cross-verification@1"
COLLECTION_SCHEMA = "tier-bench/conditional-memory-collection@1"
STATUS_SCHEMA = "tier-bench/conditional-memory-exchange-status@1"

_SOURCE_FILES = (
    "conditional_memory_common.py",
    "conditional_memory_schema.py",
    "conditional_memory_plan.py",
    "conditional_memory_hardware.py",
    "conditional_memory_models.py",
    "conditional_memory_pack.py",
    "conditional_memory_runner.py",
    "conditional_memory_report.py",
    "conditional_memory_exchange.py",
    "conditional_memory_exchange_cli.py",
)


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {name: hash_file(root / name) for name in _SOURCE_FILES if (root / name).exists()}


def _need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MemoryLabError(f"{label} must be an object")
    return value


def _need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise MemoryLabError(f"{label} must be an array{suffix}")
    return value


def _need_text(value: Any, label: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MemoryLabError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def _need_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise MemoryLabError(f"{label} must be boolean")
    return value


def _need_number(value: Any, label: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryLabError(f"{label} must be numeric")
    result = float(value)
    if not low <= result <= high:
        raise MemoryLabError(f"{label} must be between {low} and {high}")
    return result


def _node(raw: Any, label: str, role: str) -> dict[str, Any]:
    row = _need_object(raw, label)
    node_id = safe_id(row.get("id"), f"{label}.id")
    hostname_env = row.get("hostname_env")
    if hostname_env is not None:
        hostname_env = _need_text(hostname_env, f"{label}.hostname_env", limit=120)
    expected_hostname = row.get("expected_hostname")
    if expected_hostname is not None:
        expected_hostname = _need_text(
            expected_hostname, f"{label}.expected_hostname", limit=200
        )
    return {
        "id": node_id,
        "role": role,
        "hostname_env": hostname_env,
        "expected_hostname": expected_hostname,
        "require_hostname": _need_bool(
            row.get("require_hostname", False), f"{label}.require_hostname"
        ),
    }


def _seat(raw: Any, index: int) -> dict[str, Any]:
    label = f"cluster.worker.seats[{index}]"
    row = _need_object(raw, label)
    kind = _need_text(row.get("kind", "cuda"), f"{label}.kind", limit=20)
    if kind not in {"cuda", "cpu"}:
        raise MemoryLabError(f"{label}.kind must be cuda or cpu")
    uuid_env = row.get("uuid_env")
    if uuid_env is not None:
        uuid_env = _need_text(uuid_env, f"{label}.uuid_env", limit=120)
    gpu_uuid = row.get("gpu_uuid")
    if gpu_uuid is not None:
        gpu_uuid = _need_text(gpu_uuid, f"{label}.gpu_uuid", limit=160)
    if kind == "cuda" and not uuid_env and not gpu_uuid:
        raise MemoryLabError(f"{label} requires uuid_env or gpu_uuid")
    return {
        "id": safe_id(row.get("id"), f"{label}.id"),
        "kind": kind,
        "uuid_env": uuid_env,
        "gpu_uuid": gpu_uuid,
        "expected_name_contains": (
            _need_text(
                row.get("expected_name_contains"),
                f"{label}.expected_name_contains",
                limit=160,
            )
            if row.get("expected_name_contains") is not None
            else None
        ),
        "require_identity": _need_bool(
            row.get("require_identity", kind == "cuda"), f"{label}.require_identity"
        ),
    }


def validate_cluster(raw: Any) -> dict[str, Any]:
    cluster = _need_object(raw, "cluster")
    if cluster.get("schema") != CLUSTER_SCHEMA:
        raise MemoryLabError(f"cluster.schema must be {CLUSTER_SCHEMA}")
    coordinator_raw = _need_object(cluster.get("coordinator"), "cluster.coordinator")
    coordinator = _node(coordinator_raw, "cluster.coordinator", "coordinator")
    coordinator.update(
        {
            "service_gpu_uuid_env": _need_text(
                coordinator_raw.get("service_gpu_uuid_env"),
                "cluster.coordinator.service_gpu_uuid_env",
                limit=120,
            ),
            "service_gpu_expected_name_contains": _need_text(
                coordinator_raw.get("service_gpu_expected_name_contains", "4060"),
                "cluster.coordinator.service_gpu_expected_name_contains",
                limit=160,
            ),
        }
    )
    worker_raw = _need_object(cluster.get("worker"), "cluster.worker")
    worker = _node(worker_raw, "cluster.worker", "worker")
    seats = [
        _seat(value, index)
        for index, value in enumerate(
            _need_array(worker_raw.get("seats"), "cluster.worker.seats", nonempty=True)
        )
    ]
    seat_ids = [seat["id"] for seat in seats]
    if len(seat_ids) != len(set(seat_ids)):
        raise MemoryLabError("cluster.worker.seats ids must be unique")
    worker["seats"] = seats
    exchange_raw = _need_object(cluster.get("exchange"), "cluster.exchange")
    kind = _need_text(
        exchange_raw.get("kind", "shared_filesystem"), "cluster.exchange.kind", limit=40
    )
    if kind != "shared_filesystem":
        raise MemoryLabError("cluster.exchange.kind must be shared_filesystem in version 1")
    exchange = {
        "kind": kind,
        "root_env": _need_text(
            exchange_raw.get("root_env", "TIER_EXCHANGE_ROOT"),
            "cluster.exchange.root_env",
            limit=120,
        ),
        "poll_seconds": _need_number(
            exchange_raw.get("poll_seconds", 2.0),
            "cluster.exchange.poll_seconds",
            low=0.1,
            high=3600.0,
        ),
        "heartbeat_seconds": _need_number(
            exchange_raw.get("heartbeat_seconds", 5.0),
            "cluster.exchange.heartbeat_seconds",
            low=0.25,
            high=3600.0,
        ),
        "lease_seconds": _need_number(
            exchange_raw.get("lease_seconds", 21600.0),
            "cluster.exchange.lease_seconds",
            low=1.0,
            high=30 * 86400.0,
        ),
        "copy_checkpoints": _need_bool(
            exchange_raw.get("copy_checkpoints", True),
            "cluster.exchange.copy_checkpoints",
        ),
        "cross_verify": _need_bool(
            exchange_raw.get("cross_verify", True), "cluster.exchange.cross_verify"
        ),
        "verification_loss_tolerance": _need_number(
            exchange_raw.get("verification_loss_tolerance", 0.005),
            "cluster.exchange.verification_loss_tolerance",
            low=0.0,
            high=1.0,
        ),
        "require_top_token_match": _need_bool(
            exchange_raw.get("require_top_token_match", True),
            "cluster.exchange.require_top_token_match",
        ),
    }
    if exchange["heartbeat_seconds"] >= exchange["lease_seconds"]:
        raise MemoryLabError("heartbeat_seconds must be lower than lease_seconds")
    return {
        "schema": CLUSTER_SCHEMA,
        "id": safe_id(cluster.get("id"), "cluster.id"),
        "coordinator": coordinator,
        "worker": worker,
        "exchange": exchange,
    }


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}-{time.time_ns()}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, canonical(value))


def _exclusive_json(path: Path, value: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def _slug(value: str) -> str:
    result = "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
    result = result.strip("-.")
    if not result:
        raise MemoryLabError("value has no safe path characters")
    return result[:180]


def _flight_root(exchange_root: Path, flight_id: str) -> Path:
    safe_id(flight_id, "flight_id", limit=180)
    return exchange_root.resolve() / "flights" / flight_id


def _hash_without(value: dict[str, Any], field: str) -> str:
    return hash_json(without_hash(value, field))


def _resolve_hostname(node: dict[str, Any], *, force_cpu: bool) -> dict[str, Any]:
    observed = socket.gethostname()
    declared = os.environ.get(node["hostname_env"]) if node.get("hostname_env") else None
    expected = declared or node.get("expected_hostname")
    if node["require_hostname"] and not force_cpu and not expected:
        raise MemoryLabError(f"node {node['id']} requires a declared hostname")
    if expected and not force_cpu and expected.casefold() != observed.casefold():
        raise MemoryLabError(
            f"node {node['id']} expected hostname {expected!r}, observed {observed!r}"
        )
    return {
        "node_id": node["id"],
        "role": node["role"],
        "hostname": observed,
        "expected_hostname": expected,
        "resolved": True,
    }


def coordinator_attestation(cluster: dict[str, Any], *, force_cpu: bool = False) -> dict[str, Any]:
    node = cluster["coordinator"]
    result = _resolve_hostname(node, force_cpu=force_cpu)
    if force_cpu:
        result["service_gpu"] = {"resolved": False, "reason": "CPU override"}
        return result
    uuid_value = os.environ.get(node["service_gpu_uuid_env"])
    if not uuid_value:
        raise MemoryLabError(
            f"coordinator requires GPU UUID through {node['service_gpu_uuid_env']}"
        )
    match = next((gpu for gpu in query_nvidia() if gpu["uuid"] == uuid_value), None)
    if match is None:
        raise MemoryLabError(f"coordinator GPU UUID {uuid_value!r} is not present")
    expected = node["service_gpu_expected_name_contains"]
    if expected.casefold() not in match["name"].casefold():
        raise MemoryLabError(
            f"coordinator expected GPU containing {expected!r}, observed {match['name']!r}"
        )
    result["service_gpu"] = {"resolved": True, "gpu": match}
    return result


def worker_attestation(
    cluster: dict[str, Any], seat: dict[str, Any], *, force_cpu: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = _resolve_hostname(cluster["worker"], force_cpu=force_cpu)
    resolution = resolve_seat_environment(seat, allow_cpu_override=force_cpu)
    node["seat"] = resolution
    return node, resolution


def _match_plan(cluster: dict[str, Any], plan: dict[str, Any]) -> None:
    plan_ids = {seat["id"] for seat in plan["resolved"]["topology"]["seats"]}
    cluster_ids = {seat["id"] for seat in cluster["worker"]["seats"]}
    if plan_ids != cluster_ids:
        raise MemoryLabError(
            f"plan seats {sorted(plan_ids)} do not match cluster seats {sorted(cluster_ids)}"
        )


def _opposite_seat(cluster: dict[str, Any], seat_id: str) -> dict[str, Any]:
    seats = cluster["worker"]["seats"]
    if len(seats) < 2:
        raise MemoryLabError("cross verification requires at least two worker seats")
    index = next(index for index, seat in enumerate(seats) if seat["id"] == seat_id)
    return seats[(index + 1) % len(seats)]


def _packet(
    *,
    flight_id: str,
    plan: dict[str, Any],
    cluster: dict[str, Any],
    trial: dict[str, Any],
    action: str,
    seat: dict[str, Any],
    dependencies: list[str],
    source_packet_id: str | None,
) -> dict[str, Any]:
    prefix = "run" if action == "run_trial" else "verify"
    packet_id = f"{prefix}--{_slug(trial['id'])}"
    value: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "flight_id": flight_id,
        "packet_id": packet_id,
        "action": action,
        "lab_id": plan["lab_id"],
        "profile": plan["profile"],
        "lab_sha256": plan["lab_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "cluster_id": cluster["id"],
        "assigned_node_id": cluster["worker"]["id"],
        "assigned_seat_id": seat["id"],
        "trial_id": trial["id"],
        "arm_id": trial["arm_id"],
        "seed": trial["seed"],
        "pair_id": trial["pair_id"],
        "dependencies": dependencies,
        "source_packet_id": source_packet_id,
        "team": {
            "mode": "artifact_parallel_cross_verification",
            "producer_seat_id": trial["seat"]["id"],
            "consumer_seat_id": seat["id"] if action == "verify_checkpoint" else None,
            "return_node_id": cluster["coordinator"]["id"],
        },
        "source_hashes": source_hashes(),
    }
    value["packet_sha256"] = _hash_without(value, "packet_sha256")
    return value


def publish_flight(
    *,
    raw_lab: dict[str, Any],
    profile: str,
    raw_cluster: dict[str, Any],
    exchange_root: Path,
    flight_id: str,
    force_cpu: bool = False,
) -> dict[str, Any]:
    cluster = validate_cluster(raw_cluster)
    plan = compile_plan(raw_lab, profile)
    errors = verify_plan(raw_lab, plan, profile)
    if errors:
        raise MemoryLabError("cannot publish invalid plan: " + "; ".join(errors))
    _match_plan(cluster, plan)
    if cluster["exchange"]["cross_verify"] and not plan["resolved"]["training"][
        "save_checkpoint"
    ]:
        raise MemoryLabError("cross verification requires save_checkpoint=true")
    coordinator = coordinator_attestation(cluster, force_cpu=force_cpu)
    root = _flight_root(exchange_root, flight_id)
    if root.exists():
        raise MemoryLabError(f"flight already exists: {root}")
    for name in (
        "inputs",
        "packets",
        "claims",
        "heartbeats",
        "submissions",
        "collections",
        "coordinator",
    ):
        (root / name).mkdir(parents=True, exist_ok=name == "inputs")
    _atomic_json(root / "inputs" / "lab.json", raw_lab)
    _atomic_json(root / "inputs" / "cluster.json", raw_cluster)
    _atomic_json(root / "inputs" / "plan.json", plan)
    packets: list[dict[str, Any]] = []
    seats = {seat["id"]: seat for seat in cluster["worker"]["seats"]}
    for trial in plan["trials"]:
        producer = seats[trial["seat"]["id"]]
        run_packet = _packet(
            flight_id=flight_id,
            plan=plan,
            cluster=cluster,
            trial=trial,
            action="run_trial",
            seat=producer,
            dependencies=[],
            source_packet_id=None,
        )
        packets.append(run_packet)
        if cluster["exchange"]["cross_verify"]:
            verifier = _opposite_seat(cluster, producer["id"])
            packets.append(
                _packet(
                    flight_id=flight_id,
                    plan=plan,
                    cluster=cluster,
                    trial=trial,
                    action="verify_checkpoint",
                    seat=verifier,
                    dependencies=[run_packet["packet_id"]],
                    source_packet_id=run_packet["packet_id"],
                )
            )
    for packet in packets:
        _atomic_json(root / "packets" / f"{packet['packet_id']}.json", packet)
    manifest: dict[str, Any] = {
        "schema": FLIGHT_SCHEMA,
        "flight_id": flight_id,
        "published_at": now_utc(),
        "lab_id": plan["lab_id"],
        "profile": plan["profile"],
        "lab_sha256": plan["lab_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "cluster": cluster,
        "coordinator_attestation": coordinator,
        "source_hashes": source_hashes(),
        "packets": [
            {
                "packet_id": packet["packet_id"],
                "packet_sha256": packet["packet_sha256"],
                "action": packet["action"],
                "assigned_node_id": packet["assigned_node_id"],
                "assigned_seat_id": packet["assigned_seat_id"],
                "trial_id": packet["trial_id"],
                "dependencies": packet["dependencies"],
            }
            for packet in packets
        ],
        "authority": {
            "scheduler": cluster["coordinator"]["id"],
            "execution": cluster["worker"]["id"],
            "teaming": "parallel independent trials plus opposite-seat checkpoint replay",
            "transport": "content-addressed shared-filesystem artifacts",
        },
    }
    manifest["manifest_sha256"] = _hash_without(manifest, "manifest_sha256")
    _atomic_json(root / "manifest.json", manifest)
    return {"root": str(root), "plan": plan, "manifest": manifest}


def load_flight(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = load_json(root / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema") != FLIGHT_SCHEMA:
        raise MemoryLabError(f"flight manifest schema must be {FLIGHT_SCHEMA}")
    if manifest.get("manifest_sha256") != _hash_without(manifest, "manifest_sha256"):
        raise MemoryLabError("flight manifest hash does not verify")
    raw_lab = load_json(root / "inputs" / "lab.json")
    raw_cluster = load_json(root / "inputs" / "cluster.json")
    cluster = validate_cluster(raw_cluster)
    plan = load_json(root / "inputs" / "plan.json")
    errors = verify_plan(raw_lab, plan, plan.get("profile") if isinstance(plan, dict) else None)
    if errors:
        raise MemoryLabError("flight plan verification failed: " + "; ".join(errors))
    _match_plan(cluster, plan)
    if manifest["source_hashes"] != source_hashes():
        raise MemoryLabError("flight source hashes differ from this checkout")
    return manifest, raw_lab, cluster, plan


def packet_by_id(root: Path, packet_id: str) -> dict[str, Any]:
    packet = load_json(root / "packets" / f"{packet_id}.json")
    if packet.get("schema") != PACKET_SCHEMA:
        raise MemoryLabError(f"packet schema is invalid: {packet_id}")
    if packet.get("packet_sha256") != _hash_without(packet, "packet_sha256"):
        raise MemoryLabError(f"packet hash is invalid: {packet_id}")
    return packet


def packets_for_seat(root: Path, node_id: str, seat_id: str) -> list[dict[str, Any]]:
    manifest, _, _, _ = load_flight(root)
    rows = [
        packet_by_id(root, row["packet_id"])
        for row in manifest["packets"]
        if row["assigned_node_id"] == node_id and row["assigned_seat_id"] == seat_id
    ]
    return sorted(rows, key=lambda row: (len(row["dependencies"]), row["packet_id"]))


def _submission_dirs(root: Path, packet_id: str) -> list[Path]:
    packet_root = root / "submissions" / packet_id
    return sorted(packet_root.glob("attempt-*")) if packet_root.exists() else []


def _load_submission(path: Path) -> dict[str, Any]:
    value = load_json(path / "submission.json")
    if value.get("schema") != SUBMISSION_SCHEMA:
        raise MemoryLabError(f"submission schema is invalid: {path}")
    if value.get("submission_sha256") != _hash_without(value, "submission_sha256"):
        raise MemoryLabError(f"submission hash does not verify: {path}")
    for file in value["files"]:
        target = path / file["path"]
        if not target.exists() or target.stat().st_size != file["bytes"]:
            raise MemoryLabError(f"submission file size mismatch: {target}")
        if hash_file(target) != file["sha256"]:
            raise MemoryLabError(f"submission file hash mismatch: {target}")
    return value


def selected_submission(root: Path, packet_id: str) -> tuple[Path, dict[str, Any]] | None:
    valid: list[tuple[Path, dict[str, Any]]] = []
    for path in _submission_dirs(root, packet_id):
        try:
            value = _load_submission(path)
        except MemoryLabError:
            continue
        if value["status"] == "completed":
            valid.append((path, value))
    return min(valid, key=lambda row: row[1]["attempt"]) if valid else None


def latest_submission(root: Path, packet_id: str) -> tuple[Path, dict[str, Any]] | None:
    valid: list[tuple[Path, dict[str, Any]]] = []
    for path in _submission_dirs(root, packet_id):
        try:
            valid.append((path, _load_submission(path)))
        except MemoryLabError:
            continue
    return max(valid, key=lambda row: row[1]["attempt"]) if valid else None


def _dependencies_ready(root: Path, packet: dict[str, Any]) -> bool:
    return all(selected_submission(root, value) is not None for value in packet["dependencies"])


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _claim_stale(path: Path, lease_seconds: float) -> bool:
    try:
        claim = load_json(path)
        timestamp = _parse_time(claim.get("heartbeat_at") or claim["claimed_at"])
    except Exception:
        timestamp = path.stat().st_mtime
    return time.time() - timestamp > lease_seconds


@contextmanager
def claim_packet(
    *,
    root: Path,
    packet: dict[str, Any],
    attestation: dict[str, Any],
    exchange: dict[str, Any],
    reclaim_stale: bool,
) -> Iterator[None]:
    path = root / "claims" / f"{packet['packet_id']}.json"
    if path.exists() and (reclaim_stale and _claim_stale(path, exchange["lease_seconds"])):
        history = root / "claims" / "history"
        history.mkdir(parents=True, exist_ok=True)
        os.replace(path, history / f"{packet['packet_id']}-{time.time_ns()}.json")
    claim: dict[str, Any] = {
        "schema": CLAIM_SCHEMA,
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["packet_sha256"],
        "attestation": attestation,
        "process_id": os.getpid(),
        "claimed_at": now_utc(),
        "heartbeat_at": now_utc(),
        "lease_seconds": exchange["lease_seconds"],
    }
    claim["claim_sha256"] = _hash_without(claim, "claim_sha256")
    if not _exclusive_json(path, claim):
        raise MemoryLabError(f"packet is already claimed: {packet['packet_id']}")
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(exchange["heartbeat_seconds"]):
            claim["heartbeat_at"] = now_utc()
            claim["claim_sha256"] = _hash_without(claim, "claim_sha256")
            _atomic_json(path, claim)
            _atomic_json(
                root / "heartbeats" / f"{packet['packet_id']}.json",
                {
                    "schema": "tier-bench/conditional-memory-heartbeat@1",
                    "packet_id": packet["packet_id"],
                    "captured_at": claim["heartbeat_at"],
                    "attestation": attestation,
                },
            )

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=exchange["heartbeat_seconds"] * 2)
        claim["released_at"] = now_utc()
        claim["heartbeat_at"] = claim["released_at"]
        claim["claim_sha256"] = _hash_without(claim, "claim_sha256")
        _atomic_json(path, claim)


def _next_attempt(root: Path, packet_id: str) -> int:
    values: list[int] = []
    for path in _submission_dirs(root, packet_id):
        try:
            values.append(int(path.name.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return max(values, default=0) + 1


def _copy(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{time.time_ns()}")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return {"path": destination.name, "bytes": destination.stat().st_size, "sha256": hash_file(destination)}


def _publish_submission(
    *,
    root: Path,
    packet: dict[str, Any],
    attempt: int,
    status: str,
    attestation: dict[str, Any],
    files: list[tuple[Path, str]],
    result_sha256: str,
) -> dict[str, Any]:
    destination = root / "submissions" / packet["packet_id"] / f"attempt-{attempt:03d}"
    if destination.exists():
        raise MemoryLabError(f"submission attempt already exists: {destination}")
    destination.mkdir(parents=True)
    file_rows = [_copy(source, destination / name) for source, name in files]
    value: dict[str, Any] = {
        "schema": SUBMISSION_SCHEMA,
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["packet_sha256"],
        "action": packet["action"],
        "status": status,
        "attempt": attempt,
        "trial_id": packet["trial_id"],
        "node_id": packet["assigned_node_id"],
        "seat_id": packet["assigned_seat_id"],
        "attestation": attestation,
        "result_sha256": result_sha256,
        "submitted_at": now_utc(),
        "files": sorted(file_rows, key=lambda row: row["path"]),
    }
    value["submission_sha256"] = _hash_without(value, "submission_sha256")
    _atomic_json(destination / "submission.json", value)
    return value


def _find_receipt(work_root: Path, receipt_sha256: str) -> Path:
    matches = []
    for path in work_root.rglob("receipt.json"):
        value = load_json(path)
        if value.get("receipt_sha256") == receipt_sha256:
            matches.append(path)
    if len(matches) != 1:
        raise MemoryLabError(f"expected one local receipt, found {matches}")
    return matches[0]


def verify_checkpoint(
    *,
    plan: dict[str, Any],
    trial: dict[str, Any],
    source_receipt: dict[str, Any],
    checkpoint_path: Path,
    out: Path,
    seat_resolution: dict[str, Any],
    force_cpu: bool,
    loss_tolerance: float,
    require_top_token_match: bool,
) -> dict[str, Any]:
    try:
        import torch
        from .conditional_memory_models import ConditionalMemoryLM
        from .conditional_memory_runner import (
            _evaluate,
            _golden_logits,
            materialize_dataset,
            state_dict_sha256,
        )
    except ImportError as exc:
        raise MemoryLabError("cross verification requires PyTorch") from exc
    if hash_file(checkpoint_path) != source_receipt["model"]["checkpoint_sha256"]:
        raise MemoryLabError("checkpoint bytes differ from the producer receipt")
    try:
        state = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(checkpoint_path, map_location="cpu")
    model = ConditionalMemoryLM(trial)
    model.load_state_dict(state, strict=True)
    observed_state = state_dict_sha256(model)
    if observed_state != source_receipt["model"]["final_state_sha256"]:
        raise MemoryLabError("checkpoint state differs from the producer final state")
    device = torch.device("cpu" if force_cpu or trial["seat"]["kind"] == "cpu" else "cuda:0")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise MemoryLabError("cross verification requires CUDA but torch reports none")
    model.configure_device(device)
    _, validation, fingerprint = materialize_dataset(
        trial["dataset"], trial_seed=trial["seed"]
    )
    if fingerprint["combined_sha256"] != source_receipt["data"]["combined_sha256"]:
        raise MemoryLabError("verification data differs from the producer data")
    evaluation = _evaluate(
        model,
        validation,
        batch_size=trial["training"]["batch_size"],
        device=device,
        amp=trial["training"]["amp"],
    )
    golden = _golden_logits(
        model, validation, device=device, amp=trial["training"]["amp"]
    )
    source_loss = float(source_receipt["evaluation"]["validation_loss"])
    observed_loss = float(evaluation["validation_loss"])
    relative_loss = abs(observed_loss - source_loss) / max(abs(source_loss), 1e-12)
    source_tokens = [row["token_id"] for row in source_receipt["golden"]["top_tokens"]]
    observed_tokens = [row["token_id"] for row in golden["top_tokens"]]
    top_match = source_tokens == observed_tokens
    passed = relative_loss <= loss_tolerance and (
        top_match or not require_top_token_match
    )
    value: dict[str, Any] = {
        "schema": CROSS_VERIFY_SCHEMA,
        "status": "completed" if passed else "failed",
        "plan_sha256": plan["plan_sha256"],
        "trial_id": trial["id"],
        "source_receipt_sha256": source_receipt["receipt_sha256"],
        "source_checkpoint_sha256": source_receipt["model"]["checkpoint_sha256"],
        "source_seat": source_receipt["seat"],
        "verification_seat": trial["seat"],
        "seat_resolution": seat_resolution,
        "captured_at": now_utc(),
        "model_state_sha256": observed_state,
        "data_sha256": fingerprint["combined_sha256"],
        "evaluation": evaluation,
        "golden": golden,
        "comparison": {
            "pass": passed,
            "source_validation_loss": source_loss,
            "observed_validation_loss": observed_loss,
            "relative_validation_loss_change_abs": relative_loss,
            "loss_tolerance": loss_tolerance,
            "top_token_order_match": top_match,
            "require_top_token_match": require_top_token_match,
        },
    }
    value["verification_sha256"] = _hash_without(value, "verification_sha256")
    _atomic_json(out, value)
    return value


def run_packet(
    *,
    root: Path,
    packet: dict[str, Any],
    work_root: Path,
    attestation: dict[str, Any],
    seat_resolution: dict[str, Any],
    force_cpu: bool,
    reclaim_stale: bool,
) -> dict[str, Any]:
    manifest, _, cluster, plan = load_flight(root)
    if selected_submission(root, packet["packet_id"]):
        return {"packet_id": packet["packet_id"], "status": "skipped_completed"}
    if not _dependencies_ready(root, packet):
        return {"packet_id": packet["packet_id"], "status": "blocked_dependencies"}
    attempt = _next_attempt(root, packet["packet_id"])
    with claim_packet(
        root=root,
        packet=packet,
        attestation=attestation,
        exchange=cluster["exchange"],
        reclaim_stale=reclaim_stale,
    ):
        trial = trial_by_id(plan, packet["trial_id"])
        local = work_root.resolve() / manifest["flight_id"] / packet["packet_id"]
        local.mkdir(parents=True, exist_ok=True)
        if packet["action"] == "run_trial":
            from .conditional_memory_runner import execute_trial

            receipt = execute_trial(
                plan=plan,
                trial=trial,
                state_dir=local,
                seat_resolution=seat_resolution,
                attempt=attempt,
                force_cpu=force_cpu,
            )
            receipt_path = _find_receipt(local, receipt["receipt_sha256"])
            files: list[tuple[Path, str]] = [(receipt_path, "receipt.json")]
            checkpoint = (receipt.get("model") or {}).get("checkpoint_path")
            if checkpoint and cluster["exchange"]["copy_checkpoints"]:
                files.append((Path(checkpoint), "checkpoint.pt"))
            submission = _publish_submission(
                root=root,
                packet=packet,
                attempt=attempt,
                status=receipt["status"],
                attestation=attestation,
                files=files,
                result_sha256=receipt["receipt_sha256"],
            )
            return {
                "packet_id": packet["packet_id"],
                "status": submission["status"],
                "submission_sha256": submission["submission_sha256"],
            }
        source = selected_submission(root, packet["source_packet_id"])
        if source is None:
            return {"packet_id": packet["packet_id"], "status": "blocked_dependencies"}
        source_path, _ = source
        source_receipt = load_json(source_path / "receipt.json")
        verify_trial = dict(trial)
        verify_trial["seat"] = next(
            seat
            for seat in cluster["worker"]["seats"]
            if seat["id"] == packet["assigned_seat_id"]
        )
        result_path = local / f"attempt-{attempt:03d}" / "cross-verification.json"
        result = verify_checkpoint(
            plan=plan,
            trial=verify_trial,
            source_receipt=source_receipt,
            checkpoint_path=source_path / "checkpoint.pt",
            out=result_path,
            seat_resolution=seat_resolution,
            force_cpu=force_cpu,
            loss_tolerance=cluster["exchange"]["verification_loss_tolerance"],
            require_top_token_match=cluster["exchange"]["require_top_token_match"],
        )
        submission = _publish_submission(
            root=root,
            packet=packet,
            attempt=attempt,
            status=result["status"],
            attestation=attestation,
            files=[(result_path, "cross-verification.json")],
            result_sha256=result["verification_sha256"],
        )
        return {
            "packet_id": packet["packet_id"],
            "status": submission["status"],
            "submission_sha256": submission["submission_sha256"],
        }


def run_worker_seat(
    *,
    root: Path,
    node_id: str,
    seat_id: str,
    work_root: Path,
    force_cpu: bool,
    reclaim_stale: bool,
    max_wait_seconds: float,
) -> dict[str, Any]:
    manifest, _, cluster, _ = load_flight(root)
    if node_id != cluster["worker"]["id"]:
        raise MemoryLabError(f"flight has no worker node {node_id}")
    seat = next((row for row in cluster["worker"]["seats"] if row["id"] == seat_id), None)
    if seat is None:
        raise MemoryLabError(f"worker node has no seat {seat_id}")
    attestation, resolution = worker_attestation(cluster, seat, force_cpu=force_cpu)
    packets = packets_for_seat(root, node_id, seat_id)
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    while True:
        pending = [row for row in packets if selected_submission(root, row["packet_id"]) is None]
        if not pending:
            break
        progress = False
        for packet in pending:
            if not _dependencies_ready(root, packet):
                continue
            result = run_packet(
                root=root,
                packet=packet,
                work_root=work_root,
                attestation=attestation,
                seat_resolution=resolution,
                force_cpu=force_cpu,
                reclaim_stale=reclaim_stale,
            )
            results.append(result)
            progress = True
            if result["status"] == "failed":
                return {
                    "ok": False,
                    "flight_id": manifest["flight_id"],
                    "seat_id": seat_id,
                    "results": results,
                }
        if not progress:
            if time.monotonic() - started > max_wait_seconds:
                raise MemoryLabError(
                    f"seat {seat_id} timed out waiting for packet dependencies"
                )
            time.sleep(cluster["exchange"]["poll_seconds"])
    return {
        "ok": True,
        "flight_id": manifest["flight_id"],
        "seat_id": seat_id,
        "results": results,
    }


def run_worker_node(
    *,
    root: Path,
    node_id: str,
    work_root: Path,
    force_cpu: bool,
    reclaim_stale: bool,
    max_wait_seconds: float,
) -> dict[str, Any]:
    manifest, _, cluster, _ = load_flight(root)
    if node_id != cluster["worker"]["id"]:
        raise MemoryLabError(f"flight has no worker node {node_id}")
    log_root = work_root.resolve() / manifest["flight_id"] / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[dict[str, Any], subprocess.Popen[str], Any, Any, Path, Path]] = []
    for seat in cluster["worker"]["seats"]:
        stdout_path = log_root / f"{_slug(seat['id'])}.stdout.log"
        stderr_path = log_root / f"{_slug(seat['id'])}.stderr.log"
        stdout = stdout_path.open("w", encoding="utf-8", newline="\n")
        stderr = stderr_path.open("w", encoding="utf-8", newline="\n")
        argv = [
            sys.executable,
            "-m",
            "tier_runner.conditional_memory_exchange_cli",
            "worker-seat",
            "--flight-root",
            str(root),
            "--node",
            node_id,
            "--seat",
            seat["id"],
            "--work-root",
            str(work_root),
            "--max-wait-seconds",
            str(max_wait_seconds),
        ]
        if force_cpu:
            argv.append("--force-cpu")
        if reclaim_stale:
            argv.append("--reclaim-stale")
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, text=True)
        rows.append((seat, process, stdout, stderr, stdout_path, stderr_path))
    outcomes: list[dict[str, Any]] = []
    for seat, process, stdout, stderr, stdout_path, stderr_path in rows:
        return_code = process.wait()
        stdout.close()
        stderr.close()
        outcomes.append(
            {
                "seat_id": seat["id"],
                "return_code": return_code,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            }
        )
    return {
        "ok": all(row["return_code"] == 0 for row in outcomes),
        "flight_id": manifest["flight_id"],
        "node_id": node_id,
        "seats": outcomes,
    }


def list_flights(exchange_root: Path) -> list[Path]:
    root = exchange_root.resolve() / "flights"
    return sorted(path for path in root.iterdir() if (path / "manifest.json").exists()) if root.exists() else []


def worker_loop(
    *,
    exchange_root: Path,
    node_id: str,
    work_root: Path,
    once: bool,
    poll_seconds: float,
    force_cpu: bool,
    reclaim_stale: bool,
    max_wait_seconds: float,
) -> dict[str, Any]:
    processed: list[dict[str, Any]] = []
    while True:
        found = False
        for root in list_flights(exchange_root):
            manifest, _, cluster, _ = load_flight(root)
            if cluster["worker"]["id"] != node_id:
                continue
            assigned = [row for row in manifest["packets"] if row["assigned_node_id"] == node_id]
            if not any(selected_submission(root, row["packet_id"]) is None for row in assigned):
                continue
            found = True
            result = run_worker_node(
                root=root,
                node_id=node_id,
                work_root=work_root,
                force_cpu=force_cpu,
                reclaim_stale=reclaim_stale,
                max_wait_seconds=max_wait_seconds,
            )
            processed.append(result)
            if not result["ok"]:
                return {"ok": False, "processed": processed}
        if once:
            break
        if not found:
            time.sleep(poll_seconds)
    return {"ok": all(row["ok"] for row in processed), "processed": processed}


def exchange_status(root: Path) -> dict[str, Any]:
    manifest, _, _, _ = load_flight(root)
    counts = {"pending": 0, "claimed": 0, "completed": 0, "failed": 0, "collected": 0}
    packets = []
    for row in manifest["packets"]:
        packet_id = row["packet_id"]
        selected = selected_submission(root, packet_id)
        latest = latest_submission(root, packet_id)
        if (root / "collections" / f"{packet_id}.json").exists():
            state = "collected"
        elif selected:
            state = "completed"
        elif latest:
            state = "failed"
        elif (root / "claims" / f"{packet_id}.json").exists():
            state = "claimed"
        else:
            state = "pending"
        counts[state] += 1
        packets.append({**row, "state": state})
    result = {
        "schema": STATUS_SCHEMA,
        "flight_id": manifest["flight_id"],
        "plan_sha256": manifest["plan_sha256"],
        "counts": counts,
        "packets": packets,
    }
    result["status_sha256"] = _hash_without(result, "status_sha256")
    return result


def _cross_verify_valid(value: dict[str, Any], plan: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schema") != CROSS_VERIFY_SCHEMA:
        errors.append("cross verification schema is invalid")
    if value.get("verification_sha256") != _hash_without(value, "verification_sha256"):
        errors.append("cross verification hash does not verify")
    if value.get("plan_sha256") != plan["plan_sha256"]:
        errors.append("cross verification belongs to another plan")
    if value.get("trial_id") != packet["trial_id"]:
        errors.append("cross verification belongs to another trial")
    if value.get("verification_seat", {}).get("id") != packet["assigned_seat_id"]:
        errors.append("cross verification ran on the wrong seat")
    if value.get("status") != "completed" or not value.get("comparison", {}).get("pass"):
        errors.append("cross verification did not pass")
    if value.get("source_seat", {}).get("id") == value.get("verification_seat", {}).get("id"):
        errors.append("producer and verifier seats are identical")
    return errors


def _copy_verified(source: Path, destination: Path, expected_sha256: str) -> dict[str, Any]:
    if hash_file(source) != expected_sha256:
        raise MemoryLabError(f"source hash mismatch: {source}")
    row = _copy(source, destination)
    if row["sha256"] != expected_sha256:
        raise MemoryLabError(f"copied hash mismatch: {destination}")
    return row


def collect_flight(
    *,
    root: Path,
    coordinator_state: Path,
    force_cpu: bool = False,
) -> dict[str, Any]:
    manifest, raw_lab, cluster, plan = load_flight(root)
    coordinator = coordinator_attestation(cluster, force_cpu=force_cpu)
    imported = coordinator_state.resolve() / manifest["flight_id"]
    imported.mkdir(parents=True, exist_ok=True)
    _atomic_json(imported / "lab.json", raw_lab)
    _atomic_json(imported / "plan.json", plan)
    errors: list[dict[str, Any]] = []
    collections: list[dict[str, Any]] = []
    verified_trials: set[str] = set()
    for row in manifest["packets"]:
        packet = packet_by_id(root, row["packet_id"])
        selected = selected_submission(root, packet["packet_id"])
        if selected is None:
            errors.append({"packet_id": packet["packet_id"], "error": "no completed submission"})
            continue
        submission_path, submission = selected
        destination = imported / _slug(packet["trial_id"]) / packet["action"]
        destination.mkdir(parents=True, exist_ok=True)
        files = {value["path"]: value for value in submission["files"]}
        imported_files: list[dict[str, Any]] = []
        try:
            if packet["action"] == "run_trial":
                receipt = load_json(submission_path / "receipt.json")
                receipt_errors = validate_receipt(receipt, plan)
                if receipt_errors:
                    raise MemoryLabError("; ".join(receipt_errors))
                imported_files.append(
                    _copy_verified(
                        submission_path / "receipt.json",
                        destination / "receipt.json",
                        files["receipt.json"]["sha256"],
                    )
                )
                if "checkpoint.pt" in files:
                    checkpoint_row = _copy_verified(
                        submission_path / "checkpoint.pt",
                        destination / "checkpoint.pt",
                        files["checkpoint.pt"]["sha256"],
                    )
                    imported_files.append(checkpoint_row)
                    local_receipt = dict(receipt)
                    local_receipt["origin_receipt_sha256"] = receipt["receipt_sha256"]
                    local_receipt["model"] = dict(receipt["model"])
                    local_receipt["model"]["checkpoint_path"] = str(
                        (destination / "checkpoint.pt").resolve()
                    )
                    local_receipt["receipt_sha256"] = _hash_without(
                        local_receipt, "receipt_sha256"
                    )
                    _atomic_json(destination / "receipt.local.json", local_receipt)
            else:
                verification = load_json(submission_path / "cross-verification.json")
                verification_errors = _cross_verify_valid(verification, plan, packet)
                if verification_errors:
                    raise MemoryLabError("; ".join(verification_errors))
                verified_trials.add(packet["trial_id"])
                imported_files.append(
                    _copy_verified(
                        submission_path / "cross-verification.json",
                        destination / "cross-verification.json",
                        files["cross-verification.json"]["sha256"],
                    )
                )
            collection: dict[str, Any] = {
                "schema": COLLECTION_SCHEMA,
                "packet_id": packet["packet_id"],
                "packet_sha256": packet["packet_sha256"],
                "submission_sha256": submission["submission_sha256"],
                "trial_id": packet["trial_id"],
                "action": packet["action"],
                "coordinator_attestation": coordinator,
                "collected_at": now_utc(),
                "destination": str(destination),
                "files": imported_files,
            }
            collection["collection_sha256"] = _hash_without(
                collection, "collection_sha256"
            )
            _atomic_json(root / "collections" / f"{packet['packet_id']}.json", collection)
            _atomic_json(destination / "collection.json", collection)
            collections.append(collection)
        except MemoryLabError as exc:
            errors.append({"packet_id": packet["packet_id"], "error": str(exc)})
    expected_trials = {trial["id"] for trial in plan["trials"]}
    if cluster["exchange"]["cross_verify"] and verified_trials != expected_trials:
        errors.append(
            {
                "error": "cross-verification coverage is incomplete",
                "missing_trials": sorted(expected_trials - verified_trials),
            }
        )
    report = build_report(plan, imported)
    cluster_report: dict[str, Any] = {
        "schema": "tier-bench/conditional-memory-cluster-report@1",
        "flight_id": manifest["flight_id"],
        "plan_sha256": plan["plan_sha256"],
        "report_sha256": report["report_sha256"],
        "packet_count": len(manifest["packets"]),
        "collection_count": len(collections),
        "cross_verified_trials": sorted(verified_trials),
        "cross_verified_count": len(verified_trials),
        "expected_trial_count": len(expected_trials),
        "errors": errors,
        "promotable_arms": report["promotable_arms"],
        "promotion_authorized": False,
    }
    cluster_report["cluster_report_sha256"] = _hash_without(
        cluster_report, "cluster_report_sha256"
    )
    _atomic_json(imported / "report.json", report)
    _atomic_json(imported / "cluster-report.json", cluster_report)
    _atomic_json(root / "coordinator" / "report.json", report)
    _atomic_json(root / "coordinator" / "cluster-report.json", cluster_report)
    return {
        "ok": not errors and report["status"]["ok"],
        "flight_id": manifest["flight_id"],
        "coordinator_state": str(imported),
        "report_sha256": report["report_sha256"],
        "cluster_report_sha256": cluster_report["cluster_report_sha256"],
        "cross_verified_count": len(verified_trials),
        "errors": errors,
        "promotable_arms": report["promotable_arms"],
        "promotion_authorized": False,
    }
