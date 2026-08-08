"""Strict configuration, action, URL, and side-effect policy for browser computers."""
from __future__ import annotations

import hmac
import ipaddress
from pathlib import Path
import re
import socket
from typing import Any
from urllib.parse import urlparse

from .playwright_computer_common import (
    PlaywrightComputerError,
    hash_json,
    safe_id,
    safe_relative_path,
)

CONFIG_SCHEMA = "tier-bench/playwright-computer@1"
ACTION_SCHEMA = "tier-bench/playwright-action@1"
STATE_SCHEMA = "tier-bench/playwright-state@1"
ACTION_RECEIPT_SCHEMA = "tier-bench/playwright-action-receipt@1"
TAKEOVER_SCHEMA = "tier-bench/playwright-takeover@1"

MODES = {"isolated", "persistent", "cdp"}
OPS = {
    "observe",
    "navigate",
    "back",
    "open_tab",
    "switch_tab",
    "close_tab",
    "click",
    "fill",
    "type",
    "press",
    "select",
    "scroll",
    "wait",
    "extract",
    "screenshot",
    "upload",
    "javascript",
    "done",
}
READ_OPS = {
    "observe",
    "navigate",
    "back",
    "open_tab",
    "switch_tab",
    "close_tab",
    "scroll",
    "wait",
    "extract",
    "screenshot",
}
TARGET_OPS = {"click", "fill", "type", "press", "select", "upload"}

_DEFAULT_SIDE_EFFECT_WORDS = {
    "buy",
    "checkout",
    "confirm",
    "delete",
    "remove",
    "send",
    "submit",
    "publish",
    "post",
    "pay",
    "purchase",
    "order",
    "book",
    "reserve",
    "transfer",
    "withdraw",
    "sign",
    "accept",
    "agree",
    "unsubscribe",
    "cancel subscription",
}
_SENSITIVE_WORDS = {
    "password",
    "passcode",
    "credit card",
    "card number",
    "cvv",
    "cvc",
    "social security",
    "ssn",
    "api key",
    "secret",
    "token",
    "private key",
}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlaywrightComputerError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlaywrightComputerError(f"{label} must be an array")
    return value


