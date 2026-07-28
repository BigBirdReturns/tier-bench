"""Content-addressed multi-host exchange for Conditional Memory Lab flights.

The desktop coordinator and LG Gram worker may see the same SMB/Tailscale share at
unrelated local paths. The exchange therefore binds only relative flight paths and
content hashes. Workers use local scratch for model execution, then submit immutable
receipts and checkpoint artifacts. Cross-verification packets send each checkpoint
to the opposite 3090 seat before the coordinator accepts the matrix.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import shutil
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
from .conditional_memory_hardware import resolve_node_environment, resolve_seat_environment
from .conditional_memory_plan import node_by_id, seats_for_node, trial_by_id, verify_plan
from .conditional_memory_report import build_report, validate_receipt
from .conditional_memory_schema import (
    COLLECTION_SCHEMA,
    CROSS_VERIFY_SCHEMA,
    FLIGHT_SCHEMA,
    PACKET_SCHEMA,
    SUBMISSION_SCHEMA,
)

CLAIM_SCHEMA = "tier-bench/conditional-memory-claim@1"
HEARTBEAT_SCHEMA = "tier-bench/conditional-memory-heartbeat@1"
EXCHANGE_STATUS_SCHEMA = "tier-bench/conditional-memory-exchange-status@1"

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
    "conditional_memory_cli.py",
)


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {name: hash_file(root / name) for name in _SOURCE_FILES if (root / name).exists()}


def _slug(value: str) -> str:
    result = "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
    result = result.strip("-.")
    if not result:
        raise MemoryLabError("value has no safe path characters")
    return result[:180]


def _flight_root(exchange_root: Path, flight_id: str) -> Path:
    safe_id(flight_id, "flight_id", limit=180)
    return exchange_root.resolve() / "flights" / flight_id


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


def _copy_verified(source: Path, destination: Path, expected_sha256: str) -> dict[str, Any]:
    if not source.exists():
        raise MemoryLabError(f"artifact does not exist: {source}")
    observed = hash_file(source)
    if observed != expected_sha256:
        raise MemoryLabError(
            f"artifact hash mismatch for {source}: expected {expected_sha256}, observed {observed}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{os.getpid()}-{time.time_ns()}")
    shutil.copy2(source, temporary)
    copied = hash_file(temporary)
    if copied != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise MemoryLabError(f"copied artifact hash mismatch for {destination}")
    os.replace(temporary, destination)
    return {"path": destination.name, "bytes": destination.stat().st_size, "sha256": copied}


def _parse_time(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError) as exc:
        raise MemoryLabError(f"invalid timestamp {value!r}") from exc


def _packet_hash(packet: dict[str, Any]) -> str:
    return hash_json(without_hash(packet, "packet_sha256"))


def _manifest_hash(manifest: dict[str, Any]) -> str:
    return hash_json(without_hash(manifest, "manifest_sha256"))


def _submission_hash(submission: dict[str, Any]) -> str:
    return hash_json(without_hash(submission, "submission_sha256"))


def _collection_hash(collection: dict[str, Any]) -> str:
    return hash_json(without_hash(collection, "collection_sha256"))


def _opposite_seat(plan: dict[str, Any], seat: dict[str, Any]) -> dict[str, Any]:
    seats = seats_for_node(plan, seat["node_id"])
    if len(seats) < 2:
        raise MemoryLabError(
            f"cross verification requires at least two seats on node {seat['node_id']}"
        )
    index = next(index for index, value in enumerate(seats) if value["id"] == seat["id"])
    return seats[(index + 1) % len(seats)]


def _packet(
    *,
    flight_id: str,
    plan: dict[str, Any],
    packet_id: str,
    action: str,
    node_id: str,
    seat: dict[str, Any],
    trial: dict[str, Any],
    dependencies: list[str],
    source_packet_id: str | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "flight_id": flight_id,
        "packet_id": packet_id,
        "action": action,
        "lab_id": plan["lab_id"],
        "profile": plan["profile"],
        "lab_sha256": plan["lab_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "assigned_node_id": node_id,
        "assigned_seat_id": seat["id"],
        "trial_id": trial["id"],
        "arm_id": trial["arm_id"],
        "seed": trial["seed"],
        "pair_id": trial["pair_id"],
        "dependencies": dependencies,
        "source_packet_id": source_packet_id,
        "team": {
            "mode": "artifact_parallel_cross_verification",
            "cohort_id": trial["pair_id"],
            "producer_seat_id": trial["seat"]["id"],
            "consumer_seat_id": seat["id"] if action == "verify_checkpoint" else None,
            "return_node_id": plan["resolved"]["topology"]["coordinator_node"],
        },
        "inputs": {
            "lab": "inputs/lab.json",
            "plan": "inputs/plan.json",
            "source_hashes": source_hashes(),
        },
        "outputs": (
            ["receipt.json", "checkpoint.pt", "submission.json"]
            if action == "run_trial"
            else ["cross-verification.json", "submission.json"]
        ),
    }
    value["packet_sha256"] = _packet_hash(value)
    return value


def publish_flight(
    *,
    raw_lab: dict[str, Any],
    plan: dict[str, Any],
    exchange_root: Path,
    flight_id: str,
    coordinator_attestation: dict[str, Any],
) -> dict[str, Any]:
    errors = verify_plan(raw_lab, plan, plan.get("profile"))
    if errors:
        raise MemoryLabError("cannot publish invalid plan: " + "; ".join(errors))
    topology = plan["resolved"]["topology"]
    exchange = topology.get("exchange")
    if not exchange or exchange["kind"] != "shared_filesystem":
        raise MemoryLabError("multi-host publish requires shared_filesystem exchange")
    coordinator_id = topology["coordinator_node"]
    if coordinator_attestation.get("node_id") != coordinator_id:
        raise MemoryLabError("coordinator attestation does not match the plan")
    root = _flight_root(exchange_root, flight_id)
    if root.exists():
        raise MemoryLabError(f"flight already exists: {root}")
    (root / "inputs").mkdir(parents=True, exist_ok=False)
    for name in ("packets", "claims", "heartbeats", "submissions", "collections", "logs", "coordinator"):
        (root / name).mkdir()
    _atomic_json(root / "inputs" / "lab.json", raw_lab)
    _atomic_json(root / "inputs" / "plan.json", plan)
    packets: list[dict[str, Any]] = []
    cross_verify = bool(exchange["cross_verify"])
    if cross_verify and not plan["resolved"]["training"]["save_checkpoint"]:
        raise MemoryLabError(
            "cross verification requires training.save_checkpoint=true for the selected profile"
        )
    for trial in plan["trials"]:
        train_id = "run--" + _slug(trial["id"])
        packets.append(
            _packet(
                flight_id=flight_id,
                plan=plan,
                packet_id=train_id,
                action="run_trial",
                node_id=trial["node_id"],
                seat=trial["seat"],
                trial=trial,
                dependencies=[],
                source_packet_id=None,
            )
        )
        if cross_verify:
            verify_seat = _opposite_seat(plan, trial["seat"])
            packets.append(
                _packet(
                    flight_id=flight_id,
                    plan=plan,
                    packet_id="verify--" + _slug(trial["id"]),
                    action="verify_checkpoint",
                    node_id=verify_seat["node_id"],
                    seat=verify_seat,
                    trial=trial,
                    dependencies=[train_id],
                    source_packet_id=train_id,
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
        "coordinator_node_id": coordinator_id,
        "coordinator_attestation": coordinator_attestation,
        "exchange": exchange,
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
            "scheduler": coordinator_id,
            "execution": "assigned worker node and GPU UUID",
            "handoff": "content hashes and atomic shared-filesystem publication",
            "verification": "opposite-seat checkpoint replay plus coordinator report",
        },
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    _atomic_json(root / "manifest.json", manifest)
    return {"root": str(root), **manifest}


def load_flight(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = load_json(root / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema") != FLIGHT_SCHEMA:
        raise MemoryLabError(f"flight manifest schema must be {FLIGHT_SCHEMA}")
    if manifest.get("manifest_sha256") != _manifest_hash(manifest):
        raise MemoryLabError("flight manifest hash does not verify")
    raw_lab = load_json(root / "inputs" / "lab.json")
    plan = load_json(root / "inputs" / "plan.json")
    errors = verify_plan(raw_lab, plan, plan.get("profile") if isinstance(plan, dict) else None)
    if errors:
        raise MemoryLabError("flight plan verification failed: " + "; ".join(errors))
    if plan["plan_sha256"] != manifest["plan_sha256"]:
        raise MemoryLabError("flight plan identity differs from the manifest")
    packet_rows = {row["packet_id"]: row for row in manifest["packets"]}
    if len(packet_rows) != len(manifest["packets"]):
        raise MemoryLabError("flight manifest contains duplicate packet ids")
    for packet_id, row in packet_rows.items():
        packet = load_json(root / "packets" / f"{packet_id}.json")
        if packet.get("packet_sha256") != _packet_hash(packet):
            raise MemoryLabError(f"packet hash does not verify: {packet_id}")
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise MemoryLabError(f"packet differs from manifest: {packet_id}")
    return manifest, raw_lab, plan


def packet_by_id(root: Path, packet_id: str) -> dict[str, Any]:
    packet = load_json(root / "packets" / f"{packet_id}.json")
    if packet.get("schema") != PACKET_SCHEMA or packet.get("packet_sha256") != _packet_hash(packet):
        raise MemoryLabError(f"invalid packet {packet_id}")
    return packet


def packets_for_seat(root: Path, node_id: str, seat_id: str) -> list[dict[str, Any]]:
    manifest, _, _ = load_flight(root)
    packets = [
        packet_by_id(root, row["packet_id"])
        for row in manifest["packets"]
        if row["assigned_node_id"] == node_id and row["assigned_seat_id"] == seat_id
    ]
    return sorted(packets, key=lambda row: (len(row["dependencies"]), row["packet_id"]))


def _submission_attempts(root: Path, packet_id: str) -> list[Path]:
    packet_root = root / "submissions" / packet_id
    if not packet_root.exists():
        return []
    return sorted(path for path in packet_root.glob("attempt-*") if path.is_dir())


def _load_submission(path: Path) -> dict[str, Any]:
    submission = load_json(path / "submission.json")
    if submission.get("schema") != SUBMISSION_SCHEMA:
        raise MemoryLabError(f"submission schema is invalid: {path}")
    if submission.get("submission_sha256") != _submission_hash(submission):
        raise MemoryLabError(f"submission hash does not verify: {path}")
    for file in submission.get("files", []):
        target = path / file["path"]
        if not target.exists() or target.stat().st_size != file["bytes"]:
            raise MemoryLabError(f"submission file size mismatch: {target}")
        if hash_file(target) != file["sha256"]:
            raise MemoryLabError(f"submission file hash mismatch: {target}")
    return submission


def selected_submission(root: Path, packet_id: str) -> tuple[Path, dict[str, Any]] | None:
    valid: list[tuple[Path, dict[str, Any]]] = []
    for path in _submission_attempts(root, packet_id):
        try:
            submission = _load_submission(path)
        except MemoryLabError:
            continue
        if submission["status"] == "completed":
            valid.append((path, submission))
    return min(valid, key=lambda row: (row[1]["attempt"], str(row[0]))) if valid else None


def latest_submission(root: Path, packet_id: str) -> tuple[Path, dict[str, Any]] | None:
    valid: list[tuple[Path, dict[str, Any]]] = []
    for path in _submission_attempts(root, packet_id):
        try:
            valid.append((path, _load_submission(path)))
        except MemoryLabError:
            continue
    return max(valid, key=lambda row: (row[1]["attempt"], str(row[0]))) if valid else None


def _dependencies_ready(root: Path, packet: dict[str, Any]) -> bool:
    return all(selected_submission(root, dependency) is not None for dependency in packet["dependencies"])


def _claim_is_stale(path: Path, lease_seconds: float) -> bool:
    if not path.exists():
        return False
    try:
        claim = load_json(path)
        last = _parse_time(claim.get("heartbeat_at") or claim["claimed_at"])
    except Exception:
        last = path.stat().st_mtime
    return time.time() - last > lease_seconds


@contextmanager
def claim_packet(
    *,
    root: Path,
    packet: dict[str, Any],
    node_attestation: dict[str, Any],
    lease_seconds: float,
    heartbeat_seconds: float,
    reclaim_stale: bool,
) -> Iterator[dict[str, Any]]:
    claim_path = root / "claims" / f"{packet['packet_id']}.json"
    if claim_path.exists():
        try:
            existing_value = load_json(claim_path)
            existing = existing_value if isinstance(existing_value, dict) else None
        except MemoryLabError:
            existing = None
        reusable = bool(existing and existing.get("released_at"))
        reusable = reusable or (reclaim_stale and _claim_is_stale(claim_path, lease_seconds))
        if reusable:
            history = root / "claims" / "history"
            history.mkdir(parents=True, exist_ok=True)
            os.replace(
                claim_path,
                history / f"{packet['packet_id']}-{int(time.time())}-{time.time_ns()}.json",
            )
    claim = {
        "schema": CLAIM_SCHEMA,
        "flight_id": packet["flight_id"],
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["packet_sha256"],
        "node_id": packet["assigned_node_id"],
        "seat_id": packet["assigned_seat_id"],
        "node_attestation": node_attestation,
        "claimed_at": now_utc(),
        "heartbeat_at": now_utc(),
        "lease_seconds": lease_seconds,
        "process_id": os.getpid(),
    }
    claim["claim_sha256"] = hash_json(claim)
    if not _exclusive_json(claim_path, claim):
        raise MemoryLabError(f"packet is already claimed: {packet['packet_id']}")
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(heartbeat_seconds):
            claim["heartbeat_at"] = now_utc()
            claim["claim_sha256"] = hash_json(without_hash(claim, "claim_sha256"))
            _atomic_json(claim_path, claim)
            heartbeat = {
                "schema": HEARTBEAT_SCHEMA,
                "flight_id": packet["flight_id"],
                "packet_id": packet["packet_id"],
                "node_id": packet["assigned_node_id"],
                "seat_id": packet["assigned_seat_id"],
                "captured_at": claim["heartbeat_at"],
                "process_id": os.getpid(),
            }
            heartbeat["heartbeat_sha256"] = hash_json(heartbeat)
            _atomic_json(root / "heartbeats" / f"{packet['packet_id']}.json", heartbeat)

    thread = threading.Thread(target=beat, name=f"heartbeat-{packet['packet_id']}", daemon=True)
    thread.start()
    try:
        yield claim
    finally:
        stop.set()
        thread.join(timeout=max(heartbeat_seconds * 2, 1.0))
        claim["heartbeat_at"] = now_utc()
        claim["released_at"] = now_utc()
        claim["claim_sha256"] = hash_json(without_hash(claim, "claim_sha256"))
        _atomic_json(claim_path, claim)


def _next_attempt(root: Path, packet_id: str) -> int:
    values: list[int] = []
    for path in _submission_attempts(root, packet_id):
        try:
            values.append(int(path.name.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return max(values, default=0) + 1


def _publish_submission(
    *,
    root: Path,
    packet: dict[str, Any],
    attempt: int,
    status: str,
    node_attestation: dict[str, Any],
    files: list[tuple[Path, str]],
    receipt_identity: str | None,
) -> dict[str, Any]:
    destination = root / "submissions" / packet["packet_id"] / f"attempt-{attempt:03d}"
    if destination.exists():
        raise MemoryLabError(f"submission attempt already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    file_rows: list[dict[str, Any]] = []
    for source, name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + f".tmp-{os.getpid()}-{time.time_ns()}")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
        file_rows.append({"path": name, "bytes": target.stat().st_size, "sha256": hash_file(target)})
    submission: dict[str, Any] = {
        "schema": SUBMISSION_SCHEMA,
        "flight_id": packet["flight_id"],
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["packet_sha256"],
        "action": packet["action"],
        "status": status,
        "attempt": attempt,
        "node_id": packet["assigned_node_id"],
        "seat_id": packet["assigned_seat_id"],
        "trial_id": packet["trial_id"],
        "node_attestation": node_attestation,
        "receipt_identity": receipt_identity,
        "submitted_at": now_utc(),
        "files": sorted(file_rows, key=lambda row: row["path"]),
    }
    submission["submission_sha256"] = _submission_hash(submission)
    _atomic_json(destination / "submission.json", submission)
    return {"path": str(destination), **submission}


def _local_receipt_path(work_root: Path, receipt: dict[str, Any]) -> Path:
    candidates: list[Path] = []
    for path in work_root.rglob("receipt.json"):
        value = load_json(path)
        if isinstance(value, dict) and value.get("receipt_sha256") == receipt.get("receipt_sha256"):
            candidates.append(path)
    if len(candidates) != 1:
        raise MemoryLabError(
            f"could not resolve exactly one local receipt for {receipt.get('trial_id')}: {candidates}"
        )
    return candidates[0]


def execute_packet(
    *,
    root: Path,
    packet: dict[str, Any],
    work_root: Path,
    node_attestation: dict[str, Any],
    seat_resolution: dict[str, Any],
    force_cpu: bool,
    reclaim_stale: bool,
) -> dict[str, Any]:
    manifest, _, plan = load_flight(root)
    exchange = manifest["exchange"]
    if packet["assigned_node_id"] != node_attestation["node_id"]:
        raise MemoryLabError("worker node does not own this packet")
    if selected_submission(root, packet["packet_id"]) is not None:
        return {"packet_id": packet["packet_id"], "status": "skipped_completed"}
    if not _dependencies_ready(root, packet):
        return {"packet_id": packet["packet_id"], "status": "blocked_dependencies"}
    attempt = _next_attempt(root, packet["packet_id"])
    with claim_packet(
        root=root,
        packet=packet,
        node_attestation=node_attestation,
        lease_seconds=exchange["lease_seconds"],
        heartbeat_seconds=exchange["heartbeat_seconds"],
        reclaim_stale=reclaim_stale,
    ):
        from .conditional_memory_runner import execute_trial, verify_checkpoint

        source_trial = trial_by_id(plan, packet["trial_id"])
        local_root = work_root.resolve() / packet["flight_id"] / packet["packet_id"]
        local_root.mkdir(parents=True, exist_ok=True)
        if packet["action"] == "run_trial":
            receipt = execute_trial(
                plan=plan,
                trial=source_trial,
                state_dir=local_root,
                seat_resolution=seat_resolution,
                attempt=attempt,
                force_cpu=force_cpu,
            )
            receipt_path = _local_receipt_path(local_root, receipt)
            files: list[tuple[Path, str]] = [(receipt_path, "receipt.json")]
            checkpoint_value = (receipt.get("model") or {}).get("checkpoint_path")
            if checkpoint_value and exchange["copy_checkpoints"]:
                checkpoint = Path(checkpoint_value)
                if not checkpoint.exists():
                    raise MemoryLabError("completed receipt points to an absent checkpoint")
                files.append((checkpoint, "checkpoint.pt"))
            submission = _publish_submission(
                root=root,
                packet=packet,
                attempt=attempt,
                status="completed" if receipt["status"] == "completed" else "failed",
                node_attestation=node_attestation,
                files=files,
                receipt_identity=receipt["receipt_sha256"],
            )
            return {
                "packet_id": packet["packet_id"],
                "status": submission["status"],
                "attempt": attempt,
                "submission_sha256": submission["submission_sha256"],
            }
        if packet["action"] == "verify_checkpoint":
            source = selected_submission(root, packet["source_packet_id"])
            if source is None:
                return {"packet_id": packet["packet_id"], "status": "blocked_dependencies"}
            source_path, source_submission = source
            source_receipt = load_json(source_path / "receipt.json")
            checkpoint = source_path / "checkpoint.pt"
            verify_trial = dict(source_trial)
            verify_trial["node_id"] = packet["assigned_node_id"]
            verify_trial["seat"] = next(
                seat
                for seat in plan["resolved"]["topology"]["seats"]
                if seat["id"] == packet["assigned_seat_id"]
            )
            result_path = local_root / f"attempt-{attempt:03d}" / "cross-verification.json"
            verification = verify_checkpoint(
                plan=plan,
                trial=verify_trial,
                source_receipt=source_receipt,
                checkpoint_path=checkpoint,
                out=result_path,
                seat_resolution=seat_resolution,
                force_cpu=force_cpu,
                loss_tolerance=exchange["verification_loss_tolerance"],
                require_top_token_match=exchange["require_top_token_match"],
            )
            status = "completed" if verification["status"] == "completed" else "failed"
            submission = _publish_submission(
                root=root,
                packet=packet,
                attempt=attempt,
                status=status,
                node_attestation=node_attestation,
                files=[(result_path, "cross-verification.json")],
                receipt_identity=verification["verification_sha256"],
            )
            return {
                "packet_id": packet["packet_id"],
                "status": submission["status"],
                "attempt": attempt,
                "source_submission_sha256": source_submission["submission_sha256"],
                "submission_sha256": submission["submission_sha256"],
            }
        raise MemoryLabError(f"unsupported packet action {packet['action']}")


def run_exchange_seat(
    *,
    root: Path,
    node_id: str,
    seat_id: str,
    work_root: Path,
    force_cpu: bool = False,
    reclaim_stale: bool = False,
    max_wait_seconds: float = 86400.0,
) -> dict[str, Any]:
    manifest, _, plan = load_flight(root)
    if manifest["source_hashes"] != source_hashes():
        raise MemoryLabError("worker module source hashes differ from the published flight")
    node = node_by_id(plan, node_id)
    node_attestation = resolve_node_environment(node, allow_cpu_override=force_cpu)
    seat = next((value for value in seats_for_node(plan, node_id) if value["id"] == seat_id), None)
    if seat is None:
        raise MemoryLabError(f"node {node_id} has no seat {seat_id}")
    seat_resolution = resolve_seat_environment(seat, allow_cpu_override=force_cpu)
    seat_resolution["node"] = node_attestation
    node_attestation = {
        **node_attestation,
        "seat": {key: value for key, value in seat_resolution.items() if key != "node"},
    }
    packets = packets_for_seat(root, node_id, seat_id)
    started = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    while True:
        incomplete = [packet for packet in packets if selected_submission(root, packet["packet_id"]) is None]
        if not incomplete:
            break
        progress = False
        for packet in incomplete:
            if not _dependencies_ready(root, packet):
                continue
            result = execute_packet(
                root=root,
                packet=packet,
                work_root=work_root,
                node_attestation=node_attestation,
                seat_resolution=seat_resolution,
                force_cpu=force_cpu,
                reclaim_stale=reclaim_stale,
            )
            results[packet["packet_id"]] = result
            progress = progress or result["status"] != "blocked_dependencies"
            if result["status"] == "failed":
                return {
                    "ok": False,
                    "flight_id": manifest["flight_id"],
                    "node_id": node_id,
                    "seat_id": seat_id,
                    "results": list(results.values()),
                }
        if not progress:
            if time.monotonic() - started > max_wait_seconds:
                blocked = [packet["packet_id"] for packet in incomplete]
                raise MemoryLabError(
                    f"seat {seat_id} timed out waiting for packet dependencies: {blocked}"
                )
            time.sleep(manifest["exchange"]["poll_seconds"])
    return {
        "ok": True,
        "flight_id": manifest["flight_id"],
        "node_id": node_id,
        "seat_id": seat_id,
        "results": list(results.values()),
    }


def run_exchange_node(
    *,
    root: Path,
    node_id: str,
    work_root: Path,
    force_cpu: bool = False,
    reclaim_stale: bool = False,
    max_wait_seconds: float = 86400.0,
) -> dict[str, Any]:
    manifest, _, plan = load_flight(root)
    seats = seats_for_node(plan, node_id)
    processes: list[tuple[dict[str, Any], subprocess.Popen[str], Path, Path]] = []
    log_root = work_root.resolve() / manifest["flight_id"] / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    for seat in seats:
        stdout_path = log_root / f"{_slug(seat['id'])}.stdout.log"
        stderr_path = log_root / f"{_slug(seat['id'])}.stderr.log"
        argv = [
            sys.executable,
            "-m",
            "tier_runner.conditional_memory_cli",
            "exchange-run-seat",
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
        with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout, stderr_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as stderr:
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, text=True)
        processes.append((seat, process, stdout_path, stderr_path))
    rows: list[dict[str, Any]] = []
    for seat, process, stdout_path, stderr_path in processes:
        return_code = process.wait()
        rows.append(
            {
                "seat_id": seat["id"],
                "return_code": return_code,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            }
        )
    return {
        "ok": all(row["return_code"] == 0 for row in rows),
        "flight_id": manifest["flight_id"],
        "node_id": node_id,
        "seats": rows,
    }


def list_flights(exchange_root: Path) -> list[Path]:
    root = exchange_root.resolve() / "flights"
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if (path / "manifest.json").exists())


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
            try:
                manifest, _, _ = load_flight(root)
            except MemoryLabError as exc:
                processed.append({"flight_root": str(root), "status": "invalid", "error": str(exc)})
                continue
            assigned = [row for row in manifest["packets"] if row["assigned_node_id"] == node_id]
            if not assigned:
                continue
            pending = [row for row in assigned if selected_submission(root, row["packet_id"]) is None]
            if not pending:
                continue
            found = True
            result = run_exchange_node(
                root=root,
                node_id=node_id,
                work_root=work_root,
                force_cpu=force_cpu,
                reclaim_stale=reclaim_stale,
                max_wait_seconds=max_wait_seconds,
            )
            processed.append(result)
            if not result.get("ok"):
                return {"ok": False, "processed": processed}
        if once:
            break
        if not found:
            time.sleep(poll_seconds)
    return {"ok": all(row.get("ok", False) for row in processed), "processed": processed}


def exchange_status(root: Path) -> dict[str, Any]:
    manifest, _, _ = load_flight(root)
    rows: list[dict[str, Any]] = []
    counts = {"pending": 0, "claimed": 0, "submitted": 0, "failed": 0, "collected": 0}
    for packet_row in manifest["packets"]:
        packet_id = packet_row["packet_id"]
        selected = selected_submission(root, packet_id)
        latest = latest_submission(root, packet_id)
        collection_path = root / "collections" / f"{packet_id}.json"
        if collection_path.exists():
            state = "collected"
        elif selected is not None:
            state = "submitted"
        elif latest is not None and latest[1]["status"] != "completed":
            state = "failed"
        elif (root / "claims" / f"{packet_id}.json").exists():
            state = "claimed"
        else:
            state = "pending"
        counts[state] += 1
        rows.append({**packet_row, "state": state})
    result = {
        "schema": EXCHANGE_STATUS_SCHEMA,
        "flight_id": manifest["flight_id"],
        "plan_sha256": manifest["plan_sha256"],
        "counts": counts,
        "packets": rows,
    }
    result["status_sha256"] = hash_json(result)
    return result


def _verify_cross_verification(
    verification: dict[str, Any], packet: dict[str, Any], plan: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if verification.get("schema") != CROSS_VERIFY_SCHEMA:
        errors.append(f"cross verification schema must be {CROSS_VERIFY_SCHEMA}")
    if verification.get("verification_sha256") != hash_json(
        without_hash(verification, "verification_sha256")
    ):
        errors.append("cross verification hash does not verify")
    if verification.get("plan_sha256") != plan["plan_sha256"]:
        errors.append("cross verification belongs to another plan")
    if verification.get("trial_id") != packet["trial_id"]:
        errors.append("cross verification belongs to another trial")
    if verification.get("verification_seat", {}).get("id") != packet["assigned_seat_id"]:
        errors.append("cross verification ran on the wrong seat")
    if verification.get("status") != "completed" or not verification.get("comparison", {}).get("pass"):
        errors.append("cross verification did not pass")
    return errors


def collect_flight(
    *,
    root: Path,
    coordinator_state: Path,
    coordinator_attestation: dict[str, Any],
) -> dict[str, Any]:
    manifest, raw_lab, plan = load_flight(root)
    if coordinator_attestation.get("node_id") != manifest["coordinator_node_id"]:
        raise MemoryLabError("collector is not the declared coordinator node")
    if manifest["source_hashes"] != source_hashes():
        raise MemoryLabError("collector module source hashes differ from the published flight")
    imported_root = coordinator_state.resolve() / manifest["flight_id"]
    imported_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(imported_root / "lab.json", raw_lab)
    _atomic_json(imported_root / "plan.json", plan)
    collections: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in manifest["packets"]:
        packet_id = row["packet_id"]
        packet = packet_by_id(root, packet_id)
        selected = selected_submission(root, packet_id)
        if selected is None:
            errors.append({"packet_id": packet_id, "error": "no completed submission"})
            continue
        submission_path, submission = selected
        if submission["packet_sha256"] != packet["packet_sha256"]:
            errors.append({"packet_id": packet_id, "error": "submission packet hash mismatch"})
            continue
        collection_path = root / "collections" / f"{packet_id}.json"
        if collection_path.exists():
            try:
                existing = load_json(collection_path)
                if existing.get("schema") != COLLECTION_SCHEMA:
                    raise MemoryLabError("existing collection schema is invalid")
                if existing.get("collection_sha256") != _collection_hash(existing):
                    raise MemoryLabError("existing collection hash does not verify")
                if existing.get("submission_sha256") != submission["submission_sha256"]:
                    raise MemoryLabError("existing collection references another submission")
                collections.append(existing)
                continue
            except MemoryLabError as exc:
                errors.append({"packet_id": packet_id, "error": str(exc)})
                continue
        destination = imported_root / _slug(packet["trial_id"]) / packet["action"]
        destination.mkdir(parents=True, exist_ok=True)
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
                        next(file["sha256"] for file in submission["files"] if file["path"] == "receipt.json"),
                    )
                )
                checkpoint_rows = [file for file in submission["files"] if file["path"] == "checkpoint.pt"]
                if checkpoint_rows:
                    imported_files.append(
                        _copy_verified(
                            submission_path / "checkpoint.pt",
                            destination / "checkpoint.pt",
                            checkpoint_rows[0]["sha256"],
                        )
                    )
            else:
                verification = load_json(submission_path / "cross-verification.json")
                verification_errors = _verify_cross_verification(verification, packet, plan)
                if verification_errors:
                    raise MemoryLabError("; ".join(verification_errors))
                imported_files.append(
                    _copy_verified(
                        submission_path / "cross-verification.json",
                        destination / "cross-verification.json",
                        next(
                            file["sha256"]
                            for file in submission["files"]
                            if file["path"] == "cross-verification.json"
                        ),
                    )
                )
            collection: dict[str, Any] = {
                "schema": COLLECTION_SCHEMA,
                "flight_id": manifest["flight_id"],
                "packet_id": packet_id,
                "packet_sha256": packet["packet_sha256"],
                "submission_sha256": submission["submission_sha256"],
                "action": packet["action"],
                "trial_id": packet["trial_id"],
                "coordinator_attestation": coordinator_attestation,
                "collected_at": now_utc(),
                "destination": str(destination),
                "files": imported_files,
            }
            collection["collection_sha256"] = _collection_hash(collection)
            _atomic_json(collection_path, collection)
            _atomic_json(destination / "collection.json", collection)
            collections.append(collection)
        except MemoryLabError as exc:
            errors.append({"packet_id": packet_id, "error": str(exc)})
    report = build_report(plan, imported_root)
    _atomic_json(imported_root / "report.json", report)
    _atomic_json(root / "coordinator" / "report.json", report)
    summary = {
        "ok": not errors and report["status"]["ok"],
        "flight_id": manifest["flight_id"],
        "plan_sha256": plan["plan_sha256"],
        "coordinator_state": str(imported_root),
        "collections": len(collections),
        "errors": errors,
        "report_sha256": report["report_sha256"],
        "promotable_arms": report["promotable_arms"],
        "promotion_authorized": False,
    }
    _atomic_json(root / "coordinator" / "collection-summary.json", summary)
    return summary
