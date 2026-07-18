"""Model-free guards distilled from LESSONS.md rule 13: smoke before cage.

Three executable clauses, each pinned to a failure that actually happened:

1. The Spark execution surface fail-closes on sandbox drift — the exact
   Sol-root v0.3 bite (requested workspace-write, router enforced read-only,
   discovered only after the 59-call freeze was ratified).
2. Any NEW freeze artifact must bind a prior disposable smoke receipt proving
   the run-only-provable properties (sandbox writes, transport liveness,
   output-schema acceptance). Historical artifacts are grandfathered by exact
   content hash — never by path — so editing a fossil breaks the guard.
3. Any execution closure receipt must classify infra-vs-observation, so a
   no-retry stopping rule can never silently absorb an infrastructure failure
   (the ARC-D buffalo 3/3 systemError lock-in).

Zero provider calls, zero scientific observations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"

# Freeze artifacts that predate rule 13, pinned by exact content hash. A hash
# mismatch means someone edited a sealed fossil instead of authoring a new,
# smoke-bound freeze — that is a failure, not a reason to update this table.
GRANDFATHERED_FREEZES = {
    "luna_sol_anchor_replication_v2/CLI_SURFACE_V2_2_2_FREEZE.json": "6fe07562101628530abf5c9598057eb7de3858c8d481a8d13b412e578db98ab1",
    "luna_sol_anchor_replication_v2/SPARK_EXECUTION_SURFACE_V2_2_3_FREEZE.json": "284a3f0aa0f468378d7f804cdabd9be1105ce2f460407a29e11e00699af9f3e1",
    "sol_root_matched_config/activation_v0_3/freeze_candidate.json": "754f8142c3398d626e7972901374e89a35508e082c88578747ddadd90793f568",
}

# The properties that can ONLY be proven by running, per rule 13.
REQUIRED_SMOKE_CHECKS = (
    "sandbox_write_proven",
    "transport_liveness_proven",
    "output_schema_accepted",
)


def _load_run_v2():
    path = EXPERIMENTS / "luna_sol_anchor_replication_v2" / "run_v2.py"
    spec = importlib.util.spec_from_file_location("sol_root_run_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _refusal(callback, code: str, errors) -> None:
    try:
        callback()
    except errors as exc:
        detail = getattr(exc, "code", None) or str(exc)
        assert code in str(detail), f"expected refusal {code!r}, got {detail!r}"
        return
    raise AssertionError(f"expected refusal {code!r}, call was accepted")


def _freeze_files():
    for path in sorted(EXPERIMENTS.rglob("*freeze*.json")):
        if "run" in path.relative_to(EXPERIMENTS).parts:
            continue  # sealed run evidence is immutable history, not a cage
        yield path


def _closure_files():
    for path in sorted(EXPERIMENTS.rglob("*execution_closure_receipt*.json")):
        if "run" in path.relative_to(EXPERIMENTS).parts:
            continue
        yield path


def test_execution_surface_fail_closes_on_sandbox_drift() -> int:
    run_v2 = _load_run_v2()
    checks = 0
    cwd, final = Path("."), Path("final.json")

    command = run_v2.spark_execution_command(cwd, final)
    index = command.index("--sandbox")
    assert command[index + 1] == "workspace-write"
    checks += 1

    # A read-only Spark execution command must be unconstructable: the v0.3
    # executor died writing files under an enforced read-only sandbox.
    _refusal(lambda: run_v2.spark_execution_command(cwd, final, sandbox="read-only"), "unsupported", (ValueError,))
    checks += 1

    run_v2.require_spark_execution_surface(command)
    checks += 1

    escalated = run_v2.spark_execution_command(cwd, final, sandbox="danger-full-access")
    _refusal(lambda: run_v2.require_spark_execution_surface(escalated), "SPARK_WRITABLE_SURFACE_REQUIRED", (run_v2.ControllerError,))
    run_v2.require_spark_execution_surface(escalated, allow_isolated_repo_full_access=True)
    checks += 1

    stripped = [item for item in command if item != "--sandbox" and item != "workspace-write"]
    _refusal(lambda: run_v2.require_spark_execution_surface(stripped), "SPARK_SANDBOX_MISSING", (run_v2.ControllerError,))
    checks += 1

    _refusal(lambda: run_v2.require_spark_execution_surface(command + ["--ignore-user-config"]), "SPARK_APP_SURFACE_STRIPPED", (run_v2.ControllerError,))
    _refusal(lambda: run_v2.require_spark_execution_surface(command + ["--output-schema"]), "SPARK_OUTPUT_SCHEMA_FORBIDDEN", (run_v2.ControllerError,))
    checks += 1

    return checks


def test_new_freezes_bind_a_smoke_receipt() -> int:
    checks = 0
    for path in _freeze_files():
        relative = path.relative_to(EXPERIMENTS).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pinned = GRANDFATHERED_FREEZES.get(relative)
        if pinned is not None:
            assert digest == pinned, (
                f"{relative}: grandfathered freeze bytes changed ({digest}); "
                "sealed fossils are immutable — author a new smoke-bound freeze instead"
            )
            checks += 1
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        smoke = document.get("smoke_receipt")
        assert isinstance(smoke, dict), (
            f"{relative}: freeze artifact has no bound smoke_receipt. LESSONS.md rule 13: "
            "burn 1-2 disposable calls proving the runtime path BEFORE building the cage"
        )
        assert isinstance(smoke.get("sha256"), str) and len(smoke["sha256"]) == 64, f"{relative}: smoke_receipt.sha256 must pin the receipt bytes"
        received = smoke.get("checks") or {}
        for name in REQUIRED_SMOKE_CHECKS:
            assert received.get(name) is True, f"{relative}: smoke_receipt.checks.{name} must be proven true before the freeze"
        checks += 1
    assert checks > 0, "freeze scan found nothing — glob or layout drifted; fix the scan, do not delete the guard"
    return checks


def test_closure_receipts_classify_infra_vs_observation() -> int:
    checks = 0
    for path in _closure_files():
        relative = path.relative_to(EXPERIMENTS).as_posix()
        document = json.loads(path.read_text(encoding="utf-8"))
        finding = document.get("finding") or {}
        classification = finding.get("classification")
        assert isinstance(classification, str) and classification, (
            f"{relative}: execution closure must classify the failure "
            "(infrastructure vs model/observation) so no-retry rules cannot absorb infra failures"
        )
        assert isinstance(finding.get("scientific_schedule_admissible"), bool), f"{relative}: finding.scientific_schedule_admissible must be an explicit boolean"
        checks += 1
    assert checks > 0, "closure scan found nothing — glob or layout drifted; fix the scan, do not delete the guard"
    return checks


def main() -> int:
    checks = 0
    checks += test_execution_surface_fail_closes_on_sandbox_drift()
    checks += test_new_freezes_bind_a_smoke_receipt()
    checks += test_closure_receipts_classify_infra_vs_observation()
    print(f"OK - {checks} smoke-before-cage guards; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
