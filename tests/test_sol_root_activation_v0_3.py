"""Model-free tests for the Sol-root activation v0.3 freeze and runner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ACTIVATION = ROOT / "experiments" / "sol_root_matched_config" / "activation_v0_3"
sys.path.insert(0, str(ACTIVATION))

from build_activation_v0_3 import ActivationError, OWNER_CELL, build, canonical, receipt  # noqa: E402
from runner import call_directory_name, command_for, freeze_sha256, validate_authorization, validate_result  # noqa: E402


def refusal(callback) -> None:
    try:
        callback()
    except ActivationError:
        return
    raise AssertionError("expected ActivationError")


def git(*args: str, cwd: Path) -> None:
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def main() -> int:
    freeze = build()
    schedule = freeze["schedule"]
    assert len(schedule) == 59
    assert schedule[0]["cell_id"] == OWNER_CELL and schedule[0]["role"] == "owner"
    assert len({item["cell_id"] for item in schedule[1:]}) == 58
    assert all(item["role"] == "executor" for item in schedule[1:])
    assert all(item["service_tier_config"] == ("default" if item["catalog_tier"] == "standard" else "priority") for item in schedule)
    output_schema = json.loads((ACTIVATION / "final_schema.json").read_text(encoding="utf-8"))
    assert output_schema["properties"]["status"] == {"const": "ready", "type": "string"}
    assert receipt(freeze)["all_pass"] is True
    assert call_directory_name(0) == "c00" and call_directory_name(58) == "c58"
    assert len(str(Path("D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2/experiments/sol_root_matched_config/run/activation_v0_3") / ("0" * 64) / call_directory_name(58) / "subject" / ".git" / "hooks" / "applypatch-msg.sample")) < 248
    checks = 1

    digest = freeze_sha256(freeze)
    authorization = {
        "schema": "tier-bench/sol-root-activation/operator-authorization@0.3",
        "freeze_sha256": digest,
        "authorized_call_ceiling": 59,
        "no_retries": True,
        "prospective": True,
        "authorized_by": "test fixture",
        "authorized_at_utc": "2026-07-17T00:00:00Z",
    }
    assert validate_authorization(freeze, authorization) == digest
    wrong = dict(authorization, freeze_sha256="0" * 64)
    refusal(lambda: validate_authorization(freeze, wrong))
    refusal(lambda: validate_authorization(freeze, dict(authorization, no_retries=False)))
    checks += 1

    with tempfile.TemporaryDirectory(prefix="sol-root-activation-") as temp:
        temp_path = Path(temp)
        final_path = temp_path / "final.json"
        command = command_for(Path("codex"), schedule[0], temp_path, final_path)
        joined = " ".join(command)
        assert "--ignore-user-config" in command and "--strict-config" in command and "--ephemeral" in command
        assert "gpt-5.6-sol" in command and "model_reasoning_effort=\"high\"" in command
        assert "service_tier=\"default\"" in command and "--sandbox read-only" in joined
        checks += 1

        owner = temp_path / "owner"
        owner.mkdir()
        git("init", "--quiet", cwd=owner)
        final_path.write_text('{"status":"ready"}\n', encoding="utf-8")
        validate_result("owner", owner, final_path)
        checks += 1

        executor = temp_path / "executor"
        executor.mkdir()
        git("init", "--quiet", cwd=executor)
        (executor / "result.txt").write_bytes(b"SOL_ROOT_CANARY_V0_3\n")
        validate_result("executor", executor, final_path)
        (executor / "extra.txt").write_text("no", encoding="utf-8")
        refusal(lambda: validate_result("executor", executor, final_path))
        checks += 1

    print(f"OK - {checks} Sol-root activation v0.3 checks; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
