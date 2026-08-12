#!/usr/bin/env python3
"""Inventory the accepted Estate workflows for native-rail equivalence.

Read-only, stdlib only. Reads workflow YAML from a checkout of the bound source
revision rather than from a live API, so the inventory is reproducible from the
same exact-SHA bundle the rail executes.

    inventory_workflows.py <path/to/.github/workflows> <out.json>

The v1 parser in this lane reported `runs_on: ["${{"]` and therefore
`hosted_runner: false` for every workflow, and it counted trigger names under
`on:` as jobs. Both claims were wrong: all five accepted workflows run on
GitHub-hosted runners via a matrix expression. This parser resolves
`${{ matrix.<name> }}` against the job's own `strategy.matrix`, separates the
`on:` section from the `jobs:` section, and states what it cannot decide.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

PROVIDER_HINTS = re.compile(
    r"anthropic|openai|api\.claude|claude-code|ANTHROPIC_API_KEY|OPENAI_API_KEY"
    r"|gemini|mistral|ollama|llm", re.I)
NETWORK_HINTS = re.compile(r"curl |wget |pip install|npm install|apt-get|actions/setup", re.I)
WINDOWS_HINTS = re.compile(r"windows-|powershell|pwsh|\.ps1|\bwin32\b", re.I)
HOSTED = ("ubuntu", "windows", "macos")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def block(lines: list[str], start: int, indent: int) -> list[str]:
    """Lines belonging to the mapping opened at `start`, by indentation."""
    out = []
    for line in lines[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(line)
            continue
        if indent_of(line) <= indent:
            break
        out.append(line)
    return out


def top_sections(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m:
            out[m.group(1)] = block(lines, i, 0)
    return out


def keys_at(lines: list[str], indent: int) -> list[str]:
    out = []
    for line in lines:
        if indent_of(line) != indent:
            continue
        m = re.match(r"^\s*([A-Za-z0-9_-]+):", line)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def scalar(lines: list[str], key: str) -> str | None:
    for line in lines:
        m = re.match(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return None


def matrix_values(job_lines: list[str], name: str) -> list[str]:
    """Resolve a matrix axis, inline (`os: [a, b]`) or block (`- a`)."""
    for i, line in enumerate(job_lines):
        m = re.match(rf"^(\s*){re.escape(name)}:\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest.startswith("["):
            return [v.strip().strip("'\"") for v in rest.strip("[]").split(",") if v.strip()]
        vals = []
        for nxt in job_lines[i + 1:]:
            if not nxt.strip():
                continue
            if indent_of(nxt) <= len(m.group(1)):
                break
            item = re.match(r"^\s*-\s*(.+?)\s*$", nxt)
            if item:
                vals.append(item.group(1).strip().strip("'\""))
            else:
                break
        if vals:
            return vals
    return []


def inventory(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sections = top_sections(lines)

    triggers = keys_at(sections.get("on", []), 2)
    if not triggers:
        inline = scalar(lines, "on")
        if inline:
            triggers = [t.strip() for t in inline.strip("[]").split(",") if t.strip()]

    job_lines = sections.get("jobs", [])
    jobs = []
    unresolved = []
    for i, line in enumerate(job_lines):
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if not m:
            continue
        body = block(job_lines, i, 2)
        raw = scalar(body, "runs-on") or ""
        expr = re.match(r"^\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}$", raw)
        if expr:
            resolved = matrix_values(body, expr.group(1))
            if not resolved:
                unresolved.append(raw)
        elif raw:
            resolved = [raw]
        else:
            resolved = []
            unresolved.append("<absent>")
        jobs.append({
            "job": m.group(1),
            "runs_on_declared": raw,
            "runs_on_resolved": resolved,
            "permissions": [ln.strip() for ln in body
                            if re.match(r"^\s+\w[\w-]*:\s*(read|write|none)\s*$", ln)],
            "timeout_minutes": scalar(body, "timeout-minutes"),
        })

    resolved_all = sorted({r for j in jobs for r in j["runs_on_resolved"]})
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "line_count": len(lines),
        "triggers": triggers,
        "jobs": jobs,
        "runs_on_resolved": resolved_all,
        "hosted_runner": any(r.startswith(HOSTED) for r in resolved_all),
        "self_hosted_runner": any("self-hosted" in r for r in resolved_all),
        "unresolved_runner_expressions": unresolved,
        "actions_used": sorted(set(re.findall(r"uses:\s*(\S+)", text))),
        "permissions_top_level": [ln.strip() for ln in sections.get("permissions", [])
                                  if ln.strip()],
        "provider_calls": bool(PROVIDER_HINTS.search(text)),
        "network_install_steps": bool(NETWORK_HINTS.search(text)),
        "windows_dependent": bool(WINDOWS_HINTS.search(text)),
    }


def main() -> None:
    src = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2])
    files = sorted(p for p in src.iterdir() if p.suffix in (".yml", ".yaml"))
    records = [inventory(p) for p in files]
    payload = {
        "schema": "tier-bench/estate-workflow-inventory@2",
        "repository": "BigBirdReturns/estate",
        "source": "checkout of the bound revision, not a live API read",
        "workflow_count": len(records),
        "coverage": {"denominator": len(files), "numerator": len(records),
                     "complete": len(files) == len(records)},
        "claims": {
            "hosted_runner": "true where a job's runs-on resolves to a "
                             "GitHub-hosted image, including through a matrix axis",
            "provider_calls": "textual hint search only; a false value is evidence "
                              "of no provider reference in the YAML, not proof that "
                              "no invoked script reaches a provider",
            "not_claimed": ["semantic equivalence of a workflow to a native "
                            "transaction", "behaviour of reusable or called "
                            "workflows", "anything about repository or organisation "
                            "level settings"],
        },
        "workflows": records,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{'workflow':<52} {'runs-on':<28} hosted prov win net")
    for r in records:
        print(f"{r['name']:<52} {','.join(r['runs_on_resolved'])[:27]:<28} "
              f"{'Y' if r['hosted_runner'] else '.':<6} "
              f"{'Y' if r['provider_calls'] else '.':<4} "
              f"{'Y' if r['windows_dependent'] else '.':<3} "
              f"{'Y' if r['network_install_steps'] else '.':<3}")


if __name__ == "__main__":
    main()
