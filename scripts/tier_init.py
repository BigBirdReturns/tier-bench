"""Onboard a repo onto tier-desk: probe the machine, generate arm stanzas.

    python scripts/tier_init.py --repo <path> [--write] [--json]

Dry run (no --write) probes the machine and prints what tooling was found
and which arms a manifest built from that would contain. --write additionally
writes pilot_backends.json, .tier/hands.prompt.txt, and cartridges.json into
<path> -- never outside it, and never clobbering a file this tool did not
itself just decide to refresh (see WRITE POLICY below).

This script imports tier_runner (see scripts/planner_codex.py for the same
convention) so it must run in an environment where the tier-bench package is
installed/importable -- e.g. `pip install -e .` from the repo root, or via
the `tier-init` console script pyproject.toml registers for it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

# Prefer this checkout's own tier_runner over any stale copy that happens to
# be installed elsewhere on sys.path (e.g. a non-editable `pip install`
# performed before this module existed) -- this script must see the
# init_arms module it was written to drive.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tier_runner
from tier_runner import init_arms, manifest


# The protocol's own checkout: where this installed tier_runner package's
# source (and its .tier/hands.prompt.txt, cartridges.json templates) lives.
# Usually the same worktree this script is running from; may be a different
# path if tier-bench was pip-installed from elsewhere.
PROTOCOL_ROOT = Path(tier_runner.__file__).resolve().parent.parent
SOURCE_TEMPLATE = PROTOCOL_ROOT / ".tier" / "hands.prompt.txt"
SOURCE_CARTRIDGES = PROTOCOL_ROOT / "cartridges.json"


class InitError(RuntimeError):
    pass


def _protocol_commit() -> str | None:
    """`git rev-parse HEAD` against the protocol's own checkout, or None.

    None (not a fabricated placeholder) whenever PROTOCOL_ROOT isn't a Git
    checkout or git isn't on PATH -- build_manifest() then falls back to
    whatever protocol_commit an existing target manifest already has.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROTOCOL_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def gather_probes() -> dict[str, object]:
    probes: dict[str, object] = {
        "codex": init_arms.probe_codex(),
        "claude": init_arms.probe_claude(),
        "ollama": init_arms.probe_ollama(),
    }
    commit = _protocol_commit()
    if commit:
        probes["protocol_commit"] = commit
    if SOURCE_TEMPLATE.is_file():
        template_bytes = SOURCE_TEMPLATE.read_bytes()
        probes["hands_template"] = {
            "path": ".tier/hands.prompt.txt",
            "sha256": manifest.sha256_bytes(template_bytes),
        }
    return probes


def load_existing_manifest(repo: Path) -> dict[str, object] | None:
    path = repo / "pilot_backends.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InitError(f"existing {path} is not readable/valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else None


def filtered_cartridges(arm_names: set[str]) -> dict[str, object]:
    """This repo's cartridges.json, with ladders/arms trimmed to arm_names.

    A tier whose entire ladder was filtered away is dropped rather than
    written as an empty (and therefore unusable, per route.py) list.
    """
    raw = json.loads(SOURCE_CARTRIDGES.read_text(encoding="utf-8"))
    ladders = raw.get("ladders", {})
    filtered_ladders = {}
    for tier, ladder in ladders.items():
        kept = [arm for arm in ladder if arm in arm_names]
        if kept:
            filtered_ladders[tier] = kept
    arms_meta = raw.get("arms", {})
    filtered_arms_meta = {arm: meta for arm, meta in arms_meta.items() if arm in arm_names}
    return {"schema": raw.get("schema", "tier-bench/cartridges@1"), "ladders": filtered_ladders, "arms": filtered_arms_meta}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tier_init.py",
        description="Probe this machine's tooling and generate/write a pilot_backends.json for --repo.",
    )
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    args.repo = args.repo.expanduser().resolve()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.repo.is_dir():
        print(f"tier_init.py: --repo does not exist or is not a directory: {args.repo}", file=sys.stderr)
        return 2

    try:
        existing = load_existing_manifest(args.repo)
        probes = gather_probes()
        result = init_arms.build_manifest(probes, existing=existing)
    except (init_arms.ProbeError, InitError) as exc:
        print(f"tier_init.py: {exc}", file=sys.stderr)
        return 2

    existing_arm_names = set((existing or {}).get("arms", {})) if existing else set()
    new_arm_names = sorted(set(result["arms"]) - existing_arm_names)
    kept_arm_names = sorted(set(result["arms"]) & existing_arm_names)

    manifest_path = args.repo / "pilot_backends.json"
    template_path = args.repo / ".tier" / "hands.prompt.txt"
    cartridges_path = args.repo / "cartridges.json"

    would_write: list[str] = [str(manifest_path)]
    skipped: list[str] = []
    if template_path.exists():
        skipped.append(str(template_path))
    else:
        would_write.append(str(template_path))
    if cartridges_path.exists():
        skipped.append(str(cartridges_path))
    else:
        would_write.append(str(cartridges_path))

    written: list[str] = []
    if args.write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        written.append(str(manifest_path))

        # WRITE POLICY: pilot_backends.json is always refreshed above --
        # build_manifest()'s existing-arm-preserving merge makes that safe.
        # The two scaffold files below are seeded once and never silently
        # clobbered on a later --write; delete them first if a genuine reset
        # is wanted.
        if not template_path.exists() and SOURCE_TEMPLATE.is_file():
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_bytes(SOURCE_TEMPLATE.read_bytes())
            written.append(str(template_path))
        if not cartridges_path.exists() and SOURCE_CARTRIDGES.is_file():
            cartridges_data = filtered_cartridges(set(result["arms"]))
            cartridges_path.write_text(
                json.dumps(cartridges_data, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            written.append(str(cartridges_path))

    if args.json:
        payload = {
            "repo": str(args.repo),
            "found": {
                "codex": probes["codex"],
                "claude": probes["claude"],
                "ollama": probes["ollama"],
            },
            "arms": sorted(result["arms"]),
            "new_arms": new_arm_names,
            "kept_arms": kept_arm_names,
            "would_write": would_write if not args.write else [],
            "skipped": skipped,
            "written": written,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"repo: {args.repo}")
    print(f"codex:  available={probes['codex'].get('available')} version={probes['codex'].get('version')!r}")
    print(f"claude: available={probes['claude'].get('available')} version={probes['claude'].get('version')!r}")
    print(f"ollama: available={probes['ollama'].get('available')} version={probes['ollama'].get('version')!r}")
    print(f"arms ({len(result['arms'])}): {', '.join(sorted(result['arms'])) or '(none)'}")
    if new_arm_names:
        print(f"  new:  {', '.join(new_arm_names)}")
    if kept_arm_names:
        print(f"  kept (from existing manifest, unchanged): {', '.join(kept_arm_names)}")
    if args.write:
        print("written:")
        for path in written:
            print(f"  {path}")
        if skipped:
            print("skipped (already present, not overwritten):")
            for path in skipped:
                print(f"  {path}")
    else:
        print("would write (pass --write to actually write):")
        for path in would_write:
            print(f"  {path}")
        if skipped:
            print("would skip (already present):")
            for path in skipped:
                print(f"  {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside the modeled guard paths
        print(f"tier_init.py: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
