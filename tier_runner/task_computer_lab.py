"""Executable Task Computer laboratory over real Playwright and project-shaped fixtures."""
from __future__ import annotations

from collections import Counter
import asyncio
import json
from pathlib import Path
import secrets
import shutil
import time
from typing import Any

from .playwright_computer import PlaywrightComputer
from .playwright_computer_common import (
    EventLedger,
    PlaywrightComputerError,
    atomic_json,
    hash_file,
    hash_json,
    load_json,
    now_utc,
    safe_relative_path,
    without_hash,
)
from .task_computer_fixtures import ProjectFixtureServer
from .task_computer_planner import Planner, ReferencePlanner
from .task_computer_protocol import (
    RUN_RECEIPT_SCHEMA,
    STEP_RECEIPT_SCHEMA,
    compile_planner_packet,
    critic_verdict,
    resolve_element,
    scenario_by_id,
    screen_ghost_request,
    validate_catalog,
    verify_hashed_record,
)


def load_catalog(path: Path) -> dict[str, Any]:
    return validate_catalog(load_json(path))


def _browser_config(
    scenario: dict[str, Any],
    *,
    start_url: str,
    headless: bool,
    trace: bool,
) -> dict[str, Any]:
    return {
        "schema": "tier-bench/playwright-computer@1",
        "id": f"task-computer-{scenario['id']}",
        "title": scenario["title"],
        "mode": "isolated",
        "headless": headless,
        "start_url": start_url,
        "paths": {
            "workspace": "workspace",
            "profile": "profile",
            "downloads": "downloads",
            "artifacts": "artifacts",
            "secrets": "secrets",
        },
        "viewport": {"width": 1280, "height": 900},
        "locale": "en-US",
        "allowed_schemes": ["http", "https", "about", "data"],
        "allowed_domains": ["127.0.0.1"],
        "blocked_domains": [],
        "deny_private_networks": False,
        "trace": trace,
        "record_video": False,
        "force_open_shadow_dom": False,
        "policy": {
            "max_actions_per_batch": scenario["policy"]["max_actions_per_proposal"],
            "default_timeout_ms": 8000,
            "navigation_timeout_ms": 20000,
            "wait_between_actions_ms": 100,
            "viewport_expansion": 500,
            "max_visible_text_chars": 24000,
            "highlight_elements": True,
            "external_write_requires_approval": True,
            "sensitive_input_requires_approval": True,
            "allow_javascript": False,
            "allow_upload": True,
            "allow_download": True,
        },
        "takeover": {"enabled": True, "lease_seconds": 600},
    }


def _write_hashed(path: Path, value: dict[str, Any], hash_field: str) -> dict[str, Any]:
    if hash_field not in value:
        value = {**value, hash_field: hash_json(value)}
    atomic_json(path, value)
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": hash_file(path),
        hash_field: value[hash_field],
    }


