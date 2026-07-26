"""CLI for the Sovereign Desktop Execution Plane."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .sovereign_cache import (
    cache_inventory_from_registry,
    restore_slot_cache,
    save_slot_cache,
)
from .sovereign_common import PlaneError, hash_json, load_json, write_json
from .sovereign_context import (
    materialize_context_pack,
    pack_metrics,
    prefix_fingerprint,
    verify_context_receipt,
)
from .sovereign_plan import compile_campaigns, compile_plan, verify_plan
from .sovereign_schema import validate_manifest


def _manifest(path: Path) -> Any:
    return load_json(path)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tierplane",
        description=(
            "Compile, materialize, and verify attention-first sovereign desktop execution"
        ),
    )
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--plan", type=Path, required=True)

    key = commands.add_parser("context-key")
    key.add_argument("--manifest", type=Path, required=True)
    key.add_argument("--runtime", required=True)
    key.add_argument("--pack", required=True)

    materialize = commands.add_parser("materialize")
    materialize.add_argument("--manifest", type=Path, required=True)
    materialize.add_argument("--pack", required=True)
    materialize.add_argument("--repo", type=Path, required=True)
    materialize.add_argument("--out-root", type=Path, required=True)

    verify_context = commands.add_parser("verify-context")
    verify_context.add_argument("--directory", type=Path, required=True)

    campaigns = commands.add_parser("campaigns")
    campaigns.add_argument("--manifest", type=Path, required=True)
    campaigns.add_argument("--out-dir", type=Path)

    def cache_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--runtime", required=True)
        command.add_argument("--pack", required=True)
        command.add_argument("--server", required=True)
        command.add_argument("--slot", type=int, default=0)
        command.add_argument("--filename", required=True)
        command.add_argument("--state-dir", type=Path, required=True)
        command.add_argument("--timeout", type=float, default=30.0)
        command.add_argument("--unsafe-network", action="store_true")
        command.add_argument("--dry-run", action="store_true")

    cache_save = commands.add_parser("cache-save")
    cache_common(cache_save)
    cache_restore = commands.add_parser("cache-restore")
    cache_common(cache_restore)

    inventory = commands.add_parser("cache-inventory")
    inventory.add_argument("--manifest", type=Path, required=True)
    inventory.add_argument("--state-dir", type=Path, required=True)
    inventory.add_argument("--out", type=Path)
    return result


def _write_campaigns(bundle: dict[str, Any], out_dir: Path | None) -> None:
    if out_dir is None:
        write_json(None, bundle)
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {
        "schema": bundle["schema"],
        "plane_id": bundle["plane_id"],
        "manifest_sha256": bundle["manifest_sha256"],
        "campaigns": [],
        "blocked": bundle["blocked"],
    }
    for campaign in bundle["campaigns"]:
        path = out_dir / f"{campaign['id']}.json"
        write_json(path, campaign)
        index["campaigns"].append({"id": campaign["id"], "path": path.name})
    write_json(out_dir / "index.json", index)
    print(
        json.dumps(
            {
                "ok": True,
                "campaigns": len(bundle["campaigns"]),
                "blocked": len(bundle["blocked"]),
                "out_dir": str(out_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "verify-context":
            errors = verify_context_receipt(args.directory)
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))

        raw = _manifest(args.manifest)
        if args.command == "validate":
            manifest = validate_manifest(raw)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "plane_id": manifest["id"],
                        "resources": len(manifest["resources"]),
                        "runtimes": len(manifest["runtimes"]),
                        "context_packs": len(manifest["context_packs"]),
                        "jobs": len(manifest["jobs"]),
                        "manifest_sha256": hash_json(manifest),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "plan":
            write_json(args.out, compile_plan(raw))
            return 0

        if args.command == "verify":
            errors = verify_plan(raw, load_json(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))

        if args.command == "context-key":
            manifest = validate_manifest(raw)
            runtimes = {row["id"]: row for row in manifest["runtimes"]}
            packs = {row["id"]: row for row in manifest["context_packs"]}
            if args.runtime not in runtimes:
                raise PlaneError(f"unknown runtime: {args.runtime}")
            if args.pack not in packs:
                raise PlaneError(f"unknown context pack: {args.pack}")
            metrics = pack_metrics(packs[args.pack])
            print(
                json.dumps(
                    {
                        "runtime": args.runtime,
                        "pack": args.pack,
                        "prefix_fingerprint": prefix_fingerprint(
                            runtimes[args.runtime], packs[args.pack]
                        ),
                        "pack_fingerprint": metrics.pack_fingerprint,
                        "cacheable_tokens": metrics.cacheable_tokens,
                        "dynamic_tokens": metrics.dynamic_tokens,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "materialize":
            receipt = materialize_context_pack(
                raw, args.pack, args.repo.resolve(), args.out_root.resolve()
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0

        if args.command == "campaigns":
            _write_campaigns(compile_campaigns(raw), args.out_dir)
            return 0

        if args.command == "cache-save":
            receipt = save_slot_cache(
                raw,
                runtime_id=args.runtime,
                pack_id=args.pack,
                server_url=args.server,
                slot=args.slot,
                filename=args.filename,
                state_dir=args.state_dir,
                timeout=args.timeout,
                unsafe_network=args.unsafe_network,
                dry_run=args.dry_run,
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0

        if args.command == "cache-restore":
            receipt = restore_slot_cache(
                raw,
                runtime_id=args.runtime,
                pack_id=args.pack,
                server_url=args.server,
                slot=args.slot,
                filename=args.filename,
                state_dir=args.state_dir,
                timeout=args.timeout,
                unsafe_network=args.unsafe_network,
                dry_run=args.dry_run,
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0

        if args.command == "cache-inventory":
            write_json(args.out, cache_inventory_from_registry(raw, args.state_dir))
            return 0
    except (PlaneError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierplane: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
