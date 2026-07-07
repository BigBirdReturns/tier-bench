# Contributing Tasks

Add benchmark tasks without touching any Python code. The harness discovers tasks automatically from the `tasks/` and `fixtures/` directories.

## The Contract

A valid task is:
1. A JSON manifest in `tasks/`
2. A fixture directory in `fixtures/`
3. Both must pass `python scripts/validate_task.py`

If it passes the validator, it will not break the harness. That's the guarantee.

## Quick Start

```bash
# 1. Create your fixture
mkdir fixtures/t2_my_new_task

# 2. Write the code that needs fixing/implementing (the "before" state)
cat > fixtures/t2_my_new_task/input.py << 'EOF'
# Your test runner goes here
# Must print "OK" and exit 0 when the task is correctly solved
# Must exit non-zero when unsolved (the "before" state)
EOF

cat > fixtures/t2_my_new_task/target.py << 'EOF'
# The file the model will edit
EOF

# 3. Create the task manifest
cat > tasks/t2_my_new_task_001.json << 'EOF'
{
  "task_id": "t2_my_new_task_001",
  "tier": "T2",
  "prompt_template": "Task: Fix the bug in {target_relpath}.\n\nRules:\n- Return ONLY the full updated content for {target_relpath}.\n- Do not add commentary.\n\nCurrent file content:\n{file_content}\n\nBaseline run:\nexit={baseline_rc}\nstdout:\n{baseline_stdout}\nstderr:\n{baseline_stderr}\n\nOther files:\n{context_files}\n",
  "fixture_dir": "fixtures/t2_my_new_task",
  "target_relpath": "target.py",
  "run_command": ["python", "input.py"],
  "validate": {
    "compile": true,
    "tests": true
  },
  "max_lines_changed": 250,
  "allowed_files": ["target.py"]
}
EOF

# 4. Validate
python scripts/validate_task.py tasks/t2_my_new_task_001.json

# 5. Run benchmark to test it
python orchestrator.py --benchmark T2
```

## Rules

### Naming
- Task ID: `{tier}_{short_description}_{number}` — e.g. `t2_fix_auth_bug_004`
- Task JSON filename must match task ID: `t2_fix_auth_bug_004.json`
- Fixture directory: `fixtures/t2_fix_auth_bug` (no number suffix)

### Fixture Structure
```
fixtures/t2_my_task/
├── input.py        # Test runner (always this name by convention)
├── target.py       # File the model will edit (can be any name)
└── helper.py       # Optional: other files the model can see but not edit
```

The test runner (`input.py` by convention) must:
- **Exit 0 and print "OK"** when the task is correctly solved
- **Exit non-zero** in the unsolved "before" state
- Be self-contained — no pip dependencies beyond stdlib

### Manifest Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | string | yes | Unique ID, must start with tier prefix |
| `tier` | string | yes | T0, T1, T2, T3, T4, or T5 |
| `prompt_template` | string | yes | Must contain `{file_content}` and `{target_relpath}` |
| `fixture_dir` | string | yes | Path to fixture directory |
| `target_relpath` | string | yes | File the model edits (relative to fixture) |
| `run_command` | list | yes | Command to run tests, e.g. `["python", "input.py"]` |
| `validate` | dict | yes | Which validators to run (see below) |
| `max_lines_changed` | int | yes | Diff limit — reject if model changes more lines |
| `allowed_files` | list | yes | Which files the model is allowed to modify |

### Validation Flags

| Flag | What It Checks | Use When |
|------|---------------|----------|
| `compile` | `python -m compileall` passes | Almost always true |
| `ruff_imports` | `ruff check --select I` passes | T0 formatting tasks |
| `functional_equivalence` | Before/after runtime output identical | T0 tasks only — the edit must not change behavior |
| `tests` | `run_command` exits 0 | Bug fixes, implementations, anything with a test |

### Template Variables

Your `prompt_template` can use these variables (injected by the harness):

| Variable | Content |
|----------|---------|
| `{target_relpath}` | Path to the target file |
| `{file_content}` | Current content of the target file |
| `{baseline_rc}` | Exit code of run_command before edit |
| `{baseline_stdout}` | Stdout of run_command before edit |
| `{baseline_stderr}` | Stderr of run_command before edit |
| `{context_files}` | Content of other .py files in the fixture |

## Tier Design Guidelines

The point of tiers is to differentiate models. A good task at tier N should:
- **Be solvable** by models at tier N or above
- **Fail** for models below tier N
- **Have an objective pass/fail** — no human judgment needed

### What Makes Each Tier Hard

**T0 (Clerical):** The constraint is *don't change behavior*. A model that "helpfully" refactors while formatting fails. Test with `functional_equivalence: true`.

**T1 (Junior):** Implement from spec. Include edge cases in the test that catch naive implementations. The slugify task has unicode and multiple-hyphen edge cases that small models miss.

**T2 (Mid):** Multi-file reasoning. The target file interacts with other files. The model must understand imports, interfaces, and how modules connect. Use `{context_files}` to show sibling files.

**T3 (Senior):** Judgment required. Security bugs that aren't flagged by linters. Refactoring where the structural check (AST analysis in test runner) verifies the model actually decomposed the function. Cross-module bugs with inverted logic that only manifest through integration.

**T4-T5:** Not currently testable in the harness. See README for the methodology split.

## Validation

Always run before submitting:

```bash
# Validate your task
python scripts/validate_task.py tasks/t2_my_new_task_001.json

# Verify fixture fails in "before" state
cd fixtures/t2_my_new_task && python input.py
# Should exit non-zero

# Verify a correct solution would pass
# (manually fix the target, run input.py, should print OK)
```

## Examples

Look at existing tasks for patterns:
- **Simple bug fix:** `t2_fix_failing_test_001` — target file has a bug, test checks for correct output
- **Multi-file:** `t2_multi_file_patch_003` — model edits `lib.py`, test runs `input.py` which imports from it
- **Security audit:** `t3_sql_injection_fix_001` — model must find and fix a vulnerability, test includes attack payloads
- **Structural refactor:** `t3_refactor_god_function_002` — test checks both output correctness AND code structure via AST

## Contributing benchmark data

Tasks are one half of Tier Bench; the other half is measurement, and no single
rig can run every model at every tier. If you've run the benchmark, your
`harness_results.jsonl` is worth pooling:

1. Run the benchmark with your own API keys: `python orchestrator.py --benchmark all`
2. Package your results: `python scripts/contribute.py --results harness_results.jsonl --as yourhandle`
   This validates every row (real task id, matching tier, sane cost) and writes
   `data/results/<date>-yourhandle-<hash>.jsonl` — invalid rows are dropped
   with an error only if they're a small minority; too many and the whole
   file is rejected.
3. Open a PR adding the generated file to `data/results/`. Do not hand-edit it
   and do not commit synthetic data — CI re-validates the file mechanically
   (`.github/workflows/validate.yml`) and the aggregator must digest it
   alongside everything already merged.
4. On merge, the site republishes automatically: `scripts/aggregate.py` pools
   your rows with everyone else's and regenerates the routing recommendations.

**Honesty doctrine.** Every contributed row is self-reported — nobody
verifies you ran the harness honestly, only that the row is structurally
real. A `(model, tier)` cell backed by a single contributor is
`single-source`: a claim, not a fact. Once two or more distinct contributors
report the same cell, it becomes `corroborated`. Every recommendation
`scripts/aggregate.py` produces is computed only from this pooled, labeled
data — routing picks, frontier-replication verdicts, and apprentice
candidates all carry their evidence class, never a bare number.
