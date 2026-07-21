"""Witness: a candidate that hangs its own grader is terminated, not tolerated.

Measured 2026-07-19 on the fnmatch-charclass bake-off: a local-model candidate
emitted an unbounded loop, the hidden grader never returned, and the single
desk worker stayed RUNNING indefinitely while a *grandchild* process spun. The
referee now supervises the whole tree and returns a terminal verdict.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tier_runner.core import TIMEOUT_RETURNCODE, _run  # noqa: E402


SPINNER = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "\\nwhile True:\\n    pass\\n"])
print("SPAWNED", child.pid, flush=True)
child.wait()
"""


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    try:
        import os

        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_hanging_acceptance_is_terminated() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        script = work / "spinner.py"
        script.write_text(SPINNER, encoding="utf-8")
        started = time.monotonic()
        result = _run(f'"{sys.executable}" -B "{script}"', work, shell=True, timeout=3.0)
        elapsed = time.monotonic() - started
        if result.returncode != TIMEOUT_RETURNCODE:
            print(f"  FAIL expected rc={TIMEOUT_RETURNCODE}, got {result.returncode}")
            return False
        if elapsed > 30:
            print(f"  FAIL timeout did not bound runtime: {elapsed:.1f}s")
            return False
        if "exceeded" not in (result.stderr or ""):
            print("  FAIL stderr does not explain the termination")
            return False
        grandchild = None
        for token in (result.stdout or "").split():
            if token.isdigit():
                grandchild = int(token)
                break
        if grandchild is None:
            print("  FAIL could not observe the grandchild pid")
            return False
        time.sleep(1.5)
        if _alive(grandchild):
            subprocess.run(
                ["taskkill", "/PID", str(grandchild), "/T", "/F"], capture_output=True
            )
            print(f"  FAIL grandchild {grandchild} survived the tree kill")
            return False
        print(f"  ok - hang terminated in {elapsed:.1f}s, tree reaped, rc={result.returncode}")
        return True


def test_normal_command_still_passes_through() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(
            f'"{sys.executable}" -c "print(42)"', Path(tmp), shell=True, timeout=60.0
        )
        if result.returncode != 0 or "42" not in (result.stdout or ""):
            print(f"  FAIL rc={result.returncode} stdout={result.stdout!r}")
            return False
        print("  ok - bounded run returns normal output and rc=0")
        return True


def test_failing_command_keeps_its_returncode() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(
            f'"{sys.executable}" -c "raise SystemExit(3)"', Path(tmp), shell=True, timeout=60.0
        )
        if result.returncode != 3:
            print(f"  FAIL expected rc=3, got {result.returncode}")
            return False
        print("  ok - ordinary failure is not masked by the timeout path")
        return True


def main() -> int:
    checks = [
        test_normal_command_still_passes_through,
        test_failing_command_keeps_its_returncode,
        test_hanging_acceptance_is_terminated,
    ]
    passed = sum(1 for check in checks if check())
    print(f"{'PASS' if passed == len(checks) else 'FAIL'} acceptance_timeout {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
