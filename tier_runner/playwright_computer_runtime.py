"""Long-lived Playwright browser computer with Manus-shaped observation and action loops."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import secrets
import socket
import time
from typing import Any
import uuid

from .playwright_computer_common import (
    EventLedger,
    ExclusiveLease,
    PlaywrightComputerError,
    atomic_json,
    hash_bytes,
    hash_file,
    hash_json,
    load_json,
    now_utc,
    safe_relative_path,
)
from .playwright_computer_protocol import (
    ACTION_RECEIPT_SCHEMA,
    STATE_SCHEMA,
    TAKEOVER_SCHEMA,
    approval_valid,
    batch_break_reason,
    classify_action,
    element_for_action,
    redact_action,
    url_allowed,
    validate_action,
    validate_config,
)


class PlaywrightComputer:
    """One task-scoped browser, filesystem, evidence stream, and human-control lease."""

    def __init__(
        self,
        raw_config: dict[str, Any],
        *,
        root: Path,
        approval_token: str | None = None,
    ):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = validate_config(raw_config, root=self.root)
        self.config_sha256 = hash_json(self.config)
        self.approval_token = approval_token
        self.workspace = safe_relative_path(
            self.root, self.config["paths"]["workspace"], "computer.paths.workspace"
        )
        self.profile = safe_relative_path(
            self.root, self.config["paths"]["profile"], "computer.paths.profile"
        )
        self.downloads = safe_relative_path(
            self.root, self.config["paths"]["downloads"], "computer.paths.downloads"
        )
        self.artifacts = safe_relative_path(
            self.root, self.config["paths"]["artifacts"], "computer.paths.artifacts"
        )
        self.secrets = safe_relative_path(
            self.root, self.config["paths"]["secrets"], "computer.paths.secrets"
        )
        for path in (self.workspace, self.profile, self.downloads, self.artifacts, self.secrets):
            path.mkdir(parents=True, exist_ok=True)
        self.states_dir = self.artifacts / "states"
        self.extracts_dir = self.artifacts / "extracts"
        self.screenshots_dir = self.artifacts / "screenshots"
        self.traces_dir = self.artifacts / "traces"
        for path in (self.states_dir, self.extracts_dir, self.screenshots_dir, self.traces_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.ledger = EventLedger(self.artifacts / "events.jsonl", self.config["id"])
        self.process_lease = ExclusiveLease(self.root / "computer.lease.json")
        self.takeover_lease = ExclusiveLease(self.root / "takeover.lease.json")
        self._probe_script = (
            Path(__file__).with_name("playwright_dom_probe.js").read_text(encoding="utf-8")
        )
        self._playwright = None
        self.browser = None
        self.context = None
        self.current_page = None
        self.current_state: dict[str, Any] | None = None
        self.page_ids: dict[int, str] = {}
        self.state_counter = 0
        self.started = False
        self.closed = False
        self.lock = asyncio.Lock()

    def _storage_state_path(self) -> Path | None:
        value = self.config.get("storage_state_file")
        if not value:
            return None
        return safe_relative_path(self.secrets, value, "computer.storage_state_file")

    def _page_id(self, page: Any) -> str:
        key = id(page)
        if key not in self.page_ids:
            self.page_ids[key] = "page-" + uuid.uuid4().hex[:16]
        return self.page_ids[key]

    async def start(self) -> dict[str, Any]:
        if self.started:
            return await self.health()
        lease = {
            "schema": "tier-bench/playwright-computer-process-lease@1",
            "computer_id": self.config["id"],
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": now_utc(),
            "config_sha256": self.config_sha256,
        }
        self.process_lease.claim(lease)
        try:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise PlaywrightComputerError(
                    "Playwright is not installed; install the Tier Bench browser extra and Chromium"
                ) from exc
            self._playwright = await async_playwright().start()
            chromium = self._playwright.chromium
            context_options: dict[str, Any] = {
                "accept_downloads": self.config["policy"]["allow_download"],
                "viewport": self.config["viewport"],
                "locale": self.config["locale"],
            }
            if self.config["user_agent"]:
                context_options["user_agent"] = self.config["user_agent"]
            if self.config["record_video"]:
                context_options["record_video_dir"] = str(self.artifacts / "video")
                context_options["record_video_size"] = self.config["viewport"]
            storage_state = self._storage_state_path()
            if storage_state and storage_state.exists() and self.config["mode"] == "isolated":
                context_options["storage_state"] = str(storage_state)
            if self.config["mode"] == "persistent":
                self.context = await chromium.launch_persistent_context(
                    user_data_dir=str(self.profile),
                    headless=self.config["headless"],
                    downloads_path=str(self.downloads),
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-popup-blocking",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    **context_options,
                )
                self.browser = self.context.browser
            elif self.config["mode"] == "cdp":
                connect_args: dict[str, Any] = {
                    "endpoint_url": self.config["cdp_url"],
                    "timeout": self.config["policy"]["navigation_timeout_ms"],
                }
                parameters = inspect.signature(chromium.connect_over_cdp).parameters
                if "no_defaults" in parameters:
                    connect_args["no_defaults"] = True
                if "is_local" in parameters:
                    connect_args["is_local"] = True
                if "artifacts_dir" in parameters:
                    connect_args["artifacts_dir"] = str(self.artifacts)
                self.browser = await chromium.connect_over_cdp(**connect_args)
                if not self.browser.contexts:
                    raise PlaywrightComputerError("CDP browser exposes no default context")
                self.context = self.browser.contexts[0]
            else:
                self.browser = await chromium.launch(
                    headless=self.config["headless"],
                    downloads_path=str(self.downloads),
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-popup-blocking",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                )
                self.context = await self.browser.new_context(**context_options)
            self.context.set_default_timeout(self.config["policy"]["default_timeout_ms"])
            self.context.set_default_navigation_timeout(
                self.config["policy"]["navigation_timeout_ms"]
            )
            if self.config["force_open_shadow_dom"] and self.config["mode"] != "cdp":
                await self.context.add_init_script(
                    """
                    (() => {
                      const original = Element.prototype.attachShadow;
                      Element.prototype.attachShadow = function(options) {
                        return original.call(this, {...options, mode: 'open'});
                      };
                    })();
                    """
                )
            if self.config["trace"]:
                await self.context.tracing.start(
                    screenshots=True,
                    snapshots=True,
                    sources=True,
                )
            self.context.on("page", self._attach_page)
            for page in self.context.pages:
                self._attach_page(page)
            self.current_page = self.context.pages[-1] if self.context.pages else await self.context.new_page()
            self._attach_page(self.current_page)
            if self.current_page.url == "about:blank" and self.config["start_url"] != "about:blank":
                await self._navigate(self.config["start_url"])
            self.started = True
            self.ledger.append(
                "computer.started",
                detail={
                    "config_sha256": self.config_sha256,
                    "mode": self.config["mode"],
                    "headless": self.config["headless"],
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                },
            )
            await self.observe()
            return await self.health()
        except Exception:
            await self._close_partial()
            self.process_lease.release()
            raise

    def _attach_page(self, page: Any) -> None:
        self._page_id(page)
        page.on(
            "console",
            lambda message: self.ledger.append(
                "browser.console",
                detail={"page_id": self._page_id(page), "type": message.type, "text": message.text[:4000]},
            ),
        )
        page.on(
            "pageerror",
            lambda error: self.ledger.append(
                "browser.pageerror",
                detail={"page_id": self._page_id(page), "error": str(error)[:4000]},
            ),
        )
        page.on(
            "requestfailed",
            lambda request: self.ledger.append(
                "browser.requestfailed",
                detail={
                    "page_id": self._page_id(page),
                    "url": request.url[:4000],
                    "failure": str(request.failure)[:1000],
                },
            ),
        )
        page.on("download", lambda download: asyncio.create_task(self._handle_download(page, download)))
        page.on("dialog", lambda dialog: asyncio.create_task(self._handle_dialog(page, dialog)))
        page.on(
            "close",
            lambda: self.ledger.append(
                "browser.page.closed", detail={"page_id": self._page_id(page)}
            ),
        )

    async def _handle_dialog(self, page: Any, dialog: Any) -> None:
        self.ledger.append(
            "browser.dialog",
            detail={
                "page_id": self._page_id(page),
                "type": dialog.type,
                "message": dialog.message[:4000],
                "default_value": dialog.default_value[:1000],
                "disposition": "dismissed",
            },
        )
        try:
            await dialog.dismiss()
        except Exception:
            pass

    async def _handle_download(self, page: Any, download: Any) -> None:
        if not self.config["policy"]["allow_download"]:
            try:
                await download.cancel()
            finally:
                self.ledger.append(
                    "browser.download.blocked",
                    detail={"page_id": self._page_id(page), "url": download.url[:4000]},
                )
            return
        filename = Path(download.suggested_filename).name or "download.bin"
        destination = self.downloads / filename
        stem, suffix = destination.stem, destination.suffix
        counter = 1
        while destination.exists():
            destination = self.downloads / f"{stem} ({counter}){suffix}"
            counter += 1
        try:
            await download.save_as(str(destination))
            self.ledger.append(
                "browser.download.completed",
                detail={
                    "page_id": self._page_id(page),
                    "url": download.url[:4000],
                    "path": str(destination.relative_to(self.root)),
                    "bytes": destination.stat().st_size,
                    "sha256": hash_file(destination),
                },
            )
        except Exception as exc:
            self.ledger.append(
                "browser.download.failed",
                detail={"page_id": self._page_id(page), "error": str(exc)[:4000]},
            )

    async def _wait_ready(self, page: Any) -> dict[str, Any]:
        status = {"domcontentloaded": False, "networkidle": False}
        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=self.config["policy"]["navigation_timeout_ms"]
            )
            status["domcontentloaded"] = True
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=1500)
            status["networkidle"] = True
        except Exception:
            pass
        await asyncio.sleep(0.05)
        return status

    def _redact_element(self, element: dict[str, Any]) -> dict[str, Any]:
        value = dict(element)
        attributes = dict(value.get("attributes", {}))
        if "value" in attributes:
            raw = attributes.pop("value")
            attributes["value_sha256"] = hash_json({"value": raw})
            attributes["value_redacted"] = True
        value["attributes"] = attributes
        return value

    def _format_elements(self, elements: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for element in elements:
            attributes = element.get("attributes", {})
            details = [
                value
                for value in (
                    element.get("role"),
                    element.get("name"),
                    attributes.get("placeholder"),
                    attributes.get("title"),
                    attributes.get("href"),
                )
                if value
            ]
            detail = "; ".join(dict.fromkeys(str(item) for item in details))
            text = str(element.get("text") or "").strip()
            body = detail or text
            if detail and text and text not in detail:
                body += " > " + text
            lines.append(f"[{element['index']}]<{element['tag']}>{body}</{element['tag']}>")
        return "\n".join(lines)

    async def _remove_overlays(self) -> None:
        if self.current_page is None:
            return
        for frame in self.current_page.frames:
            try:
                await frame.evaluate(
                    """
                    () => {
                      document.getElementById('tier-browser-highlight-container')?.remove();
                    }
                    """
                )
            except Exception:
                continue

    async def observe(self) -> dict[str, Any]:
        if not self.started and self.context is None:
            raise PlaywrightComputerError("computer is not started")
        async with self.lock:
            if self.current_page is None or self.current_page.is_closed():
                pages = [page for page in self.context.pages if not page.is_closed()]
                self.current_page = pages[-1] if pages else await self.context.new_page()
                self._attach_page(self.current_page)
            page = self.current_page
            readiness = await self._wait_ready(page)
            await self._remove_overlays()
            self.state_counter += 1
            prefix = f"{self.state_counter:06d}"
            clean_path = self.states_dir / f"{prefix}-clean.png"
            marked_path = self.states_dir / f"{prefix}-marked.png"
            await page.screenshot(path=str(clean_path), full_page=False, animations="disabled")
            probe_nonce = secrets.token_hex(8)
            elements: list[dict[str, Any]] = []
            text_parts: list[str] = []
            next_index = 0
            main_scroll = {
                "pixelsAbove": 0,
                "pixelsBelow": 0,
                "viewportHeight": self.config["viewport"]["height"],
                "documentHeight": self.config["viewport"]["height"],
            }
            for frame_index, frame in enumerate(page.frames):
                try:
                    result = await frame.evaluate(
                        self._probe_script,
                        {
                            "startIndex": next_index,
                            "probeNonce": probe_nonce,
                            "viewportExpansion": self.config["policy"]["viewport_expansion"],
                            "highlight": self.config["policy"]["highlight_elements"],
                            "maxVisibleTextChars": self.config["policy"]["max_visible_text_chars"],
                        },
                    )
                except Exception as exc:
                    self.ledger.append(
                        "browser.frame.probe_failed",
                        detail={
                            "page_id": self._page_id(page),
                            "frame_index": frame_index,
                            "frame_url": frame.url[:4000],
                            "error": str(exc)[:4000],
                        },
                    )
                    continue
                if frame_index == 0:
                    main_scroll = result.get("scroll", main_scroll)
                text = str(result.get("visibleText") or "").strip()
                if text:
                    text_parts.append(
                        f"[Frame {frame_index}: {frame.url}]\n{text}"
                        if frame_index
                        else text
                    )
                for raw in result.get("elements", []):
                    element = self._redact_element(raw)
                    element["frame_index"] = frame_index
                    element["frame_url"] = frame.url
                    element["frame_name"] = frame.name
                    element["signature"] = hash_json(
                        {
                            "frame_url": frame.url,
                            "tag": element.get("tag"),
                            "role": element.get("role"),
                            "name": element.get("name"),
                            "attributes": element.get("attributes"),
                            "css_path": element.get("css_path"),
                        }
                    )
                    elements.append(element)
                next_index = int(result.get("nextIndex", next_index))
            await page.screenshot(path=str(marked_path), full_page=False, animations="disabled")
            tabs = [
                {
                    "page_id": self._page_id(candidate),
                    "url": candidate.url,
                    "title": await candidate.title(),
                    "active": candidate is page,
                }
                for candidate in self.context.pages
                if not candidate.is_closed()
            ]
            visible_text = "\n\n".join(text_parts)
            text_path = self.states_dir / f"{prefix}-visible.txt"
            text_path.write_text(visible_text, encoding="utf-8", newline="\n")
            state_without_id: dict[str, Any] = {
                "schema": STATE_SCHEMA,
                "computer_id": self.config["id"],
                "config_sha256": self.config_sha256,
                "sequence": self.state_counter,
                "captured_at": now_utc(),
                "page_id": self._page_id(page),
                "url": page.url,
                "title": await page.title(),
                "tabs": tabs,
                "elements": elements,
                "elements_text": self._format_elements(elements),
                "scroll": {
                    "pixels_above": int(main_scroll.get("pixelsAbove", 0)),
                    "pixels_below": int(main_scroll.get("pixelsBelow", 0)),
                    "viewport_height": int(main_scroll.get("viewportHeight", 0)),
                    "document_height": int(main_scroll.get("documentHeight", 0)),
                },
                "readiness": readiness,
                "artifacts": {
                    "clean_screenshot": {
                        "path": str(clean_path.relative_to(self.root)),
                        "bytes": clean_path.stat().st_size,
                        "sha256": hash_file(clean_path),
                    },
                    "marked_screenshot": {
                        "path": str(marked_path.relative_to(self.root)),
                        "bytes": marked_path.stat().st_size,
                        "sha256": hash_file(marked_path),
                    },
                    "visible_text": {
                        "path": str(text_path.relative_to(self.root)),
                        "bytes": text_path.stat().st_size,
                        "sha256": hash_file(text_path),
                    },
                },
            }
            state_id = hash_json(state_without_id)
            state = {**state_without_id, "state_id": state_id}
            state_path = self.states_dir / f"{prefix}-{state_id[:12]}.json"
            atomic_json(state_path, state)
            self.current_state = state
            self.ledger.append(
                "browser.state.observed",
                state_id=state_id,
                detail={
                    "sequence": self.state_counter,
                    "page_id": state["page_id"],
                    "url": state["url"],
                    "title": state["title"],
                    "tabs": len(tabs),
                    "elements": len(elements),
                    "state_path": str(state_path.relative_to(self.root)),
                },
            )
            return state

    async def _frame_for_element(self, element: dict[str, Any]) -> Any:
        page = self.current_page
        if page is None:
            raise PlaywrightComputerError("there is no active page")
        frames = page.frames
        frame_index = int(element.get("frame_index", 0))
        if frame_index < len(frames):
            frame = frames[frame_index]
            if not element.get("frame_url") or frame.url == element.get("frame_url"):
                return frame
        matches = [
            frame
            for frame in frames
            if frame.url == element.get("frame_url")
            and (not element.get("frame_name") or frame.name == element.get("frame_name"))
        ]
        if len(matches) == 1:
            return matches[0]
        raise PlaywrightComputerError("the element's frame is no longer uniquely available")

    async def _first_unique(self, locator: Any) -> Any | None:
        try:
            count = await locator.count()
        except Exception:
            return None
        if count == 1:
            return locator
        return None

    async def _resolve_element(self, element: dict[str, Any]) -> Any:
        frame = await self._frame_for_element(element)
        probe_id = element.get("probe_id")
        if probe_id:
            locator = await self._first_unique(
                frame.locator(f'[data-tier-browser-id="{probe_id}"]')
            )
            if locator is not None:
                return locator
        attributes = element.get("attributes", {})
        for key in ("data-testid", "data-test", "data-qa", "data-cy"):
            value = attributes.get(key)
            if value:
                locator = await self._first_unique(frame.locator(f'[{key}="{value}"]'))
                if locator is not None:
                    return locator
        if attributes.get("id"):
            locator = await self._first_unique(frame.locator(f'#{attributes["id"]}'))
            if locator is not None:
                return locator
        role = element.get("role")
        name = element.get("name")
        if role and name:
            try:
                locator = await self._first_unique(frame.get_by_role(role, name=name, exact=True))
                if locator is not None:
                    return locator
            except Exception:
                pass
        if attributes.get("placeholder"):
            locator = await self._first_unique(
                frame.get_by_placeholder(attributes["placeholder"], exact=True)
            )
            if locator is not None:
                return locator
        if attributes.get("name"):
            locator = await self._first_unique(
                frame.locator(f'[name="{attributes["name"]}"]')
            )
            if locator is not None:
                return locator
        css_path = element.get("css_path")
        if css_path and ">>>" not in css_path:
            locator = await self._first_unique(frame.locator(css_path))
            if locator is not None:
                return locator
        if name:
            try:
                locator = await self._first_unique(frame.get_by_text(name, exact=True))
                if locator is not None:
                    return locator
            except Exception:
                pass
        raise PlaywrightComputerError(
            f"element {element.get('index')} no longer resolves uniquely; observe and replan"
        )

    async def _navigate(self, url: str) -> None:
        allowed, reason = url_allowed(url, self.config, resolve_dns=True)
        if not allowed:
            raise PlaywrightComputerError(reason)
        response = await self.current_page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.config["policy"]["navigation_timeout_ms"],
        )
        if response is not None:
            self.ledger.append(
                "browser.navigation.response",
                detail={"url": response.url, "status": response.status, "ok": response.ok},
            )

    def _takeover_active(self) -> bool:
        lease = self.takeover_lease.read()
        if not lease:
            return False
        if float(lease.get("expires_unix", 0)) <= time.time():
            self.takeover_lease.release()
            self.ledger.append(
                "browser.takeover.expired",
                detail={"lease_id": lease.get("lease_id")},
            )
            return False
        return True

    async def takeover(self, *, seconds: float | None = None) -> dict[str, Any]:
        if not self.config["takeover"]["enabled"]:
            raise PlaywrightComputerError("human takeover is disabled")
        if self._takeover_active():
            raise PlaywrightComputerError("human takeover is already active")
        duration = min(
            float(seconds or self.config["takeover"]["lease_seconds"]),
            float(self.config["takeover"]["lease_seconds"]),
        )
        lease: dict[str, Any] = {
            "schema": TAKEOVER_SCHEMA,
            "computer_id": self.config["id"],
            "lease_id": "takeover-" + secrets.token_hex(12),
            "owner": "human",
            "claimed_at": now_utc(),
            "expires_unix": time.time() + duration,
            "expires_in_seconds": duration,
            "page_id": self.current_state.get("page_id") if self.current_state else None,
            "url": self.current_state.get("url") if self.current_state else None,
        }
        lease["lease_sha256"] = hash_json(lease)
        self.takeover_lease.claim(lease)
        self.ledger.append(
            "browser.takeover.claimed",
            state_id=self.current_state.get("state_id") if self.current_state else None,
            detail={"lease_id": lease["lease_id"], "expires_in_seconds": duration},
        )
        return lease

    async def release_takeover(self, lease_id: str) -> dict[str, Any]:
        lease = self.takeover_lease.read()
        if not lease:
            raise PlaywrightComputerError("no human takeover is active")
        if lease.get("lease_id") != lease_id:
            raise PlaywrightComputerError("takeover lease identity does not match")
        self.takeover_lease.release()
        state = await self.observe()
        self.ledger.append(
            "browser.takeover.released",
            state_id=state["state_id"],
            detail={"lease_id": lease_id},
        )
        return {"released": True, "lease_id": lease_id, "state_id": state["state_id"]}

    async def execute(self, raw_action: dict[str, Any]) -> dict[str, Any]:
        if self._takeover_active():
            raise PlaywrightComputerError("agent actions are paused while human takeover is active")
        action = validate_action(raw_action)
        before = self.current_state or await self.observe()
        if action["op"] in {"click", "fill", "type", "press", "select", "upload"}:
            if not action["expected_state_id"]:
                raise PlaywrightComputerError(
                    f"action {action['op']} requires expected_state_id from the observed page"
                )
        if action["expected_state_id"] and action["expected_state_id"] != before["state_id"]:
            raise PlaywrightComputerError(
                "action is stale: expected_state_id does not match the active browser state"
            )
        classification, reasons = classify_action(action, before, self.config)
        if action["op"] == "javascript" and not self.config["policy"]["allow_javascript"]:
            raise PlaywrightComputerError("page JavaScript execution is disabled")
        if action["op"] == "upload" and not self.config["policy"]["allow_upload"]:
            raise PlaywrightComputerError("file upload is disabled")
        approval_required = (
            classification in {"external_write", "privileged"}
            and self.config["policy"]["external_write_requires_approval"]
        ) or (
            classification == "sensitive_input"
            and self.config["policy"]["sensitive_input_requires_approval"]
        )
        if approval_required and not approval_valid(action.get("approval_token"), self.approval_token):
            raise PlaywrightComputerError(
                f"{classification} action requires the configured approval token"
            )
        self.ledger.append(
            "browser.action.started",
            state_id=before["state_id"],
            action_id=action["action_id"],
            detail={
                "action": redact_action(action),
                "classification": classification,
                "classification_reasons": reasons,
            },
        )
        result: dict[str, Any] = {}
        error: str | None = None
        started = time.perf_counter()
        try:
            op = action["op"]
            args = action["args"]
            target = element_for_action(before, action)
            locator = await self._resolve_element(target) if target is not None else None
            if op == "observe":
                pass
            elif op == "navigate":
                await self._navigate(str(args["url"]))
            elif op == "back":
                await self.current_page.go_back(wait_until="domcontentloaded")
            elif op == "open_tab":
                url = str(args.get("url", "about:blank"))
                allowed, reason = url_allowed(url, self.config, resolve_dns=True)
                if not allowed:
                    raise PlaywrightComputerError(reason)
                self.current_page = await self.context.new_page()
                self._attach_page(self.current_page)
                await self.current_page.goto(url, wait_until="domcontentloaded")
            elif op == "switch_tab":
                page_id = str(args["page_id"])
                matches = [
                    page for page in self.context.pages if self._page_id(page) == page_id and not page.is_closed()
                ]
                if len(matches) != 1:
                    raise PlaywrightComputerError(f"no unique open tab has page_id {page_id!r}")
                self.current_page = matches[0]
                await self.current_page.bring_to_front()
            elif op == "close_tab":
                closing = self.current_page
                await closing.close()
                pages = [page for page in self.context.pages if not page.is_closed()]
                self.current_page = pages[-1] if pages else await self.context.new_page()
                self._attach_page(self.current_page)
            elif op == "click":
                if target and target.get("disabled"):
                    raise PlaywrightComputerError("target element is disabled")
                await locator.click()
                result["clicked_index"] = target["index"]
            elif op == "fill":
                await locator.fill(str(args.get("text", "")))
                result["filled_index"] = target["index"]
            elif op == "type":
                await locator.press_sequentially(
                    str(args.get("text", "")), delay=float(args.get("delay_ms", 20))
                )
                result["typed_index"] = target["index"]
            elif op == "press":
                await locator.press(str(args["key"]))
                result["pressed_index"] = target["index"]
            elif op == "select":
                if "label" in args:
                    selected = await locator.select_option(label=str(args["label"]))
                elif "value" in args:
                    selected = await locator.select_option(value=str(args["value"]))
                elif "option_index" in args:
                    selected = await locator.select_option(index=int(args["option_index"]))
                else:
                    raise PlaywrightComputerError("select requires label, value, or option_index")
                result["selected"] = selected
            elif op == "scroll":
                amount = int(args.get("amount", self.config["viewport"]["height"]))
                direction = str(args.get("direction", "down"))
                if direction not in {"up", "down"}:
                    raise PlaywrightComputerError("scroll direction must be up or down")
                await self.current_page.evaluate(
                    "amount => window.scrollBy(0, amount)", amount if direction == "down" else -amount
                )
                result["scrolled"] = {"direction": direction, "amount": amount}
            elif op == "wait":
                seconds = min(max(float(args.get("seconds", 1.0)), 0.0), 60.0)
                await asyncio.sleep(seconds)
                result["waited_seconds"] = seconds
            elif op == "extract":
                selector = str(args.get("selector", "body"))
                content = await self.current_page.locator(selector).inner_text(timeout=5000)
                path = self.extracts_dir / f"extract-{int(time.time())}-{secrets.token_hex(4)}.txt"
                path.write_text(content, encoding="utf-8", newline="\n")
                result["artifact"] = {
                    "path": str(path.relative_to(self.root)),
                    "bytes": path.stat().st_size,
                    "sha256": hash_file(path),
                }
            elif op == "screenshot":
                path = self.screenshots_dir / f"screenshot-{int(time.time())}-{secrets.token_hex(4)}.png"
                await self.current_page.screenshot(
                    path=str(path), full_page=bool(args.get("full_page", False)), animations="disabled"
                )
                result["artifact"] = {
                    "path": str(path.relative_to(self.root)),
                    "bytes": path.stat().st_size,
                    "sha256": hash_file(path),
                }
            elif op == "upload":
                relative = str(args["path"])
                upload = safe_relative_path(self.workspace, relative, "action.args.path")
                if not upload.is_file():
                    raise PlaywrightComputerError(f"upload file does not exist: {relative}")
                await locator.set_input_files(str(upload))
                result["uploaded"] = {
                    "path": str(upload.relative_to(self.workspace)),
                    "bytes": upload.stat().st_size,
                    "sha256": hash_file(upload),
                }
            elif op == "javascript":
                value = await self.current_page.evaluate(str(args["script"]), args.get("argument"))
                result["javascript_result"] = value
            elif op == "done":
                result["done"] = True
                result["summary"] = str(args.get("summary", ""))
            else:
                raise PlaywrightComputerError(f"unsupported action {op}")
            after = await self.observe()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                after = await self.observe()
            except Exception:
                after = before
        receipt_without_hash: dict[str, Any] = {
            "schema": ACTION_RECEIPT_SCHEMA,
            "computer_id": self.config["id"],
            "action_id": action["action_id"],
            "action": redact_action(action),
            "classification": classification,
            "classification_reasons": reasons,
            "approval_required": approval_required,
            "approval_present": bool(action.get("approval_token")),
            "started_state_id": before["state_id"],
            "completed_state_id": after["state_id"],
            "started_at": now_utc(),
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "result": result,
            "error": error,
        }
        receipt = {
            **receipt_without_hash,
            "receipt_sha256": hash_json(receipt_without_hash),
        }
        path = self.artifacts / "actions" / f"{action['action_id']}.json"
        if path.exists():
            raise PlaywrightComputerError(f"append-only action receipt already exists: {path}")
        atomic_json(path, receipt)
        self.ledger.append(
            "browser.action.completed" if error is None else "browser.action.failed",
            state_id=after["state_id"],
            action_id=action["action_id"],
            detail={
                "receipt_path": str(path.relative_to(self.root)),
                "receipt_sha256": receipt["receipt_sha256"],
                "error": error,
            },
        )
        return receipt

    async def execute_batch(self, raw_actions: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(raw_actions, list) or not raw_actions:
            raise PlaywrightComputerError("actions must be a non-empty array")
        if len(raw_actions) > self.config["policy"]["max_actions_per_batch"]:
            raise PlaywrightComputerError("action batch exceeds max_actions_per_batch")
        receipts: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        for index, raw in enumerate(raw_actions):
            before = self.current_state or await self.observe()
            receipt = await self.execute(raw)
            receipts.append(receipt)
            if receipt["error"]:
                stopped_reason = "action failed"
                break
            if receipt["result"].get("done"):
                stopped_reason = "task declared done"
                break
            after = self.current_state
            reason = batch_break_reason(before, after)
            if reason and index < len(raw_actions) - 1:
                stopped_reason = reason
                self.ledger.append(
                    "browser.batch.interrupted",
                    state_id=after["state_id"],
                    detail={
                        "after_action_id": receipt["action_id"],
                        "reason": reason,
                        "remaining_actions": len(raw_actions) - index - 1,
                    },
                )
                break
            if index < len(raw_actions) - 1:
                await asyncio.sleep(self.config["policy"]["wait_between_actions_ms"] / 1000.0)
        return {
            "ok": all(receipt["error"] is None for receipt in receipts),
            "receipts": receipts,
            "stopped_reason": stopped_reason,
            "state": self.current_state,
        }

    async def health(self) -> dict[str, Any]:
        page = self.current_page
        page_alive = bool(page is not None and not page.is_closed())
        if page_alive:
            try:
                await page.evaluate("1 + 1")
            except Exception:
                page_alive = False
        return {
            "ok": bool(self.started and not self.closed and page_alive),
            "computer_id": self.config["id"],
            "config_sha256": self.config_sha256,
            "mode": self.config["mode"],
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "page_id": self._page_id(page) if page_alive else None,
            "url": page.url if page_alive else None,
            "state_id": self.current_state.get("state_id") if self.current_state else None,
            "takeover_active": self._takeover_active(),
            "event_ledger": self.ledger.verify(),
        }

    async def verify(self) -> dict[str, Any]:
        errors: list[str] = []
        ledger = self.ledger.verify()
        if not ledger["ok"]:
            errors.extend(ledger["errors"])
        for path in sorted((self.artifacts / "actions").glob("*.json")):
            value = load_json(path)
            observed = value.get("receipt_sha256") if isinstance(value, dict) else None
            expected = hash_json({key: item for key, item in value.items() if key != "receipt_sha256"})
            if observed != expected:
                errors.append(f"action receipt hash does not verify: {path.name}")
        return {
            "ok": not errors,
            "computer_id": self.config["id"],
            "config_sha256": self.config_sha256,
            "events": ledger,
            "errors": errors,
        }

    async def _close_partial(self) -> None:
        try:
            if self.context is not None and self.config["trace"]:
                await self.context.tracing.stop()
        except Exception:
            pass
        try:
            if self.context is not None:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser is not None:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass

    async def close(self) -> dict[str, Any]:
        if self.closed:
            return {"closed": True, "computer_id": self.config["id"]}
        self.closed = True
        trace_path = self.traces_dir / f"trace-{int(time.time())}.zip"
        storage_state = self._storage_state_path()
        try:
            if storage_state is not None and self.context is not None:
                storage_state.parent.mkdir(parents=True, exist_ok=True)
                await self.context.storage_state(path=str(storage_state))
                if os.name != "nt":
                    storage_state.chmod(0o600)
                self.ledger.append(
                    "browser.storage_state.saved",
                    detail={
                        "path": str(storage_state.relative_to(self.root)),
                        "bytes": storage_state.stat().st_size,
                        "sha256": hash_file(storage_state),
                    },
                )
            if self.context is not None and self.config["trace"]:
                await self.context.tracing.stop(path=str(trace_path))
        finally:
            await self._close_partial()
            self.takeover_lease.release()
            self.process_lease.release()
        self.ledger.append(
            "computer.closed",
            state_id=self.current_state.get("state_id") if self.current_state else None,
            detail={
                "trace": (
                    {
                        "path": str(trace_path.relative_to(self.root)),
                        "bytes": trace_path.stat().st_size,
                        "sha256": hash_file(trace_path),
                    }
                    if trace_path.exists()
                    else None
                )
            },
        )
        return {
            "closed": True,
            "computer_id": self.config["id"],
            "trace_path": str(trace_path) if trace_path.exists() else None,
        }
