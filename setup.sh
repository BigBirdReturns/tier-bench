#!/usr/bin/env bash
set -euo pipefail

# ─── Tier Bench — Setup Script ──────────────────────
# Run this once after unzipping the repo.
# Usage: bash setup.sh

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Tier Bench — Setup                              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 1. Check Python
echo "→ Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install it first."
    exit 1
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PY_VERSION found."

# 2. Install dependencies
echo ""
echo "→ Installing dependencies..."
pip install ruff --break-system-packages -q 2>/dev/null || pip install ruff -q
pip install anthropic openai --break-system-packages -q 2>/dev/null || pip install anthropic openai -q
echo "  ✓ ruff, anthropic, openai installed."

# 3. Check API keys
echo ""
echo "→ Checking API keys..."
KEYS_FOUND=0
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  ✓ ANTHROPIC_API_KEY is set"
    KEYS_FOUND=1
else
    echo "  ✗ ANTHROPIC_API_KEY not set"
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "  ✓ OPENAI_API_KEY is set"
    KEYS_FOUND=1
else
    echo "  ✗ OPENAI_API_KEY not set"
fi

if [ "$KEYS_FOUND" -eq 0 ]; then
    echo ""
    echo "  ⚠ No API keys found. You can still:"
    echo "    - Run dry-run mode:  python orchestrator.py --dry-run \"your task\""
    echo "    - Run local tests:   python -m pytest (no API needed)"
    echo ""
    echo "  To set a key:"
    echo "    export ANTHROPIC_API_KEY=sk-ant-..."
    echo "    export OPENAI_API_KEY=sk-..."
fi

# 4. Verify the harness works locally (no API needed)
echo ""
echo "→ Running local validation test (no API calls)..."
python3 -c "
from harness.task_schema import Task
from harness.validators import validate_all
from harness.util_git import ensure_git_repo, git_commit_all
from pathlib import Path
import shutil, tempfile

with tempfile.TemporaryDirectory() as td:
    work = Path(td) / 'repo'
    shutil.copytree('fixtures/t0_format_whitespace', work)
    ensure_git_repo(work)
    git_commit_all(work, 'baseline')
    target = work / 'input.py'
    target.write_text('import os\\nimport sys\\n\\n\\ndef main():\\n    x = 1\\n    y = 2\\n    print(x + y)\\n\\n\\nif __name__ == \"__main__\":\\n    main()\\n')
    v = validate_all(
        cwd=work, target_relpath='input.py', run_command=['python', 'input.py'],
        max_lines_changed=50, allowed_files=['*.py'],
        require_functional_equivalence=True, require_ruff_imports=False,
        require_compile=True, require_tests=False,
    )
    assert v.pass_all, f'Validation failed: {v}'
    print('  ✓ Harness validators work correctly.')
    print(f'    compile={v.compile_ok} equiv={v.functional_equivalence} diff={v.diff_lines} lines')
"

# 5. Verify task loading
echo ""
echo "→ Verifying task manifests..."
python3 -c "
from harness.task_schema import Task
from pathlib import Path
tasks = sorted(Path('tasks').glob('*.json'))
tiers = {}
for p in tasks:
    t = Task.from_json(p)
    tiers.setdefault(t.tier, []).append(t.task_id)
for tier in sorted(tiers):
    print(f'  {tier}: {len(tiers[tier])} tasks — {tiers[tier]}')
print(f'  ✓ {len(tasks)} tasks loaded across {len(tiers)} tiers.')
"

# 6. Show cost estimates
echo ""
echo "→ Cost estimates per tier (worst case, max output tokens):"
python3 -c "
from cost_guard import Tier, TIER_BUDGETS, TIER_ROUTING, estimate_cost
for tier in Tier:
    if tier not in TIER_ROUTING or not TIER_ROUTING[tier]:
        continue
    model = TIER_ROUTING[tier][0]
    budget = TIER_BUDGETS[tier]
    est = estimate_cost(model, 2000, budget['max_output_tokens'])
    print(f'  {tier.name:4s} → {model:28s} \${est:.4f} per call')
"

# 7. Done
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✓ Setup complete!                               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "WHAT TO DO NEXT:"
echo ""
echo "  THE ACTIVE MISSION (needs NO API key — runs on this session's model):"
echo "    1. Read: HANDOFF.md, ROADMAP.md, experiments/breadth/LESSONS.md"
echo "    2. Follow the paste-prompt in experiments/breadth/FABLE_KICKOFF.md"
echo "       (cheap floor on hidden-graded tasks -> escalate only real walls -> seal)"
echo "    3. Sanity, keyless/\$0:"
echo "       python experiments/breadth/smoke.py"
echo "       python experiments/breadth/breadth_tasks.py"
echo ""
echo "  ORIGINAL ROUTER LANE (needs an API key — only if benchmarking model routing):"
echo "    python orchestrator.py --dry-run \"your task\"     # cost estimate, no calls"
echo "    python orchestrator.py --benchmark T0              # needs a key"
echo ""
echo "  See CLAUDE.md -> START HERE for which lane you are in."
echo ""
