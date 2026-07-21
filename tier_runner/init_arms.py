"""Probe the local machine's tooling and generate manifest arm stanzas.

Companion to tier_runner/manifest.py: manifest.py *validates* a
tier-bench/pilot-backends@1 manifest; this module *generates* one from what
is actually installed on the machine running it, so a fresh checkout on a
new machine gets real, probed versions/hashes instead of a hand-copied
pilot_backends.json pinned to someone else's toolchain.

Nothing here invents a version. Each `probe_*` function reports exactly what
it observed (or that it observed nothing); `build_manifest` only emits an arm
when every value that arm's manifest stanza needs was actually present in a
probe, and never overwrites an arm carried in via `existing`.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .adapters import claude_code
from .desk_common import hidden_process_kwargs
from .manifest import SCHEMA


# Isolation block required by manifest.load_backend(); copied verbatim from
# the required_isolation check there so a generated manifest always satisfies
# it (this is a protocol-shape constant, not a probed value).
ISOLATION: dict[str, bool] = {
    "fresh_session_per_call": True,
    "instruction_files": False,
    "auto_memory": False,
    "conversation_carryover": False,
}

# Used only when codex is present but its model catalog could not be read.
CODEX_FALLBACK_SLUGS: list[str] = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.3-codex-spark",
]

CODEX_SURFACE = "codex-cli-subscription-text-emit"
CODEX_ACCOUNT = "chatgpt-subscription"
CODEX_COST_BASIS = "subscription-derived"
CODEX_ADAPTER_VERSION = "1"

# model slug -> the arm name/effort/tier this repo's cartridges.json already
# expects for it (see pilot_backends.json). A slug probed_codex() finds that
# is not in this table is skipped: we only generate arms this protocol's
# policy layer (cartridges.json) knows how to place on a ladder.
CODEX_ARM_SPECS: dict[str, dict[str, str]] = {
    "gpt-5.6-sol": {"arm": "arm_a", "effort": "medium", "tier": "frontier"},
    "gpt-5.6-luna": {"arm": "arm_luna", "effort": "medium", "tier": "frontier"},
    "gpt-5.6-terra": {"arm": "arm_terra", "effort": "medium", "tier": "frontier"},
    "gpt-5.3-codex-spark": {"arm": "arm_spark", "effort": "low", "tier": "cheap"},
}

CLAUDE_ARM = "arm_haiku"
CLAUDE_MODEL_ID = "claude-haiku-4-5-20251001"
CLAUDE_EFFORT = "low"
CLAUDE_SURFACE = "claude-code-subscription"
CLAUDE_ACCOUNT = "claude-subscription"
CLAUDE_TIER = "cheap"
CLAUDE_COST_BASIS = "subscription-derived"
CLAUDE_ADAPTER_VERSION = "9"

OLLAMA_ARM = "arm_b"
OLLAMA_MODEL = "qwen3.5:9b-q4_K_M"
OLLAMA_EFFORT = "deterministic"
OLLAMA_SURFACE = "ollama-local-text-emit"
OLLAMA_ACCOUNT = "local-ollama"
OLLAMA_TIER = "local"
OLLAMA_COST_BASIS = "shadow-estimated"
OLLAMA_ADAPTER_VERSION = "3"


class ProbeError(RuntimeError):
    """The machine could not be probed enough to build a manifest."""


# --------------------------------------------------------------------------
# probes: each one is a pure observation of the machine. No manifest shape,
# no policy, and (deliberately) no exceptions escape to the caller -- an
# absent/broken tool is reported as {"available": False, ...}, not raised.
# --------------------------------------------------------------------------


def probe_codex(binary: str = "codex") -> dict[str, Any]:
    """codex-cli's presence/version and its reachable model catalog.

    Falls back to CODEX_FALLBACK_SLUGS, tagged "source": "fallback_slug_list",
    only when codex itself is confirmed present but no catalog could be read.
    codex being absent entirely reports {"available": False, "models": []} --
    the fallback list is never used to paper over a missing binary.
    """
    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, **hidden_process_kwargs()
        )
    except OSError:
        return {"available": False, "version": None, "models": [], "source": None}
    if result.returncode != 0:
        return {"available": False, "version": None, "models": [], "source": None}
    version = result.stdout.strip()
    if not version:
        return {"available": False, "version": None, "models": [], "source": None}

    models: list[str] = []
    source: str | None = None
    try:
        catalog = subprocess.run(
            [binary, "models", "list", "--json"],
            capture_output=True,
            text=True,
            **hidden_process_kwargs(),
        )
        if catalog.returncode == 0 and catalog.stdout.strip():
            parsed = json.loads(catalog.stdout)
            candidates = parsed.get("models") if isinstance(parsed, dict) else parsed
            if isinstance(candidates, list):
                found = sorted(
                    {
                        str(entry.get("id") or entry.get("slug"))
                        for entry in candidates
                        if isinstance(entry, dict) and (entry.get("id") or entry.get("slug"))
                    }
                )
                if found:
                    models = found
                    source = "probed"
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    if not models:
        models = list(CODEX_FALLBACK_SLUGS)
        source = "fallback_slug_list"
    return {"available": True, "version": version, "models": models, "source": source}


def probe_claude(binary: str = "claude") -> dict[str, Any]:
    """Claude Code's version and help-surface hash.

    Reuses tier_runner.adapters.claude_code's own _version/_help_surface so
    the hash produced here is byte-identical to what the adapter itself
    computes and gates on at dispatch time -- this module never reimplements
    that hashing.
    """
    try:
        version = claude_code._version(binary)
    except (OSError, RuntimeError):
        return {"available": False, "version": None, "help_sha256": None}
    try:
        help_sha256 = claude_code._help_surface(binary)
    except (OSError, RuntimeError):
        return {"available": False, "version": version or None, "help_sha256": None}
    if not version or not help_sha256:
        return {"available": False, "version": version or None, "help_sha256": help_sha256 or None}
    return {"available": True, "version": version, "help_sha256": help_sha256}


def probe_ollama(base_url: str = "http://127.0.0.1:11434", timeout: float = 3.0) -> dict[str, Any]:
    """Installed Ollama model tags/digests (GET /api/tags) plus its version
    (GET /api/version, best-effort -- absence of a version alone never
    fabricates one; an arm needing it simply isn't emitted).
    """
    try:
        with urlopen(base_url.rstrip("/") + "/api/tags", timeout=timeout) as response:
            tags = json.loads(response.read())
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError):
        return {"available": False, "version": None, "models": {}}

    models: dict[str, str] = {}
    entries = tags.get("models") if isinstance(tags, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name, digest = entry.get("name"), entry.get("digest")
            if isinstance(name, str) and name and isinstance(digest, str) and digest:
                models[name] = digest

    version: str | None = None
    try:
        with urlopen(base_url.rstrip("/") + "/api/version", timeout=timeout) as response:
            payload = json.loads(response.read())
        candidate = payload.get("version") if isinstance(payload, dict) else None
        if isinstance(candidate, str) and candidate:
            version = candidate
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError):
        pass

    return {"available": True, "version": version, "models": models}


# --------------------------------------------------------------------------
# manifest generation
# --------------------------------------------------------------------------


def _codex_command(model: str, effort: str, version: str, account: str, tier: str) -> list[str]:
    return [
        "python", "-m", "tier_runner.adapters.codex_emit",
        "--arm", "{arm}",
        "--dispatch", "{dispatch_receipt}",
        "--prompt", "{prompt}",
        "--result", "{backend_result}",
        "--worktree", "{worktree}",
        "--model", model,
        "--effort", effort,
        "--codex-version", version,
        "--adapter-version", CODEX_ADAPTER_VERSION,
        "--account", account,
        "--tier", tier,
        "--surface", CODEX_SURFACE,
        "--cost-basis", CODEX_COST_BASIS,
    ]


def _claude_command(model: str, effort: str, version: str, help_sha256: str) -> list[str]:
    return [
        "python", "-m", "tier_runner.adapters.claude_code",
        "--arm", "{arm}",
        "--dispatch", "{dispatch_receipt}",
        "--prompt", "{prompt}",
        "--result", "{backend_result}",
        "--worktree", "{worktree}",
        "--model", model,
        "--effort", effort,
        "--claude-version", version,
        "--claude-help-sha256", help_sha256,
        "--adapter-version", CLAUDE_ADAPTER_VERSION,
        "--account", CLAUDE_ACCOUNT,
        "--tier", CLAUDE_TIER,
        "--surface", CLAUDE_SURFACE,
        "--cost-basis", CLAUDE_COST_BASIS,
    ]


def _ollama_command(model: str, digest: str, ollama_version: str) -> list[str]:
    return [
        "python", "-m", "tier_runner.adapters.ollama_emit",
        "--arm", "{arm}",
        "--dispatch", "{dispatch_receipt}",
        "--prompt", "{prompt}",
        "--result", "{backend_result}",
        "--worktree", "{worktree}",
        "--model", model,
        "--model-digest", digest,
        "--ollama-version", ollama_version,
        "--adapter-version", OLLAMA_ADAPTER_VERSION,
        "--account", OLLAMA_ACCOUNT,
        "--tier", OLLAMA_TIER,
        "--surface", OLLAMA_SURFACE,
        "--cost-basis", OLLAMA_COST_BASIS,
    ]


def _codex_arms(probe: dict[str, Any] | None) -> dict[str, Any]:
    probe = probe or {}
    if not probe.get("available"):
        return {}
    version = probe.get("version")
    if not version:
        return {}
    arms: dict[str, Any] = {}
    for slug in probe.get("models") or []:
        spec = CODEX_ARM_SPECS.get(slug)
        if not spec:
            continue
        arms[spec["arm"]] = {
            "model_id": slug,
            "effort": spec["effort"],
            "surface": CODEX_SURFACE,
            "cost_basis": CODEX_COST_BASIS,
            "account": CODEX_ACCOUNT,
            "tier": spec["tier"],
            "prompt_template": "hands",
            "tool_versions": {
                "codex_cli": version,
                "tier_codex_emit_adapter": CODEX_ADAPTER_VERSION,
            },
            "adapter": {
                "command": _codex_command(slug, spec["effort"], version, CODEX_ACCOUNT, spec["tier"])
            },
        }
    return arms


def _claude_arms(probe: dict[str, Any] | None) -> dict[str, Any]:
    probe = probe or {}
    if not probe.get("available"):
        return {}
    version = probe.get("version")
    help_sha256 = probe.get("help_sha256")
    if not version or not help_sha256:
        return {}
    return {
        CLAUDE_ARM: {
            "model_id": CLAUDE_MODEL_ID,
            "effort": CLAUDE_EFFORT,
            "surface": CLAUDE_SURFACE,
            "cost_basis": CLAUDE_COST_BASIS,
            "account": CLAUDE_ACCOUNT,
            "tier": CLAUDE_TIER,
            "prompt_template": "hands",
            "tool_versions": {
                "claude_code": version,
                "claude_help_sha256": help_sha256,
                "tier_claude_adapter": CLAUDE_ADAPTER_VERSION,
            },
            "adapter": {
                "command": _claude_command(CLAUDE_MODEL_ID, CLAUDE_EFFORT, version, help_sha256)
            },
        }
    }


def _ollama_arms(probe: dict[str, Any] | None) -> dict[str, Any]:
    probe = probe or {}
    if not probe.get("available"):
        return {}
    version = probe.get("version")
    digest = (probe.get("models") or {}).get(OLLAMA_MODEL)
    if not version or not digest:
        return {}
    return {
        OLLAMA_ARM: {
            "model_id": OLLAMA_MODEL,
            "effort": OLLAMA_EFFORT,
            "surface": OLLAMA_SURFACE,
            "cost_basis": OLLAMA_COST_BASIS,
            "account": OLLAMA_ACCOUNT,
            "tier": OLLAMA_TIER,
            "prompt_template": "hands",
            "tool_versions": {
                "model_digest": digest,
                "ollama": version,
                "tier_ollama_emit_adapter": OLLAMA_ADAPTER_VERSION,
            },
            "adapter": {"command": _ollama_command(OLLAMA_MODEL, digest, version)},
        }
    }


def build_manifest(probes: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a tier-bench/pilot-backends@1 manifest from probe results.

    `probes` is the output of this module's own probe_* functions, gathered
    under the keys "codex" / "claude" / "ollama", plus two pieces of manifest
    scaffolding this module cannot itself observe by running a probe:
      - "protocol_commit": the 40-hex Git SHA of the protocol layer being
        installed (tier_init.py resolves this with `git rev-parse HEAD`
        against its own checkout; tests may supply it directly).
      - "hands_template": {"path": str, "sha256": str} describing the hands
        prompt template that will sit next to the written manifest (the
        sha256 tier_init.py computes from the bytes it actually writes).

    `existing`, if given, is a previously-loaded manifest dict. Every arm it
    contains is preserved verbatim -- a freshly probed arm of the same name
    is dropped in favor of the existing one, never the other way around.
    Top-level scaffolding (protocol_commit / isolation / tool_versions /
    prompt_templates) falls back to `existing`'s when `probes` does not
    supply it.

    Only arms whose backing tool actually probed as available AND supplied
    every value the arm's stanza needs are emitted; nothing is invented.
    """
    existing = existing or {}
    existing_arms = existing.get("arms") if isinstance(existing.get("arms"), dict) else {}

    protocol_commit = probes.get("protocol_commit") or existing.get("protocol_commit")
    if not protocol_commit:
        raise ProbeError(
            "no protocol_commit available: pass probes['protocol_commit'] "
            "or an existing manifest that already has one"
        )

    isolation = existing.get("isolation") if isinstance(existing.get("isolation"), dict) else dict(ISOLATION)

    hands_template = probes.get("hands_template")
    if not hands_template:
        hands_template = existing.get("prompt_templates", {}).get("hands")
    if not isinstance(hands_template, dict) or not hands_template.get("path") or not hands_template.get("sha256"):
        raise ProbeError(
            "no hands prompt template info available: pass "
            "probes['hands_template'] (path + sha256) or an existing manifest"
        )

    generated: dict[str, Any] = {}
    generated.update(_codex_arms(probes.get("codex")))
    generated.update(_claude_arms(probes.get("claude")))
    generated.update(_ollama_arms(probes.get("ollama")))

    arms: dict[str, Any] = dict(existing_arms)
    for name, stanza in generated.items():
        if name in arms:
            continue  # never clobber an arm carried in via `existing`
        arms[name] = stanza

    default_tool_versions = existing.get("tool_versions") if isinstance(existing.get("tool_versions"), dict) else None
    if not default_tool_versions:
        # Every arm the schema requires has its own non-empty tool_versions;
        # borrow the first one (stable ordering) rather than inventing a
        # top-level placeholder that no probe actually produced.
        for name in sorted(arms):
            candidate = arms[name].get("tool_versions")
            if isinstance(candidate, dict) and candidate:
                default_tool_versions = dict(candidate)
                break
    if not default_tool_versions:
        # No arm probed as available at all (a brand-new machine with no
        # tooling yet, or every probe failed a version check). The manifest
        # is still schema-valid with zero arms; anchor tool_versions to the
        # one real, observed value we do have -- protocol_commit -- rather
        # than inventing a tool version that was never probed.
        default_tool_versions = {"protocol_commit": protocol_commit}

    return {
        "schema": SCHEMA,
        "protocol_commit": protocol_commit,
        "isolation": isolation,
        "tool_versions": default_tool_versions,
        "prompt_templates": {
            "hands": {"path": hands_template["path"], "sha256": hands_template["sha256"]}
        },
        "arms": arms,
    }
