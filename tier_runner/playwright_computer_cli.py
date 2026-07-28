"""Operator CLI for Manus-shaped Playwright browser computers."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .playwright_computer_common import (
    EventLedger,
    PlaywrightComputerError,
    hash_json,
    load_json,
    write_json,
)
from .playwright_computer_protocol import validate_config
from .playwright_computer_runtime import PlaywrightComputer
from .playwright_computer_server import serve_browser_computer


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tierbrowser",
        description=(
            "Run a task-scoped Playwright browser computer with indexed DOM state, "
            "screenshots, traces, stale-state checks, approvals, and human takeover."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--config", type=Path, required=True)
    validate.add_argument("--root", type=Path)

    serve = commands.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--root", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8788)
    serve.add_argument("--unsafe-network", action="store_true")
    serve.add_argument("--control-token-env", default="TIER_BROWSER_TOKEN")
    serve.add_argument("--approval-token-env", default="TIER_BROWSER_APPROVAL_TOKEN")

    run = commands.add_parser("run-batch")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--root", type=Path, required=True)
    run.add_argument("--actions", type=Path, required=True)
    run.add_argument("--approval-token-env", default="TIER_BROWSER_APPROVAL_TOKEN")
    run.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--config", type=Path, required=True)
    verify.add_argument("--root", type=Path, required=True)

    for name in ("status", "observe", "events", "takeover", "release", "shutdown", "act", "batch"):
        command = commands.add_parser(name)
        command.add_argument("--url", default="http://127.0.0.1:8788")
        command.add_argument("--token-env", default="TIER_BROWSER_TOKEN")
        if name == "events":
            command.add_argument("--after", type=int, default=0)
        elif name == "takeover":
            command.add_argument("--seconds", type=float)
        elif name == "release":
            command.add_argument("--lease-id", required=True)
        elif name == "act":
            command.add_argument("--action", type=Path, required=True)
        elif name == "batch":
            command.add_argument("--actions", type=Path, required=True)
    return root


def _loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _token(name: str, *, generate: bool = False) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if generate:
        value = secrets.token_urlsafe(32)
        print(
            f"{name} was unset. Generated an ephemeral control token for this process:\n{value}",
            file=sys.stderr,
        )
        return value
    raise PlaywrightComputerError(f"required environment variable is unset: {name}")


def _request(
    *,
    url: str,
    token: str,
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url.rstrip("/") + path,
        method=method,
        data=data,
        headers={
            "X-Tier-Browser-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error")
        except Exception:
            detail = str(exc)
        raise PlaywrightComputerError(f"browser server rejected request: {detail}") from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise PlaywrightComputerError(f"browser server request failed: {exc}") from exc


async def _run_batch(args: argparse.Namespace) -> dict[str, Any]:
    raw_config = load_json(args.config)
    computer = PlaywrightComputer(
        raw_config,
        root=args.root,
        approval_token=os.environ.get(args.approval_token_env),
    )
    await computer.start()
    try:
        payload = load_json(args.actions)
        actions = payload.get("actions") if isinstance(payload, dict) else payload
        result = await computer.execute_batch(actions)
        result["verification"] = await computer.verify()
        return result
    finally:
        await computer.close()


async def _verify(args: argparse.Namespace) -> dict[str, Any]:
    config = validate_config(load_json(args.config), root=args.root)
    ledger = EventLedger(args.root.resolve() / config["paths"]["artifacts"] / "events.jsonl", config["id"])
    errors: list[str] = []
    ledger_report = ledger.verify()
    if not ledger_report["ok"]:
        errors.extend(ledger_report["errors"])
    action_root = args.root.resolve() / config["paths"]["artifacts"] / "actions"
    for path in sorted(action_root.glob("*.json")) if action_root.exists() else []:
        value = load_json(path)
        expected = hash_json({key: item for key, item in value.items() if key != "receipt_sha256"})
        if value.get("receipt_sha256") != expected:
            errors.append(f"action receipt hash does not verify: {path.name}")
    return {
        "ok": not errors,
        "computer_id": config["id"],
        "config_sha256": hash_json(config),
        "ledger": ledger_report,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            config = validate_config(load_json(args.config), root=args.root)
            write_json(None, {"ok": True, "config": config, "config_sha256": hash_json(config)})
            return 0
        if args.command == "serve":
            if not 0 <= args.port <= 65535:
                raise PlaywrightComputerError("port must be between 0 and 65535")
            if not _loopback(args.host) and not args.unsafe_network:
                raise PlaywrightComputerError("non-loopback binding requires --unsafe-network")
            control_token = _token(args.control_token_env, generate=True)
            approval = os.environ.get(args.approval_token_env)
            computer = PlaywrightComputer(
                load_json(args.config),
                root=args.root,
                approval_token=approval,
            )
            serve_browser_computer(
                computer,
                host=args.host,
                port=args.port,
                control_token=control_token,
            )
            return 0
        if args.command == "run-batch":
            result = asyncio.run(_run_batch(args))
            write_json(args.out, result)
            return 0 if result["ok"] and result["verification"]["ok"] else 1
        if args.command == "verify":
            result = asyncio.run(_verify(args))
            write_json(None, result)
            return 0 if result["ok"] else 1
        token = _token(args.token_env)
        if args.command == "status":
            result = _request(url=args.url, token=token, path="/healthz")
        elif args.command == "observe":
            result = _request(url=args.url, token=token, path="/observe", method="POST", body={})
        elif args.command == "events":
            result = _request(url=args.url, token=token, path=f"/events?after={args.after}")
        elif args.command == "takeover":
            result = _request(
                url=args.url,
                token=token,
                path="/takeover",
                method="POST",
                body={"seconds": args.seconds},
            )
        elif args.command == "release":
            result = _request(
                url=args.url,
                token=token,
                path="/takeover/release",
                method="POST",
                body={"lease_id": args.lease_id},
            )
        elif args.command == "shutdown":
            result = _request(url=args.url, token=token, path="/shutdown", method="POST", body={})
        elif args.command == "act":
            result = _request(
                url=args.url,
                token=token,
                path="/act",
                method="POST",
                body={"action": load_json(args.action)},
            )
        elif args.command == "batch":
            payload = load_json(args.actions)
            actions = payload.get("actions") if isinstance(payload, dict) else payload
            result = _request(
                url=args.url,
                token=token,
                path="/batch",
                method="POST",
                body={"actions": actions},
            )
        else:
            raise PlaywrightComputerError(f"unsupported command {args.command}")
        write_json(None, result)
        return 0 if result.get("ok", True) else 1
    except (PlaywrightComputerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierbrowser: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
