from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
from typing import Any

from .desk_common import DeskError, canonical, common_git_dir, now
from .desk_store import DeskStore


RUN_ENVELOPE_SCHEMA = "tier-bench/tier-run-envelope@1"


@dataclass
class ExecutionResult:
    state: str
    receipt: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    receipt_path: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    exit_code: int | None = None
    error: str | None = None


class TierRunExecutor:
    def __init__(
        self,
        repo: Path,
        store: DeskStore,
        heartbeat: Path,
        heartbeat_instance: str,
    ):
        self.repo = repo
        self.store = store
        self.heartbeat = heartbeat
        self.heartbeat_instance = heartbeat_instance
        self.lock = threading.Lock()
        self.processes: dict[str, subprocess.Popen[str]] = {}

    def envelope(self, task: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": RUN_ENVELOPE_SCHEMA,
            "repo": str(self.repo),
            "task_id": task["id"],
            "task": task["task"],
            "files": task["files"],
            "acceptance": task["acceptance"],
            "manifest": task["manifest"],
            "arm": task["arm"],
            "output_dir": run["output_dir"],
        }

    def command(self, envelope_path: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "tier_runner.desk_worker",
            "--envelope",
            str(envelope_path),
            "--heartbeat",
            str(self.heartbeat),
            "--heartbeat-instance",
            self.heartbeat_instance,
        ]

    @staticmethod
    def _process_kwargs() -> dict[str, object]:
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def cancel(self, run_id: str) -> bool:
        with self.lock:
            process = self.processes.get(run_id)
        if process is None or process.poll() is not None:
            return False
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
        return True

    def run(self, task: dict[str, Any], run: dict[str, Any]) -> ExecutionResult:
        output = Path(run["output_dir"])
        log_path = Path(run["log_path"])
        envelope_path = log_path.with_suffix(".envelope.json")
        envelope_path.write_text(canonical(self.envelope(task, run)) + "\n", encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        package_root = str(Path(__file__).resolve().parents[1])
        inherited_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            package_root
            if not inherited_pythonpath
            else package_root + os.pathsep + inherited_pythonpath
        )
        command = self.command(envelope_path)
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            log.write("$ " + json.dumps(command, ensure_ascii=False) + "\n\n")
            log.flush()
            process = subprocess.Popen(
                command,
                cwd=self.repo,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                **self._process_kwargs(),
            )
            self.store.set_pid(run["id"], process.pid)
            with self.lock:
                self.processes[run["id"]] = process
            exit_code = process.wait()
            with self.lock:
                self.processes.pop(run["id"], None)

        receipt_path = output / "receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(receipt, dict):
                raise ValueError("receipt is not an object")
        except (OSError, json.JSONDecodeError, ValueError):
            return ExecutionResult(
                "ERROR",
                receipt_path=str(receipt_path) if receipt_path.exists() else None,
                exit_code=exit_code,
                error=f"tier run exited {exit_code} without a readable receipt",
            )
        verify = subprocess.run(
            [sys.executable, "-m", "tier_runner.cli", "verify", "--run-dir", str(output)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )
        try:
            verification = json.loads(verify.stdout)
        except json.JSONDecodeError:
            verification = {"ok": False, "errors": ["tier verify returned non-JSON output"]}
        state = str(receipt.get("state", "ERROR"))
        if state not in {"ACCEPTED", "REJECTED", "ERROR"}:
            state = "ERROR"
        if verify.returncode or verification.get("ok") is not True:
            state = "ERROR"
        call: dict[str, Any] = {}
        ledger = output / "ledger.jsonl"
        if ledger.is_file():
            try:
                rows = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line]
                value = json.loads(rows[-1]) if rows else {}
                if isinstance(value, dict):
                    call = value
            except (OSError, json.JSONDecodeError):
                pass
        errors = receipt.get("errors") if isinstance(receipt.get("errors"), list) else []
        verify_errors = verification.get("errors") if isinstance(verification, dict) else []
        error = "; ".join(str(item) for item in [*errors, *verify_errors] if item) or None
        return ExecutionResult(
            state=state,
            receipt=receipt,
            verification=verification,
            receipt_path=str(receipt_path),
            cost_usd=float(call.get("cost_usd", 0) or 0),
            input_tokens=int(call.get("input_tokens", 0) or 0),
            output_tokens=int(call.get("output_tokens", 0) or 0),
            cache_read_tokens=int(call.get("cache_read_tokens", 0) or 0),
            cache_write_tokens=int(call.get("cache_write_tokens", 0) or 0),
            exit_code=exit_code,
            error=error,
        )


