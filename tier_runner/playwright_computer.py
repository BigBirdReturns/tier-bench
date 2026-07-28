"""Hardened public Playwright computer layered over the core browser runtime."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse
from typing import Any

from . import playwright_computer_runtime as _runtime
from .playwright_computer_common import PlaywrightComputerError
from .playwright_computer_protocol import (
    READ_OPS,
    _SENSITIVE_WORDS,
    element_for_action,
    url_allowed,
)
from .playwright_computer_runtime import PlaywrightComputer as _CorePlaywrightComputer


def _phrase_present(haystack: str, phrase: str) -> bool:
    """Match an effect phrase as words, not as a substring inside another word.

    The early conservative classifier used raw substring tests, so ``accept``
    incorrectly classified ``acceptance contract`` as an external write and
    ``order`` could classify ``reordered``. The public runtime retains the
    conservative vocabulary while binding it to lexical boundaries.
    """
    words = [re.escape(word) for word in phrase.split() if word]
    if not words:
        return False
    pattern = r"(?<![A-Za-z0-9_])" + r"\s+".join(words) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None


def _classify_action_precise(
    action: dict[str, Any], state: dict[str, Any], config: dict[str, Any]
) -> tuple[str, list[str]]:
    op = action["op"]
    reasons: list[str] = []
    if op in READ_OPS or op == "done":
        return "read", reasons
    if op == "javascript":
        return "privileged", ["arbitrary page JavaScript"]
    if op == "upload":
        return "external_write", ["file upload leaves the task computer"]
    element = element_for_action(state, action)
    haystack = " ".join(
        str(value)
        for value in (
            action.get("intent", ""),
            (element or {}).get("name", ""),
            (element or {}).get("text", ""),
            (element or {}).get("role", ""),
            (element or {}).get("tag", ""),
            (element or {}).get("input_type", ""),
            " ".join(
                f"{key}={value}"
                for key, value in (element or {}).get("attributes", {}).items()
            ),
        )
    )
    if op == "press" and str(action["args"].get("key", "")).lower() in {
        "enter",
        "control+enter",
        "meta+enter",
    }:
        reasons.append("keyboard action can submit the current form")
    if op == "click" and (element or {}).get("input_type") == "submit":
        reasons.append("target is a submit control")
    for phrase in config["policy"]["side_effect_words"]:
        if _phrase_present(haystack, phrase):
            reasons.append(f"target or intent contains side-effect phrase {phrase!r}")
    if reasons:
        return "external_write", sorted(set(reasons))
    if op in {"fill", "type"} and any(
        _phrase_present(haystack, word) for word in _SENSITIVE_WORDS
    ):
        return "sensitive_input", ["target appears to accept sensitive data"]
    return "interactive", reasons


# Core receipts and execution remain in the frozen runtime module. Override only
# its classifier lookup with the public hardening policy above.
_runtime.classify_action = _classify_action_precise


class PlaywrightComputer(_CorePlaywrightComputer):
    """Public runtime with request interception, navigation checks, and deduplicated pages.

    The core module contains the durable state and action implementation. This layer
    installs the network boundary before the configured start URL is loaded, rejects
    navigation reached through clicks or scripts as well as explicit ``navigate``
    actions, avoids attaching duplicate event listeners to the same Page, and applies
    lexical side-effect classification.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._attached_pages: set[int] = set()
        self._network_decisions: dict[tuple[str, str, int | None], tuple[bool, str]] = {}

    def _attach_page(self, page: Any) -> None:
        identity = id(page)
        if identity in self._attached_pages:
            return
        self._attached_pages.add(identity)
        super()._attach_page(page)

    async def _network_allowed(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        key = (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)
        if key not in self._network_decisions:
            self._network_decisions[key] = await asyncio.to_thread(
                url_allowed,
                url,
                self.config,
                resolve_dns=True,
            )
        return self._network_decisions[key]

    async def _route_request(self, route: Any, request: Any) -> None:
        allowed, reason = await self._network_allowed(request.url)
        if allowed:
            await route.continue_()
            return
        self.ledger.append(
            "browser.request.blocked",
            detail={
                "url": request.url[:4000],
                "resource_type": request.resource_type,
                "reason": reason,
            },
        )
        await route.abort("blockedbyclient")

    async def start(self) -> dict[str, Any]:
        start_url = self.config["start_url"]
        self.config["start_url"] = "about:blank"
        try:
            await super().start()
        finally:
            self.config["start_url"] = start_url
        await self.context.route("**/*", self._route_request)
        for page in list(self.context.pages):
            self._attach_page(page)
        if start_url != "about:blank":
            await self._navigate(start_url)
            await self.observe()
        return await self.health()

    async def observe(self) -> dict[str, Any]:
        page = self.current_page
        if page is not None and not page.is_closed():
            allowed, reason = await self._network_allowed(page.url)
            if not allowed:
                self.ledger.append(
                    "browser.navigation.blocked",
                    detail={"url": page.url[:4000], "reason": reason},
                )
                try:
                    await page.goto("about:blank", wait_until="domcontentloaded")
                except Exception:
                    pass
                raise PlaywrightComputerError(reason)
        return await super().observe()

    async def _close_partial(self) -> None:
        """Close handles without asking Playwright tracing to stop twice."""
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
