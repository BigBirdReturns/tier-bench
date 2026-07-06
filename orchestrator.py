"""
orchestrator.py

Three modes:
  1. orchestrate: Decompose a request into subtasks, route, execute, validate.
  2. benchmark:   Run the harness task suite against real models.
  3. dry-run:     Estimate costs without calling APIs.

Safety properties:
- Planner sees repo tree (no blind planning).
- Worker sees target file plus sibling signatures (token-efficient context).
- Path safety enforced before any read or write.
- Worker output sanitized (reject prose, accept file-only output).
- Planner JSON extracted via regex (robust to surrounding text).
- Workers auto-route to cheapest available model (not forced to planner's provider).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cost_guard import (CostGuard, ROLES, Tier, TIER_BUDGETS, TIER_ROUTING,
                        estimate_cost, count_tokens_approx, model_available,
                        available_providers as _available_providers)
from harness.sanitize import sanitize_model_output
from harness.validators import capture_behavior, validate_all

# ─── Path safety ──────────────────────────────────────────────────────

IGNORED_DIRS = {
    ".git", ".work", "__pycache__", "venv", ".venv",
    "node_modules", ".mypy_cache", ".ruff_cache",
}
IGNORE_FILES = {"llm_costs.jsonl", "harness_results.jsonl"}


def _is_safe_repo_path(repo_root: Path, target_file: str) -> tuple[bool, str]:
    """Validate that target_file stays within repo_root."""
    if not target_file or not isinstance(target_file, str):
        return False, "empty_target"
    if target_file.startswith(("/", "\\", "~")):
        return False, "absolute_or_home_path"
    if ".." in Path(target_file).parts:
        return False, "parent_traversal"
    rr = repo_root.resolve()
    try:
        p = (rr / target_file).resolve()
        p.relative_to(rr)
    except Exception:
        return False, "outside_repo_root"
    parts = p.relative_to(rr).parts
    if any(part in IGNORED_DIRS for part in parts):
        return False, "path_in_ignored_dir"
    return True, "ok"


# ─── Repo context helpers ─────────────────────────────────────────────

def repo_tree(root: Path, max_lines: int = 300) -> str:
    """Generate a file tree for planner context."""
    lines: list[str] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        rel_dir = Path(dirpath).resolve().relative_to(root)
        depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
        indent = "  " * depth
        if str(rel_dir) != ".":
            lines.append(f"{indent}{rel_dir}/")
        for fn in sorted(filenames):
            if fn in IGNORE_FILES or fn.startswith("."):
                continue
            lines.append(f"{indent}  {fn}")
            if len(lines) >= max_lines:
                return "\n".join(lines) + "\n... (truncated)"
    return "\n".join(lines)


def _signature_from_ast(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.FunctionDef):
        args = [a.arg for a in node.args.args]
        if node.args.vararg:
            args.append("*" + node.args.vararg.arg)
        for a in node.args.kwonlyargs:
            args.append(a.arg)
        if node.args.kwarg:
            args.append("**" + node.args.kwarg.arg)
        return f"def {node.name}({', '.join(args)})"
    if isinstance(node, ast.AsyncFunctionDef):
        return f"async def {node.name}(... )"
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    return None


def sibling_signatures(target_file: Path, max_files: int = 12, max_chars: int = 6000) -> str:
    """AST-extracted signatures of sibling .py files. Token-efficient context."""
    d = target_file.parent
    parts: list[str] = []
    count = 0
    for p in sorted(d.glob("*.py")):
        if p.name == target_file.name or p.name.startswith("."):
            continue
        count += 1
        if count > max_files:
            parts.append("... (more sibling files omitted)")
            break
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src)
            sigs = [s for n in tree.body if (s := _signature_from_ast(n))]
            block = f"=== {p.name} ===\n" + ("\n".join(sigs) if sigs else "(no top-level defs)")
        except Exception:
            block = f"=== {p.name} ===\n(unreadable)"
        parts.append(block)
        if sum(len(x) for x in parts) >= max_chars:
            parts.append("... (truncated)")
            break
    return "\n".join(parts).strip()


# ─── Provider selection ───────────────────────────────────────────────

def check_providers() -> dict[str, bool]:
    return _available_providers()


def pick_available_provider() -> Optional[str]:
    """Best available provider for planning (T4+)."""
    forced = os.environ.get("HARNESS_PROVIDER")
    providers = check_providers()
    if forced:
        return forced if providers.get(forced) else None
    for name in ["anthropic", "openai", "google", "mistral", "deepseek", "ollama"]:
        if providers.get(name):
            return name
    return None


# ─── Prompts ──────────────────────────────────────────────────────────

SUPERVISOR_SYSTEM = (
    "You are a Staff-level engineering planner. Decompose the user request "
    "into isolated, testable subtasks.\n\n"
    "Rules:\n"
    "1) Each subtask edits ONE file.\n"
    "2) Assign a tier: T0 (format/lint), T1 (implement from spec), T2 (debug/integrate), T3 (refactor/review).\n"
    "3) Order subtasks so later ones can depend on earlier ones.\n"
    "4) Be specific: 'Implement function foo(a: int) -> str that does Y' not 'Implement X'.\n"
    "5) Output ONLY a JSON array. No markdown, no prose.\n\n"
    "Schema:\n"
    '[{"task_id":"step_1_short","tier":"T0"|"T1"|"T2"|"T3",'
    '"target_file":"path/to/file.py","instruction":"What to do",'
    '"acceptance":"How to verify"}]\n'
)

WORKER_SYSTEM = (
    "You are a software engineer executing a scoped task.\n"
    "Return ONLY the complete updated file content.\n"
    "No markdown. No backticks. No explanation.\n"
    'If you cannot complete the task, return exactly: {"escalate": true, "reason": "..."}\n'
)


def _extract_json_array(text: str) -> str | None:
    """Extract a JSON array from text, robust to surrounding prose and brackets."""
    start = text.find("[")
    if start == -1:
        return None
    text = text[start:]
    while text:
        end = text.rfind("]")
        if end == -1:
            break
        candidate = text[:end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            text = text[:end]
    return None


# ─── Orchestrate mode ─────────────────────────────────────────────────

def resolve_driver(cli_driver: str | None = None) -> str | None:
    """Resolve the planning/verification model: the 'driver'.

    Precedence: --driver flag > TIER_BENCH_DRIVER env > roles.driver in
    models.json > None (fall back to cheapest-capable tier routing).
    Roles are registry data so this survives model churn: swap the name in
    models.json and every run follows. If the named driver's provider isn't
    reachable, degrade to tier routing rather than dying — the work still
    gets planned, just not by the preferred brain.
    """
    driver = cli_driver or os.environ.get("TIER_BENCH_DRIVER") or ROLES.get("driver")
    if not driver:
        return None
    if not model_available(driver):
        print(f"⚠️  driver '{driver}' unavailable (no key / provider down); "
              "falling back to tier routing for planning.")
        return None
    return driver


def decompose_request(guard: CostGuard, prompt: str, provider: str, repo_root: Path,
                      driver: str | None = None) -> list[dict]:
    """Ask the driver (or a T4-routed model) to decompose a request into subtasks."""
    tree = repo_tree(repo_root)
    context_prompt = f"User Request:\n{prompt}\n\nCurrent Repository Structure:\n{tree}\n"

    # Driver/hands split: the driver plans (judgment tokens); workers below
    # auto-route to the cheapest capable model (bulk tokens).
    if driver:
        print(f"\n🧠 Planning (T4, driver={driver})...")
        result = guard.call(
            model=driver,
            tier=Tier.T4,
            system=SUPERVISOR_SYSTEM,
            messages=[{"role": "user", "content": context_prompt}],
        )
    else:
        print(f"\n🧠 Planning (T4, provider={provider})...")
        result = guard.call(
            tier=Tier.T4,
            provider=provider,
            system=SUPERVISOR_SYSTEM,
            messages=[{"role": "user", "content": context_prompt}],
        )

    if result.get("status") != "ok" or not isinstance(result.get("content"), str):
        print(f"❌ Planner failed: {result.get('reason', 'unknown')}")
        sys.exit(1)

    raw = result["content"].strip()
    extracted = _extract_json_array(raw)
    if extracted is None:
        print(f"❌ Planner returned no JSON array.")
        print(f"   Raw (first 500 chars): {raw[:500]}")
        sys.exit(1)

    try:
        plan = json.loads(extracted)
    except json.JSONDecodeError as e:
        print(f"❌ Planner JSON decode error: {e}")
        sys.exit(1)

    if not isinstance(plan, list):
        print("❌ Planner output is not a list.")
        sys.exit(1)

    print(f"   ✓ Plan: {len(plan)} subtasks (cost: ${result.get('cost', 0):.4f})")
    return plan


def _validation_flags_for_tier(tier: Tier) -> dict[str, bool]:
    """Deterministic validation policy per tier for orchestration."""
    if tier == Tier.T0:
        return {"compile": True, "ruff_imports": True, "functional_equivalence": True, "tests": False}
    return {"compile": True, "ruff_imports": False, "functional_equivalence": False, "tests": True}


def execute_subtask(guard: CostGuard, task: dict, repo_root: Path) -> dict:
    """Execute a single subtask. Auto-routes to cheapest available model at tier."""
    target_file = str(task.get("target_file", "")).strip()
    ok, reason = _is_safe_repo_path(repo_root, target_file)
    if not ok:
        print(f"\n   ❌ Unsafe path '{target_file}': {reason}")
        return {"task_id": task.get("task_id"), "status": "failed", "reason": f"unsafe_path:{reason}", "cost": 0}

    tier_name = str(task.get("tier", "T2")).strip().upper()
    try:
        tier = Tier[tier_name]
    except KeyError:
        print(f"   ⚠ Unknown tier '{tier_name}', defaulting to T2")
        tier = Tier.T2

    instruction = str(task.get("instruction", ""))
    acceptance = str(task.get("acceptance", ""))
    rel = Path(target_file)
    file_path = (repo_root / rel).resolve()

    print(f"\n👷 [{task.get('task_id', '?')}] → {tier_name}")
    print(f"   File: {target_file}")
    print(f"   Task: {instruction[:100]}{'...' if len(instruction) > 100 else ''}")

    current_content = ""
    if file_path.exists():
        current_content = file_path.read_text(encoding="utf-8")

    sib_ctx = sibling_signatures(file_path) if file_path.parent.exists() else ""

    # Baseline behavior for validation
    run_cmd = ["python", str(rel)] if rel.suffix == ".py" else ["python", "-c", "print('ok')"]
    before = capture_behavior(repo_root, run_cmd)

    worker_prompt = (
        f"Target file: {target_file}\n\n"
        f"Task: {instruction}\n\n"
        f"Acceptance: {acceptance}\n\n"
        f"Sibling file signatures (read-only context):\n"
        f"{sib_ctx if sib_ctx else '(none)'}\n\n"
        f"Current content:\n"
        f"{current_content if current_content else '(New file — create from scratch)'}\n"
    )

    # Auto-route: no provider forced, CostGuard picks cheapest available model at this tier
    result = guard.call(
        tier=tier,
        system=WORKER_SYSTEM,
        messages=[{"role": "user", "content": worker_prompt}],
    )

    if result.get("status") != "ok" or not isinstance(result.get("content"), str):
        reason = result.get("reason", "model_call_failed")
        print(f"   ❌ Failed: {reason}")
        return {"task_id": task.get("task_id"), "status": "failed", "reason": reason, "cost": result.get("cost", 0)}

    # Check for model escalation request
    content = result["content"]
    if content.strip().startswith('{"escalate"'):
        try:
            esc = json.loads(content.strip())
            if esc.get("escalate"):
                print(f"   ⬆ Model requested escalation: {esc.get('reason', '?')}")
                return {"task_id": task.get("task_id"), "status": "escalated", "reason": esc.get("reason", ""), "cost": result.get("cost", 0)}
        except json.JSONDecodeError:
            pass

    # Sanitize output
    sanitized, reject_reason = sanitize_model_output(content)
    if sanitized is None:
        print(f"   ❌ Output rejected: {reject_reason}")
        return {"task_id": task.get("task_id"), "status": "failed", "reason": f"sanitize:{reject_reason}", "cost": result.get("cost", 0)}

    # Write and validate
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(sanitized, encoding="utf-8")

    after = capture_behavior(repo_root, run_cmd)
    flags = _validation_flags_for_tier(tier)

    v = validate_all(
        cwd=repo_root,
        target_relpath=str(rel),
        run_command=run_cmd,
        max_lines_changed=250,
        allowed_files=[rel.name],
        require_functional_equivalence=flags["functional_equivalence"],
        require_ruff_imports=flags["ruff_imports"],
        require_compile=flags["compile"],
        require_tests=flags["tests"],
        before=before,
        after=after,
    )

    status = "ok" if v.pass_all else "validation_failed"
    icon = "✅" if v.pass_all else "⚠️"
    print(f"   {icon} compile={v.compile_ok} tests={v.tests_ok} diff={v.diff_lines} cost=${result.get('cost', 0):.4f}")

    return {
        "task_id": task.get("task_id"),
        "status": status,
        "target_file": target_file,
        "tier": tier.name,
        "model": result.get("model"),
        "cost": result.get("cost", 0),
        "validation": {
            "compile_ok": v.compile_ok,
            "tests_ok": v.tests_ok,
            "functional_equivalence": v.functional_equivalence,
            "ruff_imports_ok": v.ruff_imports_ok,
            "diff_lines": v.diff_lines,
            "allowed_files_ok": v.allowed_files_ok,
            "max_lines_ok": v.max_lines_ok,
        },
    }


# ─── Benchmark mode ──────────────────────────────────────────────────

def run_benchmark(tiers: list[str]):
    """Run the deterministic harness benchmark against real models."""
    from harness.config import RunConfig
    from harness.run_task import run_task

    cfg = RunConfig(results_path=Path("harness_results.jsonl"))

    for tier_name in tiers:
        tier_name = tier_name.upper()
        tasks = sorted(Path("tasks").glob(f"{tier_name.lower()}_*.json"))
        if not tasks:
            print(f"⚠ No tasks found for {tier_name}")
            continue

        print(f"\n{'='*60}")
        print(f"  BENCHMARK: {tier_name} — {len(tasks)} tasks")
        print(f"{'='*60}")

        for task_path in tasks:
            print(f"\n  Running: {task_path.name}")
            try:
                run_task(task_path, cfg)
                print(f"  ✓ Complete")
            except Exception as e:
                print(f"  ✗ Error: {e}")

    if cfg.results_path.exists():
        from harness.metrics import compute
        stats = compute(cfg.results_path)
        print(f"\n{'='*60}")
        print(f"  RESULTS")
        print(f"{'='*60}")
        print(f"  {'Tier':<6} {'Model':<28} {'Pass':>6} {'Att':>5} {'Rate':>7} {'$/success':>10}")
        print(f"  {'-'*6} {'-'*28} {'-'*6} {'-'*5} {'-'*7} {'-'*10}")
        rows = []
        for (model, tier), s in stats.items():
            cps = f"${s.cost_per_success:.4f}" if s.cost_per_success != float("inf") else "∞"
            rows.append((tier or "?", model or "?", s.successes, s.attempts, s.success_rate, cps))
        rows.sort()
        for tier, model, succ, att, rate, cps in rows:
            print(f"  {tier:<6} {model:<28} {succ:>6} {att:>5} {rate:>6.0%} {cps:>10}")


# ─── Dry run mode ────────────────────────────────────────────────────

def dry_run(prompt: str):
    """Estimate costs without calling APIs."""
    print(f"\n📋 DRY RUN — \"{prompt[:80]}{'...' if len(prompt) > 80 else ''}\"")
    input_tokens = count_tokens_approx([{"role": "user", "content": prompt}]) + 300

    print(f"\n  Planner (T4):")
    for model in TIER_ROUTING.get(Tier.T4, [])[:3]:
        est = estimate_cost(model, input_tokens, TIER_BUDGETS[Tier.T4]["max_output_tokens"])
        print(f"    {model:<28} est=${est:.4f}")

    print(f"\n  Workers (assuming 5 subtasks):")
    for tier in [Tier.T0, Tier.T1, Tier.T2]:
        models = TIER_ROUTING.get(tier, [])
        if not models:
            continue
        model = models[0]
        est = estimate_cost(model, 1000, TIER_BUDGETS[tier]["max_output_tokens"])
        print(f"    {tier.name} → {model:<28} est=${est:.4f} per task")

    planner_model = TIER_ROUTING[Tier.T4][0]
    planner_cost = estimate_cost(planner_model, input_tokens, TIER_BUDGETS[Tier.T4]["max_output_tokens"])
    worker_cost = sum(
        estimate_cost(TIER_ROUTING[Tier.T2][0], 1000, TIER_BUDGETS[Tier.T2]["max_output_tokens"])
        for _ in range(5)
    )
    print(f"\n  Worst-case total (5 T2 subtasks): ${planner_cost + worker_cost:.4f}")


# ─── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="LLM Orchestrator — decompose, route, execute, validate.",
        epilog="Examples:\n"
               "  python orchestrator.py \"Fix the bug in auth.py\"\n"
               "  python orchestrator.py --benchmark T0\n"
               "  python orchestrator.py --benchmark all\n"
               "  python orchestrator.py --dry-run \"Add caching\"\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("prompt", nargs="?", help="Plain-English task to decompose and execute")
    ap.add_argument("--benchmark", metavar="TIER", help="Run harness benchmark: T0, T1, T2, or 'all'")
    ap.add_argument("--dry-run", metavar="PROMPT", help="Estimate costs without calling APIs")
    ap.add_argument("--provider", help="Force provider for planner calls")
    ap.add_argument("--driver", help="Model that plans/verifies (default: roles.driver in models.json; "
                                     "env TIER_BENCH_DRIVER overrides). Workers still auto-route cheap.")
    args = ap.parse_args()

    # Dry run — no provider needed
    if args.dry_run:
        dry_run(args.dry_run)
        return 0

    # Benchmark mode
    if args.benchmark:
        provider = args.provider or pick_available_provider()
        if not provider:
            print("❌ No providers available. Set an API key or start Ollama.")
            return 1
        tiers = [t.name for t in Tier] if args.benchmark.lower() == "all" else [args.benchmark]
        run_benchmark(tiers)
        return 0

    # Orchestrate mode
    if not args.prompt:
        ap.print_help()
        return 2

    provider = args.provider or pick_available_provider()
    if not provider:
        print("❌ No providers available.")
        print("   Set ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, MISTRAL_API_KEY, or GEMINI_API_KEY")
        print("   Or start Ollama: ollama serve")
        print(f'\n   Try: python orchestrator.py --dry-run "{args.prompt[:50]}..."')
        return 1

    providers = check_providers()
    active = [k for k, v in providers.items() if v]
    print(f"🔧 Planner provider: {provider}")
    print(f"   All available: {', '.join(active)}")

    repo_root = Path.cwd()
    guard = CostGuard(
        max_cost_per_call=float(os.environ.get("HARNESS_MAX_PER_CALL", "1.00")),
        max_daily_spend=float(os.environ.get("HARNESS_MAX_DAILY", "10.00")),
    )

    # Plan
    driver = resolve_driver(args.driver)
    plan = decompose_request(guard, args.prompt, provider=provider, repo_root=repo_root,
                             driver=driver)
    print(f"\n📋 Plan ({len(plan)} subtasks):")
    for i, t in enumerate(plan):
        print(f"  {i+1}. [{t.get('tier', '?')}] {t.get('task_id', '?')} → {t.get('target_file', '?')}")

    # Execute
    results = []
    for task in plan:
        r = execute_subtask(guard, task, repo_root=repo_root)
        results.append(r)

    # Summary
    print(f"\n{'='*60}")
    print(f"  EXECUTION SUMMARY")
    print(f"{'='*60}")
    total_cost = sum(r.get("cost", 0) for r in results)
    passed = sum(1 for r in results if r.get("status") == "ok")
    failed = len(results) - passed
    for r in results:
        icon = {"ok": "✅", "failed": "❌", "escalated": "⬆", "validation_failed": "⚠️"}.get(r.get("status", ""), "?")
        print(f"  {icon} {r.get('task_id', '?'):<30} {r.get('model', '—'):<25} ${r.get('cost', 0):.4f}")
    print(f"\n  {passed} passed, {failed} failed, ${total_cost:.4f} total")
    guard.print_summary()

    # Log
    log_path = Path("orchestrator_log.jsonl")
    with open(log_path, "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": args.prompt[:500],
            "provider": provider,
            "subtasks": len(plan),
            "passed": passed,
            "failed": failed,
            "total_cost": total_cost,
            "results": results,
        }, default=str) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