class DeskScheduler:
    def __init__(
        self,
        store: DeskStore,
        repo: Path,
        state_dir: Path,
        executor: Any | None = None,
        instance_id: str | None = None,
    ):
        self.store = store
        self.repo = repo
        self.instance_id = instance_id or secrets.token_hex(16)
        self.runs_dir = common_git_dir(repo) / "tier-runs" / "monster-wrangler"
        self.logs_dir = state_dir / "logs"
        self.heartbeat = state_dir / "heartbeat"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.executor = executor or TierRunExecutor(
            repo,
            store,
            self.heartbeat,
            self.instance_id,
        )
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.lock = threading.Lock()
        self.active: dict[str, tuple[str, threading.Thread]] = {}
        self.thread = threading.Thread(target=self.loop, name="monster-wrangler", daemon=True)

    def beat(self) -> None:
        temporary = self.heartbeat.with_name(self.heartbeat.name + f".{self.instance_id}.tmp")
        temporary.write_text(f"{self.instance_id} {now()}\n", encoding="utf-8")
        os.replace(temporary, self.heartbeat)

    def owns_heartbeat(self) -> bool:
        try:
            owner = self.heartbeat.read_text(encoding="utf-8").split(maxsplit=1)[0]
        except OSError:
            return False
        return owner == self.instance_id

    def start(self) -> None:
        self.beat()
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        with self.lock:
            active = list(self.active.items())
        for run_id, (task_id, _) in active:
            self.store.cancel_running(task_id, "desk stopped by operator")
            self.executor.cancel(run_id)
        for _, (_, thread) in active:
            thread.join(timeout=12)
        self.thread.join(timeout=10)
        if self.owns_heartbeat():
            self.heartbeat.unlink(missing_ok=True)

    def wake(self) -> None:
        self.wake_event.set()

    def active_ids(self) -> list[str]:
        with self.lock:
            return sorted(self.active)

    def budget_allows(self) -> tuple[bool, str]:
        settings = self.store.settings()
        usage = self.store.daily_usage()
        if int(usage["tasks"]) >= int(settings["daily_task_limit"]):
            return False, "daily task limit reached"
        cost_limit = float(settings["daily_cost_limit_usd"])
        if cost_limit > 0 and float(usage["cost_usd"]) >= cost_limit:
            return False, "daily observed-cost limit reached"
        return True, ""

    def cancel_task(self, task_id: str) -> None:
        task = self.store.get_task(task_id, False)
        if task is None:
            raise DeskError(f"unknown task: {task_id}")
        if task["state"] == "RUNNING" and task.get("last_run_id"):
            self.store.cancel_running(task_id, "canceled by operator")
            self.executor.cancel(task["last_run_id"])
        else:
            self.store.transition(task_id, "cancel")
        self.wake()

    def emergency_stop(self) -> None:
        self.store.pause("emergency stop requested")
        with self.lock:
            active = list(self.active.items())
        for run_id, (task_id, _) in active:
            self.store.cancel_running(task_id, "emergency stop requested")
            self.executor.cancel(run_id)
        self.wake()

    def loop(self) -> None:
        last_error = ""
        while not self.stop_event.is_set():
            try:
                self.tick()
                last_error = ""
            except Exception as exc:
                message = f"scheduler failure: {type(exc).__name__}: {exc}"
                if message != last_error:
                    try:
                        self.store.pause(message)
                    except Exception:
                        pass
                    last_error = message
            self.wake_event.wait(0.75)
            self.wake_event.clear()

    def tick(self) -> None:
        self.beat()
        settings = self.store.settings()
        with self.lock:
            active_count = len(self.active)
        if settings["paused"] or active_count >= int(settings["max_workers"]):
            return
        allowed, reason = self.budget_allows()
        if not allowed:
            self.store.pause(reason)
            return
        available = int(settings["max_workers"]) - active_count
        for task in self.store.ready(available):
            allowed, reason = self.budget_allows()
            if not allowed:
                self.store.pause(reason)
                break
            claimed = self.store.claim(task["id"], self.runs_dir, self.logs_dir)
            if claimed is None:
                continue
            claimed_task, run = claimed
            thread = threading.Thread(
                target=self.execute,
                args=(claimed_task, run),
                name=f"monster-run-{run['id']}",
                daemon=True,
            )
            with self.lock:
                self.active[run["id"]] = (claimed_task["id"], thread)
            thread.start()

    def execute(self, task: dict[str, Any], run: dict[str, Any]) -> None:
        try:
            result = self.executor.run(task, run)
            current = self.store.get_task(task["id"], False)
            if current and current["state"] == "CANCELED":
                return
            self.store.complete(run["id"], result)
            if result.state in {"REJECTED", "ERROR"} and self.store.settings()["stop_on_failure"]:
                self.store.pause(f"{task['id']} ended {result.state}; operator review required")
        except Exception as exc:
            try:
                current = self.store.get_task(task["id"], False)
                if current and current["state"] == "CANCELED":
                    return
                self.store.complete(
                    run["id"],
                    ExecutionResult("ERROR", error=f"executor failure: {exc}"),
                )
                if self.store.settings()["stop_on_failure"]:
                    self.store.pause(f"{task['id']} hit an executor error")
            except Exception:
                pass
        finally:
            with self.lock:
                self.active.pop(run["id"], None)
            self.wake()
