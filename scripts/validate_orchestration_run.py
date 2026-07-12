#!/usr/bin/env python3
"""Validate ARC-C orchestration run plans and sealed trial receipts.

This validator is deliberately stronger than the JSON schema.  It verifies
hashes, hidden-grader declarations, independent grading, floor-first routing,
replay evidence, cost basis, recorded broker decisions, and closure discipline.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from experiments.breadth.residue_broker import decisions_for_run, route_was_allowed  # noqa: E402

COST_BASES = {
    "real-billed", "shadow-estimated", "subscription-derived",
    "repaired-transport-adjudicated",
}
RUN_STATUSES = {"unmeasured", "running", "partial", "sealed"}
BURDEN_REQUIRED = (
    "requested_outcome", "claimant", "authority", "predicates", "burden_holder",
    "evidence", "verifier", "gap", "closure_decision", "failure_default",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _repo_file(rel, repo: Path, label: str, errors: list[str]) -> Path | None:
    if not _nonempty(rel):
        errors.append(f"{label} must be a non-empty repo-relative path")
        return None
    path = (repo / rel).resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError:
        errors.append(f"{label} escapes the repository: {rel}")
        return None
    if not path.is_file():
        errors.append(f"{label} does not exist: {rel}")
        return None
    return path


def _check_hash(value, path: Path | None, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        errors.append(f"{label} must be a lowercase SHA-256 hex digest")
    elif path is not None and sha256(path) != value:
        errors.append(f"{label} does not match {path.name}")


def _git_blob(repo: Path, commit: str, relpath: str, label: str,
              errors: list[str]) -> bytes | None:
    """Read exact committed bytes; never substitute the current checkout."""
    if not _nonempty(relpath):
        errors.append(f"{label} must be a non-empty repo-relative path")
        return None
    path = Path(relpath)
    if path.is_absolute() or ".." in path.parts or "\\" in relpath:
        errors.append(f"{label} must be a canonical repo-relative POSIX path")
        return None
    try:
        return subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{relpath}"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        errors.append(f"{label} does not exist at pinned source commit {commit}")
        return None


def _check_hash_bytes(value, data: bytes | None, label: str,
                      errors: list[str]) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        errors.append(f"{label} must be a lowercase SHA-256 hex digest")
    elif data is not None and hashlib.sha256(data).hexdigest() != value:
        errors.append(f"{label} does not match bytes at pairing.source_commit")


def _manifest_info(run: dict, repo: Path, errors: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    source_commit = (run.get("pairing") or {}).get("source_commit", "")
    manifests = run.get("task_manifests")
    if not isinstance(manifests, list):
        errors.append("task_manifests must be a list")
        return result
    for i, item in enumerate(manifests):
        if not isinstance(item, dict):
            errors.append(f"task_manifests[{i}] must be an object")
            continue
        tid = item.get("task_id")
        relpath = item.get("path")
        blob = _git_blob(repo, source_commit, relpath,
                         f"task_manifests[{i}].path", errors)
        _check_hash_bytes(item.get("sha256"), blob,
                          f"task_manifests[{i}].sha256", errors)
        if not _nonempty(tid) or tid in result:
            errors.append(f"task_manifests[{i}].task_id must be non-empty and unique")
            continue
        if blob is not None:
            try:
                manifest = json.loads(blob.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"task manifest {relpath} at {source_commit}: {exc}")
                continue
            if manifest.get("task_id") != tid:
                errors.append(
                    f"task manifest {relpath} declares {manifest.get('task_id')!r}, "
                    f"expected {tid!r}"
                )
            if not manifest.get("hidden_files") or not manifest.get("hidden_run_command"):
                errors.append(f"task {tid}: ARC-C admits hidden-graded manifests only")
            if not relpath.startswith("tasks/almanac_"):
                errors.append(f"task {tid}: ARC-C v1 admits the real almanac knot corpus only")
            result[tid] = {"path": repo / relpath, "manifest": manifest}
    return result


def _check_burden(run: dict, errors: list[str]) -> None:
    burden = run.get("burden")
    if not isinstance(burden, dict):
        errors.append("burden must be an object")
        return
    for key in BURDEN_REQUIRED:
        value = burden.get(key)
        if key in {"predicates", "evidence"}:
            if not isinstance(value, list) or not value or not all(_nonempty(x) for x in value):
                errors.append(f"burden.{key} must be a non-empty list of strings")
        elif not _nonempty(value):
            errors.append(f"burden.{key} must be a non-empty string")


def _check_engine_pairing(run: dict, errors: list[str]) -> None:
    engine = run.get("engine")
    pairing = run.get("pairing")
    if not isinstance(engine, dict):
        errors.append("engine must be an object")
        engine = {}
    for key in ("engine_id", "model", "lineage", "surface", "role"):
        if not _nonempty(engine.get(key)):
            errors.append(f"engine.{key} must be a non-empty string")
    if not isinstance(pairing, dict):
        errors.append("pairing must be an object")
        pairing = {}
    for key in ("pair_id", "peer_engine_id", "peer_lineage", "state"):
        if not _nonempty(pairing.get(key)):
            errors.append(f"pairing.{key} must be a non-empty string")
    if pairing.get("peer_engine_id") == engine.get("engine_id"):
        errors.append("paired engines must have different engine_id values")
    if pairing.get("peer_lineage") == engine.get("lineage"):
        errors.append("paired engines must come from different provider lineages")
    if not isinstance(pairing.get("source_commit"), str) or not HEX40.fullmatch(pairing["source_commit"]):
        errors.append("pairing.source_commit must be a 40-character lowercase commit SHA")
    if pairing.get("independent_before_exchange") is not True:
        errors.append("pairing.independent_before_exchange must be true; otherwise the run is contaminated")
    if pairing.get("state") not in {
        "planned", "independent_run_sealed", "pair_sealed", "contaminated", "incomparable"
    }:
        errors.append(f"invalid pairing.state {pairing.get('state')!r}")


def _check_trial(run: dict, trial: dict, manifests: dict[str, dict], repo: Path,
                 errors: list[str]) -> None:
    label = f"trial {trial.get('trial_id', '<missing>')}"
    for key in ("trial_id", "task_id", "rung", "model", "effort", "solver_id"):
        if not _nonempty(trial.get(key)):
            errors.append(f"{label}: {key} must be a non-empty string")
    if not isinstance(trial.get("sequence"), int) or isinstance(trial.get("sequence"), bool) or trial.get("sequence", -1) < 1:
        errors.append(f"{label}: sequence must be a positive integer")
    if not isinstance(trial.get("trial"), int) or isinstance(trial.get("trial"), bool) or trial.get("trial", -1) < 1:
        errors.append(f"{label}: trial must be a positive integer")
    if trial.get("task_id") not in manifests:
        errors.append(f"{label}: task_id is not in the sealed task set")
    if trial.get("rung") not in run.get("rungs", []):
        errors.append(f"{label}: rung is not in the declared ladder")
    binding = run.get("rung_bindings", {}).get(trial.get("rung"), {})
    if isinstance(binding, dict):
        for field, trial_field in (("model", "model"), ("effort", "effort"),
                                   ("surface", "executor_surface")):
            if binding.get(field) != trial.get(trial_field):
                errors.append(f"{label}: {trial_field} does not match rung_bindings[{trial.get('rung')!r}].{field}")

    route = trial.get("route")
    if not isinstance(route, dict) or route.get("selected_by") != "residue_broker":
        errors.append(f"{label}: route.selected_by must be residue_broker")
    if isinstance(trial.get("sequence"), int) and trial.get("task_id") in manifests and trial.get("rung") in run.get("rungs", []):
        allowed, decision = route_was_allowed(run, trial)
        if not allowed:
            errors.append(
                f"{label}: route to {trial.get('rung')} was not earned; broker action before dispatch "
                f"was {decision['action']} -> {decision.get('route_to')} ({decision['state']})"
            )
        if isinstance(route, dict):
            expected_route = {
                "selected_by": "residue_broker",
                "action": decision["action"],
                "decision_state": decision["state"],
                "reason": decision["reason"],
                "escalation_from": decision["escalation_from"],
                "evidence": decision["evidence"],
            }
            if route != expected_route:
                errors.append(f"{label}: route does not preserve the broker decision available before dispatch")

    verdict = trial.get("verdict")
    if not isinstance(verdict, dict):
        errors.append(f"{label}: verdict must be an object")
        return
    outcome = verdict.get("outcome")
    if outcome not in {"pass", "fail", "partial", "error"}:
        errors.append(f"{label}: invalid verdict.outcome {outcome!r}")
    decisive = outcome in {"pass", "fail"}
    abstention = trial.get("abstention")
    if not isinstance(abstention, dict) or not isinstance(abstention.get("abstained"), bool):
        errors.append(f"{label}: abstention.abstained must be boolean")
    elif not decisive and not abstention["abstained"]:
        errors.append(f"{label}: partial/error observations must abstain from a capability verdict")
    elif decisive and abstention["abstained"]:
        errors.append(f"{label}: pass/fail receipts may not simultaneously claim abstention")

    provenance = trial.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(f"{label}: provenance must be an object")
        provenance = {}
    if provenance.get("hidden_grader_visible_to_solver") is not False:
        errors.append(f"{label}: hidden_grader_visible_to_solver must be false")
    _check_hash(provenance.get("solver_packet_sha256"), None,
                f"{label}: provenance.solver_packet_sha256", errors)
    _check_hash(provenance.get("prompt_sha256"), None,
                f"{label}: provenance.prompt_sha256", errors)
    if not _nonempty(provenance.get("solver_thread_id")):
        errors.append(f"{label}: provenance.solver_thread_id must preserve the raw exchange identity")
    raw_path = _repo_file(provenance.get("raw_response_path"), repo,
                          f"{label}: provenance.raw_response_path", errors)
    _check_hash(provenance.get("raw_response_sha256"), raw_path,
                f"{label}: provenance.raw_response_sha256", errors)
    if "event_stream_path" in provenance or "event_stream_sha256" in provenance:
        event_path = _repo_file(provenance.get("event_stream_path"), repo,
                                f"{label}: provenance.event_stream_path", errors)
        _check_hash(provenance.get("event_stream_sha256"), event_path,
                    f"{label}: provenance.event_stream_sha256", errors)
    capture_kind = provenance.get("event_stream_capture_kind")
    if capture_kind is not None and capture_kind not in {
            "provider-raw-jsonl", "coordinator-derived-codex-app-thread-snapshot"}:
        errors.append(f"{label}: invalid provenance.event_stream_capture_kind")

    spend = trial.get("spend")
    if not isinstance(spend, dict):
        errors.append(f"{label}: spend must be an object")
    else:
        cost = spend.get("cost_usd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
            errors.append(f"{label}: spend.cost_usd must be a non-negative number")
        if spend.get("cost_basis") not in COST_BASES:
            errors.append(f"{label}: invalid spend.cost_basis")
        for token_key in ("input_tokens", "output_tokens"):
            value = spend.get(token_key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{label}: spend.{token_key} must be a non-negative integer")
        usage_available = spend.get("usage_available")
        if usage_available is not None and not isinstance(usage_available, bool):
            errors.append(f"{label}: spend.usage_available must be boolean")
        if usage_available is False:
            if any(spend.get(key) != 0 for key in (
                    "input_tokens", "output_tokens", "cache_read_tokens",
                    "reasoning_output_tokens")):
                errors.append(f"{label}: unavailable usage requires zero token sentinels")
            if not _nonempty(spend.get("usage_note")):
                errors.append(f"{label}: unavailable usage requires spend.usage_note")
        if trial.get("executor_surface") == "codex-subscription" and spend.get("cost_basis") != "subscription-derived":
            errors.append(f"{label}: Codex subscription trials require cost_basis subscription-derived")

    replay = trial.get("replay")
    if not isinstance(replay, dict) or not isinstance(replay.get("is_replay"), bool):
        errors.append(f"{label}: replay.is_replay must be boolean")
    elif replay["is_replay"]:
        if not _nonempty(replay.get("source_capture_id")) or not _nonempty(replay.get("distinct_work_item_id")):
            errors.append(f"{label}: replay receipts require source_capture_id and distinct_work_item_id")
        _repo_file(replay.get("artifact_path"), repo, f"{label}: replay.artifact_path", errors)

    if decisive:
        candidate = trial.get("candidate")
        if not isinstance(candidate, dict):
            errors.append(f"{label}: decisive verdict requires a sealed candidate")
            candidate = {}
        candidate_path = _repo_file(candidate.get("path"), repo, f"{label}: candidate.path", errors)
        _check_hash(candidate.get("sha256"), candidate_path, f"{label}: candidate.sha256", errors)
        if candidate.get("sealed_before_grading") is not True:
            errors.append(f"{label}: candidate must be sealed before grading")
        if verdict.get("candidate_sha256") != candidate.get("sha256"):
            errors.append(f"{label}: verdict candidate hash does not match the sealed candidate")
        if verdict.get("source") != "coordinator_rerun" or verdict.get("rerun_verified") is not True:
            errors.append(f"{label}: decisive verdict must come from a coordinator rerun")
        if not _nonempty(verdict.get("graded_by")) or verdict.get("graded_by") == trial.get("solver_id"):
            errors.append(f"{label}: the solver may not award its own verdict")

        hidden_path = _repo_file(verdict.get("hidden_grader_path"), repo,
                                 f"{label}: verdict.hidden_grader_path", errors)
        _check_hash(verdict.get("hidden_grader_sha256"), hidden_path,
                    f"{label}: verdict.hidden_grader_sha256", errors)
        output_path = _repo_file(verdict.get("grader_output_path"), repo,
                                 f"{label}: verdict.grader_output_path", errors)
        _check_hash(verdict.get("grader_output_sha256"), output_path,
                    f"{label}: verdict.grader_output_sha256", errors)
        info = manifests.get(trial.get("task_id"))
        if info and hidden_path:
            fixture = Path(info["manifest"]["fixture_dir"])
            declared = {(repo / fixture / name).resolve() for name in info["manifest"].get("hidden_files", [])}
            if hidden_path.resolve() not in declared:
                errors.append(f"{label}: grader path is not declared hidden by the task manifest")


def validate_run(run: dict, repo: Path = REPO) -> list[str]:
    errors: list[str] = []
    for key in ("schema_version", "run_id", "status", "measurement_claim", "engine", "pairing",
                "task_set", "task_manifests", "rungs", "rung_bindings", "k", "trials",
                "decisions", "burden"):
        if key not in run:
            errors.append(f"missing required field {key!r}")
    if run.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    if not _nonempty(run.get("run_id")):
        errors.append("run_id must be a non-empty string")
    if run.get("status") not in RUN_STATUSES:
        errors.append(f"invalid status {run.get('status')!r}")
    if not isinstance(run.get("measurement_claim"), bool):
        errors.append("measurement_claim must be boolean")
    _check_engine_pairing(run, errors)
    rungs = run.get("rungs")
    if not isinstance(rungs, list) or not rungs or not all(_nonempty(x) for x in rungs) or len(set(rungs or [])) != len(rungs or []):
        errors.append("rungs must be a non-empty unique list of strings")
    bindings = run.get("rung_bindings")
    if not isinstance(bindings, dict):
        errors.append("rung_bindings must be an object")
    elif isinstance(rungs, list):
        if set(bindings) != set(rungs):
            errors.append("rung_bindings keys must exactly match rungs")
        for rung, binding in bindings.items():
            if not isinstance(binding, dict) or not all(_nonempty(binding.get(k)) for k in ("model", "effort", "surface")):
                errors.append(f"rung_bindings[{rung!r}] must name model, effort and surface")
    if not isinstance(run.get("k"), int) or isinstance(run.get("k"), bool) or run.get("k", 0) < 1:
        errors.append("k must be a positive integer")
    task_set = run.get("task_set")
    if not isinstance(task_set, list) or not task_set or not all(_nonempty(x) for x in task_set) or len(set(task_set or [])) != len(task_set or []):
        errors.append("task_set must be a non-empty unique list of strings")

    manifests = _manifest_info(run, repo, errors)
    if isinstance(task_set, list) and set(task_set) != set(manifests):
        errors.append("task_set must exactly match task_manifests")
    _check_burden(run, errors)

    trials = run.get("trials")
    if not isinstance(trials, list):
        errors.append("trials must be a list")
        trials = []
    ids, coordinates, sequences, replay_items = set(), set(), set(), set()
    for item in trials:
        if not isinstance(item, dict):
            errors.append("every trial must be an object")
            continue
        tid = item.get("trial_id")
        coord = (item.get("task_id"), item.get("rung"), item.get("trial"))
        seq = item.get("sequence")
        if tid in ids:
            errors.append(f"duplicate trial_id {tid!r}")
        if coord in coordinates:
            errors.append(f"duplicate trial coordinate {coord!r}")
        if seq in sequences:
            errors.append(f"duplicate sequence {seq!r}")
        ids.add(tid); coordinates.add(coord); sequences.add(seq)
        replay = item.get("replay")
        if isinstance(replay, dict) and replay.get("is_replay") is True:
            distinct = replay.get("distinct_work_item_id")
            if distinct in replay_items:
                errors.append(f"duplicate replay distinct_work_item_id {distinct!r}")
            replay_items.add(distinct)
        _check_trial(run, item, manifests, repo, errors)

    if isinstance(rungs, list) and rungs and isinstance(task_set, list) and task_set and isinstance(run.get("k"), int) and run["k"] > 0:
        expected = decisions_for_run(run)
        if run.get("decisions") != expected:
            errors.append("decisions do not match the deterministic residue broker output")

    decisive = sum(
        1 for t in trials if isinstance(t, dict) and t.get("verdict", {}).get("outcome") in {"pass", "fail"}
    )
    if run.get("status") == "unmeasured":
        if decisive:
            errors.append("unmeasured run may not contain decisive trial receipts")
        if run.get("measurement_claim") is not False:
            errors.append("unmeasured run must set measurement_claim=false")
        if run.get("pairing", {}).get("state") != "planned":
            errors.append("unmeasured run must keep pairing.state=planned")
    if run.get("measurement_claim") is True and run.get("status") != "sealed":
        errors.append("measurement_claim=true requires status=sealed")
    if run.get("status") == "sealed" and run.get("measurement_claim") is not True:
        errors.append("sealed run must explicitly set measurement_claim=true")
    if run.get("status") == "sealed" and any(
        d.get("action") in {"route", "collect_more", "escalate"}
        for d in run.get("decisions", []) if isinstance(d, dict)
    ):
        errors.append("sealed run still has tasks requiring dispatch or more evidence")
    closure = run.get("burden", {}).get("closure_decision") if isinstance(run.get("burden"), dict) else None
    if closure not in {"open", "partial", "sealed"}:
        errors.append(f"invalid burden.closure_decision {closure!r}")
    if closure == "sealed" and run.get("status") != "sealed":
        errors.append("burden cannot claim sealed while run status is non-closed")
    if run.get("status") == "sealed" and closure != "sealed":
        errors.append("sealed run requires burden.closure_decision=sealed")
    if run.get("status") == "sealed" and run.get("pairing", {}).get("state") not in {
        "independent_run_sealed", "pair_sealed"
    }:
        errors.append("sealed run requires pairing.state=independent_run_sealed or pair_sealed")
    return errors


def validate_file(path: Path, repo: Path = REPO) -> list[str]:
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: {exc}"]
    return validate_run(run, repo)


def main() -> int:
    files = [Path(arg) for arg in sys.argv[1:]] or sorted((REPO / "data/orchestration").glob("*.json"))
    if not files:
        print("UNMEASURED — no ARC-C run plans or receipts exist")
        return 0
    failures: list[str] = []
    for path in files:
        errors = validate_file(path)
        failures.extend(f"{path.name}: {error}" for error in errors)
    if failures:
        print(f"FAIL — {len(failures)} orchestration problem(s):", file=sys.stderr)
        for error in failures:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"OK — {len(files)} ARC-C run file(s) satisfy floor-first routing, independent hidden grading, provenance, spend, replay, abstention, and closure rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