def _write_plain(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    atomic_json(path, value)
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": hash_file(path)}


class TaskComputerRunner:
    def __init__(
        self,
        *,
        catalog: dict[str, Any],
        scenario_id: str,
        variant: str,
        out_root: Path,
        planner: Planner | None = None,
        headless: bool = True,
        trace: bool = True,
        approval_enabled: bool = True,
        run_id: str | None = None,
    ):
        self.catalog = catalog
        self.scenario = scenario_by_id(catalog, scenario_id)
        if variant not in self.scenario["variants"]:
            raise PlaywrightComputerError(
                f"scenario {scenario_id} has no variant {variant!r}; choose {self.scenario['variants']}"
            )
        self.variant = variant
        self.out_root = out_root.resolve()
        self.run_id = run_id or (
            f"{scenario_id}-{variant}-{int(time.time())}-{secrets.token_hex(4)}"
        )
        self.run_dir = self.out_root / self.run_id
        if self.run_dir.exists():
            raise PlaywrightComputerError(f"append-only run already exists: {self.run_dir}")
        self.run_dir.mkdir(parents=True)
        self.records_dir = self.run_dir / "records"
        self.records_dir.mkdir()
        self.computer_root = self.run_dir / "computer"
        self.planner = planner or ReferencePlanner(self.scenario)
        self.headless = headless
        self.trace = trace
        self.approval_token = secrets.token_urlsafe(24) if approval_enabled else None
        self.fixture = ProjectFixtureServer(scenario_id, variant)
        self.computer: PlaywrightComputer | None = None
        self.history: list[dict[str, Any]] = []
        self.step_records: list[dict[str, Any]] = []
        self.routes: Counter[str] = Counter()
        self.error: str | None = None

    def _effect_approved(self, effect: str) -> bool:
        return effect in self.scenario["policy"]["approval_effects"] and self.approval_token is not None

    async def _execute_playwright(
        self,
        *,
        action: dict[str, Any],
        packet: dict[str, Any],
        ordinal: int,
    ) -> dict[str, Any]:
        assert self.computer is not None
        state = self.computer.current_state or await self.computer.observe()
        args = dict(action["args"])
        if action["target"] is not None:
            element = resolve_element(state, action["target"])
            args["index"] = element["index"]
        browser_action = {
            "schema": "tier-bench/playwright-action@1",
            "action_id": f"{packet['step_number']:04d}-{ordinal:02d}-{action['id']}",
            "expected_state_id": state["state_id"],
            "op": action["op"],
            "args": args,
            "intent": action["intent"],
        }
        if self._effect_approved(action["effect"]):
            browser_action["approval_token"] = self.approval_token
        receipt = await self.computer.execute(browser_action)
        if receipt["error"]:
            raise PlaywrightComputerError(receipt["error"])
        self.routes["playwright"] += 1
        return {
            "surface": "playwright",
            "action": action,
            "browser_receipt": receipt,
            "completed_state_id": receipt["completed_state_id"],
        }

    async def _execute_screen_ghost(
        self,
        *,
        action: dict[str, Any],
        packet: dict[str, Any],
        ordinal: int,
    ) -> dict[str, Any]:
        assert self.computer is not None
        state = self.computer.current_state or await self.computer.observe()
        if state["state_id"] != packet["state"]["state_id"]:
            raise PlaywrightComputerError("ScreenGhost proposal is stale")
        request = screen_ghost_request(
            scenario=self.scenario,
            packet=packet,
            action=action,
        )
        request_path = self.records_dir / f"{packet['step_number']:04d}-{ordinal:02d}-screen-ghost-request.json"
        _write_hashed(request_path, request, "request_sha256")
        args = dict(action["args"])
        oracle = None
        if action["target"] and action["target"].get("visual_id"):
            oracle = self.fixture.app.visual_target(
                action["target"]["visual_id"], self.computer.config["viewport"]
            )
            args.update({"x": oracle["x"], "y": oracle["y"]})
        if "x" not in args or "y" not in args:
            raise PlaywrightComputerError("ScreenGhost tap has no coordinates")
        x = float(args["x"])
        y = float(args["y"])
        width = self.computer.config["viewport"]["width"]
        height = self.computer.config["viewport"]["height"]
        if 0 <= x <= 1 and 0 <= y <= 1:
            x *= width
            y *= height
        if not 0 <= x < width or not 0 <= y < height:
            raise PlaywrightComputerError(
                f"ScreenGhost coordinates {(x, y)} are outside viewport {(width, height)}"
            )
        self.computer.ledger.append(
            "task.screen_ghost.action.started",
            state_id=state["state_id"],
            action_id=action["id"],
            detail={
                "request_sha256": request["request_sha256"],
                "effect": action["effect"],
                "x": round(x, 3),
                "y": round(y, 3),
                "oracle": oracle,
            },
        )
        await self.computer.current_page.mouse.click(x, y)
        await asyncio.sleep(0.2)
        after = await self.computer.observe()
        self.computer.ledger.append(
            "task.screen_ghost.action.completed",
            state_id=after["state_id"],
            action_id=action["id"],
            detail={
                "request_sha256": request["request_sha256"],
                "started_state_id": state["state_id"],
                "completed_state_id": after["state_id"],
            },
        )
        self.routes["screen_ghost"] += 1
        return {
            "surface": "screen_ghost",
            "action": action,
            "screen_ghost_request": {
                "path": request_path.name,
                "sha256": hash_file(request_path),
                "request_sha256": request["request_sha256"],
            },
            "candidate": {
                "state_id": state["state_id"],
                "x": round(x, 3),
                "y": round(y, 3),
                "confidence": oracle["confidence"] if oracle else args.get("confidence"),
                "description": action["intent"],
                "evidence_tier": oracle["evidence_tier"] if oracle else "external_candidate",
            },
            "completed_state_id": after["state_id"],
        }

    async def _execute_workspace(
        self,
        *,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        assert self.computer is not None
        op = action["op"]
        args = action["args"]
        source_root = self.computer.downloads if args.get("root") == "downloads" else self.computer.workspace
        relative = str(args.get("path", ""))
        target = safe_relative_path(source_root, relative, "workspace action path")
        result: dict[str, Any] = {"surface": "workspace", "action": action}
        if op == "assert_file":
            if not target.is_file():
                raise PlaywrightComputerError(f"expected file does not exist: {target}")
            result["file"] = {
                "path": str(target.relative_to(self.computer.root)),
                "bytes": target.stat().st_size,
                "sha256": hash_file(target),
            }
        elif op == "hash_file":
            if not target.is_file():
                raise PlaywrightComputerError(f"file does not exist: {target}")
            result["sha256"] = hash_file(target)
        elif op == "copy_file":
            if not target.is_file():
                raise PlaywrightComputerError(f"source file does not exist: {target}")
            destination = safe_relative_path(
                self.computer.workspace,
                str(args.get("destination", target.name)),
                "workspace copy destination",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
            result["file"] = {
                "path": str(destination.relative_to(self.computer.root)),
                "bytes": destination.stat().st_size,
                "sha256": hash_file(destination),
            }
        elif op == "write_manifest":
            value = args.get("value")
            if not isinstance(value, dict):
                raise PlaywrightComputerError("write_manifest requires args.value object")
            atomic_json(target, value)
            result["file"] = {
                "path": str(target.relative_to(self.computer.root)),
                "bytes": target.stat().st_size,
                "sha256": hash_file(target),
            }
        elif op == "done":
            result["done"] = True
        else:
            raise PlaywrightComputerError(f"unsupported workspace operation {op}")
        self.routes["workspace"] += 1
        return result

    async def _execute_human(self, action: dict[str, Any]) -> dict[str, Any]:
        assert self.computer is not None
        if action["op"] == "takeover":
            lease = await self.computer.takeover(seconds=action["args"].get("seconds"))
            self.routes["human"] += 1
            return {"surface": "human", "action": action, "takeover": lease}
        if action["op"] == "release":
            lease_id = str(action["args"].get("lease_id", ""))
            result = await self.computer.release_takeover(lease_id)
            self.routes["human"] += 1
            return {"surface": "human", "action": action, "release": result}
        if action["op"] == "done":
            return {"surface": "human", "action": action, "done": True}
        raise PlaywrightComputerError(f"unsupported human operation {action['op']}")

    async def _execute_action(
        self,
        *,
        action: dict[str, Any],
        packet: dict[str, Any],
        ordinal: int,
    ) -> dict[str, Any]:
        surface = action["surface"]
        if surface == "playwright":
            return await self._execute_playwright(action=action, packet=packet, ordinal=ordinal)
        if surface == "screen_ghost":
            return await self._execute_screen_ghost(action=action, packet=packet, ordinal=ordinal)
        if surface == "workspace":
            return await self._execute_workspace(action=action)
        if surface == "human":
            return await self._execute_human(action)
        raise PlaywrightComputerError(f"unsupported surface {surface}")

    async def run(self) -> dict[str, Any]:
        started_at = now_utc()
        started_monotonic = time.perf_counter()
        _write_plain(self.run_dir / "scenario.json", self.scenario)
        _write_plain(
            self.run_dir / "run-start.json",
            {
                "schema": "tier-bench/task-computer-run-start@1",
                "run_id": self.run_id,
                "started_at": started_at,
                "scenario_id": self.scenario["id"],
                "project": self.scenario["project"],
                "variant": self.variant,
                "planner": type(self.planner).__name__,
                "headless": self.headless,
                "trace": self.trace,
                "approval_available": self.approval_token is not None,
            },
        )
        self.fixture.start()
        config = _browser_config(
            self.scenario,
            start_url=self.fixture.url,
            headless=self.headless,
            trace=self.trace,
        )
        self.computer = PlaywrightComputer(
            config,
            root=self.computer_root,
            approval_token=self.approval_token,
        )
        browser_verification: dict[str, Any] = {"ok": False, "errors": ["not started"]}
        close_result: dict[str, Any] | None = None
        done = False
        try:
            await self.computer.start()
            for step_number in range(1, self.scenario["max_steps"] + 1):
                state = self.computer.current_state or await self.computer.observe()
                packet = compile_planner_packet(
                    run_id=self.run_id,
                    scenario=self.scenario,
                    variant=self.variant,
                    state=state,
                    step_number=step_number,
                    history=self.history,
                )
                packet_path = self.records_dir / f"{step_number:04d}-packet.json"
                packet_record = _write_hashed(packet_path, packet, "packet_sha256")
                proposal = self.planner.propose(packet)
                proposal_path = self.records_dir / f"{step_number:04d}-proposal.json"
                proposal_record = _write_hashed(
                    proposal_path, proposal, "proposal_sha256"
                )
                verdict = critic_verdict(
                    scenario=self.scenario,
                    packet=packet,
                    proposal=proposal,
                    approval_available=self.approval_token is not None,
                )
                verdict_path = self.records_dir / f"{step_number:04d}-verdict.json"
                verdict_record = _write_hashed(verdict_path, verdict, "verdict_sha256")
                if not verdict["pass"]:
                    raise PlaywrightComputerError(
                        "critic rejected proposal: " + "; ".join(verdict["errors"])
                    )
                action_results: list[dict[str, Any]] = []
                for ordinal, action in enumerate(proposal["actions"], 1):
                    action_results.append(
                        await self._execute_action(
                            action=action,
                            packet=packet,
                            ordinal=ordinal,
                        )
                    )
                completed_state = self.computer.current_state or state
                step_receipt: dict[str, Any] = {
                    "schema": STEP_RECEIPT_SCHEMA,
                    "run_id": self.run_id,
                    "scenario_id": self.scenario["id"],
                    "step_number": step_number,
                    "packet": packet_record,
                    "proposal": proposal_record,
                    "verdict": verdict_record,
                    "started_state_id": packet["state"]["state_id"],
                    "completed_state_id": completed_state["state_id"],
                    "actions": action_results,
                    "planner_memory": proposal["memory"],
                    "next_goal": proposal["next_goal"],
                    "done": proposal["done"],
                }
                step_receipt["step_receipt_sha256"] = hash_json(step_receipt)
                step_path = self.records_dir / f"{step_number:04d}-step.json"
                step_record = _write_hashed(
                    step_path, step_receipt, "step_receipt_sha256"
                )
                self.step_records.append(step_record)
                self.history.append(
                    {
                        "step_number": step_number,
                        "proposal_sha256": proposal["proposal_sha256"],
                        "verdict_sha256": verdict["verdict_sha256"],
                        "started_state_id": packet["state"]["state_id"],
                        "completed_state_id": completed_state["state_id"],
                        "actions": [
                            {
                                "surface": action["surface"],
                                "op": action["op"],
                                "effect": action["effect"],
                                "intent": action["intent"],
                            }
                            for action in proposal["actions"]
                        ],
                    }
                )
                if proposal["done"]:
                    done = True
                    break
            if not done:
                raise PlaywrightComputerError("planner exhausted max_steps without declaring done")
            expected_downloads = self.scenario["handoff"].get("expected_downloads", [])
            if expected_downloads:
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not all(
                    (self.computer.downloads / name).is_file() for name in expected_downloads
                ):
                    await asyncio.sleep(0.1)
            browser_verification = await self.computer.verify()
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                if self.computer is not None:
                    close_result = await self.computer.close()
            except Exception as exc:
                if self.error is None:
                    self.error = f"browser close failed: {type(exc).__name__}: {exc}"
            self.fixture.stop()

        fixture_acceptance = self.fixture.app.acceptance()
        expected_downloads = self.scenario["handoff"].get("expected_downloads", [])
        download_acceptance = []
        if self.computer is not None:
            for name in expected_downloads:
                path = self.computer.downloads / name
                download_acceptance.append(
                    {
                        "id": f"download-{name}",
                        "pass": path.is_file(),
                        "observed": (
                            {
                                "path": str(path.relative_to(self.computer.root)),
                                "bytes": path.stat().st_size,
                                "sha256": hash_file(path),
                            }
                            if path.is_file()
                            else None
                        ),
                        "expected": "downloaded file",
                    }
                )
        handoff = self.fixture.app.handoff()
        handoff["run_id"] = self.run_id
        handoff["scenario_id"] = self.scenario["id"]
        handoff["variant"] = self.variant
        handoff["handoff_sha256"] = hash_json(handoff)
        handoff_path = self.run_dir / "project-handoff.json"
        handoff_record = _write_hashed(handoff_path, handoff, "handoff_sha256")
        event_report = (
            EventLedger(
                self.computer_root / "artifacts" / "events.jsonl",
                f"task-computer-{self.scenario['id']}",
            ).verify()
            if (self.computer_root / "artifacts" / "events.jsonl").exists()
            else {"ok": False, "events": 0, "errors": ["event ledger missing"]}
        )
        acceptance = [
            *fixture_acceptance,
            *download_acceptance,
            {
                "id": "browser-evidence-verifies",
                "pass": bool(browser_verification.get("ok")) and bool(event_report.get("ok")),
                "observed": {
                    "browser": browser_verification,
                    "event_ledger": event_report,
                },
                "expected": "browser and event evidence verify",
            },
            {
                "id": "planner-declared-done",
                "pass": done,
                "observed": done,
                "expected": True,
            },
        ]
        accepted = self.error is None and all(item["pass"] for item in acceptance)
        receipt: dict[str, Any] = {
            "schema": RUN_RECEIPT_SCHEMA,
            "status": "ACCEPTED" if accepted else "REJECTED",
            "run_id": self.run_id,
            "scenario_id": self.scenario["id"],
            "project": self.scenario["project"],
            "variant": self.variant,
            "evidence_tier": "synthetic_project_fixture",
            "planner": type(self.planner).__name__,
            "started_at": started_at,
            "completed_at": now_utc(),
            "duration_seconds": round(time.perf_counter() - started_monotonic, 3),
            "steps": self.step_records,
            "routes": dict(sorted(self.routes.items())),
            "acceptance": acceptance,
            "cold_operator_expected_answers": self.scenario["cold_operator"],
            "project_handoff": handoff_record,
            "browser_close": close_result,
            "error": self.error,
            "promotion_authorized": False,
        }
        receipt["receipt_sha256"] = hash_json(receipt)
        atomic_json(self.run_dir / "receipt.json", receipt)
        return receipt


def verify_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    errors: list[str] = []
    receipt = load_json(run_dir / "receipt.json")
    if not isinstance(receipt, dict) or receipt.get("schema") != RUN_RECEIPT_SCHEMA:
        raise PlaywrightComputerError("run receipt has the wrong schema")
    if receipt.get("receipt_sha256") != hash_json(without_hash(receipt, "receipt_sha256")):
        errors.append("run receipt hash does not verify")
    for step in receipt.get("steps", []):
        path = run_dir / "records" / step["path"]
        if not path.is_file() or hash_file(path) != step["sha256"]:
            errors.append(f"step file does not verify: {step.get('path')}")
            continue
        value = load_json(path)
        if not verify_hashed_record(value, "step_receipt_sha256"):
            errors.append(f"step receipt identity does not verify: {step.get('path')}")
        for field, hash_field in (
            ("packet", "packet_sha256"),
            ("proposal", "proposal_sha256"),
            ("verdict", "verdict_sha256"),
        ):
            record = value.get(field, {})
            nested = run_dir / "records" / str(record.get("path", ""))
            if not nested.is_file() or hash_file(nested) != record.get("sha256"):
                errors.append(f"{field} file does not verify for {step.get('path')}")
            else:
                nested_value = load_json(nested)
                if not verify_hashed_record(nested_value, hash_field):
                    errors.append(f"{field} identity does not verify for {step.get('path')}")
    handoff_record = receipt.get("project_handoff", {})
    handoff_path = run_dir / str(handoff_record.get("path", ""))
    if not handoff_path.is_file() or hash_file(handoff_path) != handoff_record.get("sha256"):
        errors.append("project handoff file does not verify")
    else:
        handoff = load_json(handoff_path)
        if not verify_hashed_record(handoff, "handoff_sha256"):
            errors.append("project handoff identity does not verify")
    computer_id = f"task-computer-{receipt['scenario_id']}"
    ledger = EventLedger(run_dir / "computer" / "artifacts" / "events.jsonl", computer_id).verify()
    if not ledger["ok"]:
        errors.extend(ledger["errors"])
    return {
        "ok": not errors,
        "run_id": receipt["run_id"],
        "status": receipt["status"],
        "receipt_sha256": receipt["receipt_sha256"],
        "event_ledger": ledger,
        "errors": errors,
    }


async def run_suite(
    *,
    catalog: dict[str, Any],
    out_root: Path,
    scenario_ids: list[str] | None = None,
    variants: list[str] | None = None,
    headless: bool = True,
    trace: bool = False,
) -> dict[str, Any]:
    selected = [
        scenario
        for scenario in catalog["scenarios"]
        if scenario_ids is None or scenario["id"] in scenario_ids
    ]
    results: list[dict[str, Any]] = []
    for scenario in selected:
        chosen_variants = variants or scenario["variants"]
        for variant in chosen_variants:
            if variant not in scenario["variants"]:
                continue
            runner = TaskComputerRunner(
                catalog=catalog,
                scenario_id=scenario["id"],
                variant=variant,
                out_root=out_root,
                headless=headless,
                trace=trace,
            )
            receipt = await runner.run()
            verification = verify_run(runner.run_dir)
            results.append(
                {
                    "scenario_id": scenario["id"],
                    "variant": variant,
                    "run_dir": str(runner.run_dir),
                    "status": receipt["status"],
                    "receipt_sha256": receipt["receipt_sha256"],
                    "verification": verification,
                }
            )
    return {
        "schema": "tier-bench/task-computer-suite@1",
        "catalog_id": catalog["id"],
        "results": results,
        "ok": bool(results)
        and all(
            row["status"] == "ACCEPTED" and row["verification"]["ok"]
            for row in results
        ),
    }
