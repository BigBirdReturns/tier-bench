"""Regressions for the exact Sol-root administrative execution closure."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ACTIVATION = ROOT / "experiments" / "sol_root_matched_config" / "activation_v0_3"
sys.path.insert(0, str(ACTIVATION))

from verify_activation_run_v0_3 import EVIDENCE_FILES, RUN, RunEvidenceError, build_receipt  # noqa: E402


def main() -> int:
    receipt = build_receipt()
    assert receipt["status"] == "scientific_schedule_inadmissible_sandbox_invocation_non_equivalence"
    assert receipt["calls"] == {"provider_calls_completed": 2, "owner_accepted": 1, "executor_attempted": 1, "executor_accepted": 0, "not_run": 57, "retries": 0}
    assert receipt["usage"]["total"] == {"input_tokens": 28785, "cached_input_tokens": 8960, "output_tokens": 204, "reasoning_output_tokens": 101}
    assert receipt["finding"]["scientific_schedule_admissible"] is False
    checks = 1

    with tempfile.TemporaryDirectory(prefix="sol-root-run-v03-") as temp:
        copied = Path(temp) / "run"
        for relative in EVIDENCE_FILES:
            destination = copied / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RUN / relative, destination)
        stderr = copied / "c01/stderr.txt"
        stderr.write_text(stderr.read_text(encoding="utf-8").replace("read-only sandbox", "workspace-write sandbox"), encoding="utf-8")
        try:
            build_receipt(copied)
        except RunEvidenceError:
            pass
        else:
            raise AssertionError("tampered sandbox evidence was accepted")
    checks += 1

    print(f"OK - {checks} activation-run closure checks; zero provider calls during verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