def _text(value: Any, label: str, *, limit: int = 1000, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        suffix = "" if allow_empty else " non-empty"
        raise PlaywrightComputerError(f"{label} must be a{suffix} string of at most {limit} chars")
    return value.strip() if not allow_empty else value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PlaywrightComputerError(f"{label} must be boolean")
    return value


def _integer(value: Any, label: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PlaywrightComputerError(f"{label} must be an integer between {low} and {high}")
    return value


def _number(value: Any, label: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlaywrightComputerError(f"{label} must be numeric")
    result = float(value)
    if not low <= result <= high:
        raise PlaywrightComputerError(f"{label} must be between {low} and {high}")
    return result


def _domains(values: Any, label: str) -> list[str]:
    result: list[str] = []
    for index, value in enumerate(_array(values, label)):
        domain = _text(value, f"{label}[{index}]", limit=253).lower().rstrip(".")
        if "://" in domain or "/" in domain:
            raise PlaywrightComputerError(f"{label}[{index}] must be a hostname pattern")
        if domain.startswith("*."):
            domain = domain[2:]
        if not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise PlaywrightComputerError(f"{label}[{index}] is not a valid hostname pattern")
        result.append(domain)
    return sorted(set(result))


def validate_config(raw: Any, *, root: Path | None = None) -> dict[str, Any]:
    config = _object(raw, "computer")
    if config.get("schema") != CONFIG_SCHEMA:
        raise PlaywrightComputerError(f"computer.schema must be {CONFIG_SCHEMA}")
    identifier = safe_id(config.get("id"), "computer.id")
    mode = _text(config.get("mode", "persistent"), "computer.mode", limit=20)
    if mode not in MODES:
        raise PlaywrightComputerError(f"computer.mode must be one of {sorted(MODES)}")
    viewport = _object(config.get("viewport", {}), "computer.viewport")
    policy = _object(config.get("policy", {}), "computer.policy")
    takeover = _object(config.get("takeover", {}), "computer.takeover")
    paths = _object(config.get("paths", {}), "computer.paths")
    normalized_paths = {
        "workspace": _text(paths.get("workspace", "workspace"), "computer.paths.workspace"),
        "profile": _text(paths.get("profile", "profile"), "computer.paths.profile"),
        "downloads": _text(paths.get("downloads", "downloads"), "computer.paths.downloads"),
        "artifacts": _text(paths.get("artifacts", "artifacts"), "computer.paths.artifacts"),
        "secrets": _text(paths.get("secrets", "secrets"), "computer.paths.secrets"),
    }
    if root is not None:
        for key, value in normalized_paths.items():
            safe_relative_path(root, value, f"computer.paths.{key}")
    cdp_url = config.get("cdp_url")
    if mode == "cdp":
        cdp_url = _text(cdp_url, "computer.cdp_url", limit=2000)
        parsed_cdp = urlparse(cdp_url)
        if parsed_cdp.scheme not in {"http", "https", "ws", "wss"}:
            raise PlaywrightComputerError("computer.cdp_url must use http, https, ws, or wss")
    elif cdp_url is not None:
        raise PlaywrightComputerError("computer.cdp_url is accepted only in cdp mode")
    start_url = _text(
        config.get("start_url", "about:blank"),
        "computer.start_url",
        limit=4000,
    )
    allowed_schemes = sorted(
        {
            _text(value, "computer.allowed_schemes", limit=20).lower()
            for value in _array(
                config.get("allowed_schemes", ["https", "http", "about", "data"]),
                "computer.allowed_schemes",
            )
        }
    )
    unknown_schemes = set(allowed_schemes) - {"http", "https", "about", "data", "file"}
    if unknown_schemes:
        raise PlaywrightComputerError(
            f"computer.allowed_schemes has unsupported values: {sorted(unknown_schemes)}"
        )
    result = {
        "schema": CONFIG_SCHEMA,
        "id": identifier,
        "title": _text(config.get("title", identifier), "computer.title", limit=300),
        "mode": mode,
        "browser": "chromium",
        "headless": _boolean(config.get("headless", False), "computer.headless"),
        "start_url": start_url,
        "cdp_url": cdp_url,
        "paths": normalized_paths,
        "viewport": {
            "width": _integer(viewport.get("width", 1280), "computer.viewport.width", low=320, high=7680),
            "height": _integer(viewport.get("height", 900), "computer.viewport.height", low=240, high=4320),
        },
        "locale": (
            _text(config.get("locale"), "computer.locale", limit=40)
            if config.get("locale") is not None
            else None
        ),
        "user_agent": (
            _text(config.get("user_agent"), "computer.user_agent", limit=1000)
            if config.get("user_agent") is not None
            else None
        ),
        "allowed_schemes": allowed_schemes,
        "allowed_domains": _domains(config.get("allowed_domains", []), "computer.allowed_domains"),
        "blocked_domains": _domains(config.get("blocked_domains", []), "computer.blocked_domains"),
        "deny_private_networks": _boolean(
            config.get("deny_private_networks", True), "computer.deny_private_networks"
        ),
        "storage_state_file": (
            _text(config.get("storage_state_file"), "computer.storage_state_file")
            if config.get("storage_state_file") is not None
            else None
        ),
        "trace": _boolean(config.get("trace", True), "computer.trace"),
        "record_video": _boolean(config.get("record_video", False), "computer.record_video"),
        "force_open_shadow_dom": _boolean(
            config.get("force_open_shadow_dom", False), "computer.force_open_shadow_dom"
        ),
        "policy": {
            "max_actions_per_batch": _integer(
                policy.get("max_actions_per_batch", 10),
                "computer.policy.max_actions_per_batch",
                low=1,
                high=50,
            ),
            "default_timeout_ms": _integer(
                policy.get("default_timeout_ms", 10000),
                "computer.policy.default_timeout_ms",
                low=100,
                high=300000,
            ),
            "navigation_timeout_ms": _integer(
                policy.get("navigation_timeout_ms", 45000),
                "computer.policy.navigation_timeout_ms",
                low=1000,
                high=600000,
            ),
            "wait_between_actions_ms": _integer(
                policy.get("wait_between_actions_ms", 250),
                "computer.policy.wait_between_actions_ms",
                low=0,
                high=60000,
            ),
            "viewport_expansion": _integer(
                policy.get("viewport_expansion", 500),
                "computer.policy.viewport_expansion",
                low=-1,
                high=100000,
            ),
            "max_visible_text_chars": _integer(
                policy.get("max_visible_text_chars", 24000),
                "computer.policy.max_visible_text_chars",
                low=1000,
                high=1000000,
            ),
            "highlight_elements": _boolean(
                policy.get("highlight_elements", True),
                "computer.policy.highlight_elements",
            ),
            "external_write_requires_approval": _boolean(
                policy.get("external_write_requires_approval", True),
                "computer.policy.external_write_requires_approval",
            ),
            "sensitive_input_requires_approval": _boolean(
                policy.get("sensitive_input_requires_approval", True),
                "computer.policy.sensitive_input_requires_approval",
            ),
            "allow_javascript": _boolean(
                policy.get("allow_javascript", False), "computer.policy.allow_javascript"
            ),
            "allow_upload": _boolean(
                policy.get("allow_upload", True), "computer.policy.allow_upload"
            ),
            "allow_download": _boolean(
                policy.get("allow_download", True), "computer.policy.allow_download"
            ),
            "side_effect_words": sorted(
                {
                    _text(value, "computer.policy.side_effect_words", limit=80).lower()
                    for value in _array(
                        policy.get("side_effect_words", sorted(_DEFAULT_SIDE_EFFECT_WORDS)),
                        "computer.policy.side_effect_words",
                    )
                }
            ),
        },
        "takeover": {
            "enabled": _boolean(takeover.get("enabled", True), "computer.takeover.enabled"),
            "lease_seconds": _number(
                takeover.get("lease_seconds", 600.0),
                "computer.takeover.lease_seconds",
                low=1.0,
                high=86400.0,
            ),
        },
    }
    if result["storage_state_file"] is not None and root is not None:
        safe_relative_path(
            safe_relative_path(root, result["paths"]["secrets"], "computer.paths.secrets"),
            result["storage_state_file"],
            "computer.storage_state_file",
        )
    return result


def validate_action(raw: Any) -> dict[str, Any]:
    action = _object(raw, "action")
    if action.get("schema", ACTION_SCHEMA) != ACTION_SCHEMA:
        raise PlaywrightComputerError(f"action.schema must be {ACTION_SCHEMA}")
    op = _text(action.get("op"), "action.op", limit=40)
    if op not in OPS:
        raise PlaywrightComputerError(f"action.op must be one of {sorted(OPS)}")
    args = _object(action.get("args", {}), "action.args")
    expected_state_id = action.get("expected_state_id")
    if expected_state_id is not None:
        expected_state_id = _text(expected_state_id, "action.expected_state_id", limit=64)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_state_id):
            raise PlaywrightComputerError("action.expected_state_id must be SHA-256")
    if op in TARGET_OPS and "index" not in args:
        raise PlaywrightComputerError(f"action {op} requires args.index")
    if "index" in args:
        args = dict(args)
        args["index"] = _integer(args["index"], "action.args.index", low=0, high=1000000)
    normalized = {
        "schema": ACTION_SCHEMA,
        "action_id": safe_id(action.get("action_id"), "action.action_id"),
        "expected_state_id": expected_state_id,
        "op": op,
        "args": args,
        "intent": _text(action.get("intent", op), "action.intent", limit=1000),
        "approval_token": action.get("approval_token"),
    }
    return normalized


def redact_action(action: dict[str, Any]) -> dict[str, Any]:
    result = dict(action)
    result["approval_present"] = bool(result.pop("approval_token", None))
    args = dict(result.get("args", {}))
    if result.get("op") in {"fill", "type"} and "text" in args:
        args["text_sha256"] = hash_json({"text": args.pop("text")})
        args["text_redacted"] = True
    if result.get("op") == "javascript" and "script" in args:
        args["script_sha256"] = hash_json({"script": args.pop("script")})
        args["script_redacted"] = True
    result["args"] = args
    return result


def _domain_matches(hostname: str, patterns: list[str]) -> bool:
    return any(hostname == pattern or hostname.endswith("." + pattern) for pattern in patterns)


def _literal_private(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname in {"localhost", "localhost.localdomain"}
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def url_allowed(url: str, config: dict[str, Any], *, resolve_dns: bool = False) -> tuple[bool, str]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in config["allowed_schemes"]:
        return False, f"scheme {scheme!r} is not allowed"
    if scheme in {"about", "data"}:
        return True, ""
    if scheme == "file":
        return False, "file navigation is disabled by the browser computer policy"
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return False, "URL has no hostname"
    if _domain_matches(hostname, config["blocked_domains"]):
        return False, f"hostname {hostname!r} is blocked"
    if config["allowed_domains"] and not _domain_matches(hostname, config["allowed_domains"]):
        return False, f"hostname {hostname!r} is outside the allowlist"
    if config["deny_private_networks"]:
        if _literal_private(hostname):
            return False, f"hostname {hostname!r} resolves to a private or local target"
        if resolve_dns:
            try:
                addresses = {
                    entry[4][0]
                    for entry in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
                }
            except OSError as exc:
                return False, f"DNS resolution failed: {exc}"
            if any(_literal_private(address) for address in addresses):
                return False, f"hostname {hostname!r} resolves to a private or local address"
    return True, ""


def element_for_action(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any] | None:
    if "index" not in action["args"]:
        return None
    target = int(action["args"]["index"])
    for element in state.get("elements", []):
        if int(element.get("index", -1)) == target:
            return element
    raise PlaywrightComputerError(f"state has no interactive element with index {target}")


def classify_action(
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
                f"{key}={value}" for key, value in (element or {}).get("attributes", {}).items()
            ),
        )
    ).lower()
    if op == "press" and str(action["args"].get("key", "")).lower() in {
        "enter",
        "control+enter",
        "meta+enter",
    }:
        reasons.append("keyboard action can submit the current form")
    if op == "click" and (element or {}).get("input_type") == "submit":
        reasons.append("target is a submit control")
    for phrase in config["policy"]["side_effect_words"]:
        if phrase in haystack:
            reasons.append(f"target or intent contains side-effect phrase {phrase!r}")
    if reasons:
        return "external_write", sorted(set(reasons))
    if op in {"fill", "type"} and any(word in haystack for word in _SENSITIVE_WORDS):
        return "sensitive_input", ["target appears to accept sensitive data"]
    return "interactive", reasons


def approval_valid(provided: Any, expected: str | None) -> bool:
    if expected is None or not isinstance(provided, str):
        return False
    return hmac.compare_digest(provided, expected)


def state_topology(state: dict[str, Any]) -> set[str]:
    return {
        str(element.get("signature"))
        for element in state.get("elements", [])
        if element.get("signature")
    }


def batch_break_reason(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    if before.get("page_id") != after.get("page_id"):
        return "active page changed"
    if before.get("url") != after.get("url"):
        return "URL changed"
    if before.get("tabs") != after.get("tabs"):
        return "tab set changed"
    additions = state_topology(after) - state_topology(before)
    if additions:
        return f"{len(additions)} new interactive element signatures appeared"
    return None
