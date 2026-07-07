# Breadth run PLAN — Phase 1 complete + fable@low calibration (2026-07-07)

## Update: Phase-2 calibration ran with REAL telemetry

Per RUNBOOK Phase 2 ("run 3 known-easy tasks at fable@low as calibration"),
3 tasks (one per tier: t0_rename_symbol_003, t1_simple_refactor_003,
t2_fix_failing_test_001) ran K=3 at **fable@low** — all 9/9 pass, floor confirmed.

**Instrumentation upgrade over Phase 1:** trials ran via the nested
`claude -p --model claude-fable-5 --effort low --output-format json` CLI, so the
ledger rows carry EXACT tokens (incl. cache read/write splits) and **real billed
USD** (`total_cost_usd`), not shadow prices. The `effort` ledger field is now
populated. Trials ran sequentially from a constant cwd so the 1h prompt cache was
written once (trial 1: $0.85) and read thereafter (~$0.42/trial).

**Measured vs planning:** fable@low actually costs ~$0.48/trial mean — the
rungs.py planning figure ($0.30) was ~40% low, because cache reads across the
solver's agentic turns (~170k cache-read tokens/trial) dominate. map.json now
uses measured per-rung mean costs where trials exist (haiku@harness $0.0365 est,
fable@low $0.4793 real) and planning estimates elsewhere.

**Effort-rung agents:** `.claude/agents/fable-{low,medium,high,xhigh,max}.md`
are committed (model: fable, effort: <rung>). They hot-load only in sessions
where `.claude/agents/` existed at start — this session predates the dir, hence
the CLI path. Future sessions can walk the ladder via the Agent tool directly.

Budget: $5.77 of $10 (57.7%). Decision packet: **DO NOT ESCALATE** (unchanged —
map complete, no unmapped residual, no capability ceilings).


## Result: the cheap floor cleared EVERYTHING

All 12 tasks in `tasks.txt` cleared 3/3 at `claude-haiku-4-5@harness`.
**`residual.txt` is empty. Phase 2 (Fable effort ladder) is not needed.**

## How the floor was laid (keyless, per RUNBOOK Phase 1)

- Solver: haiku subagents via the Agent tool (no `ANTHROPIC_API_KEY`, no
  `orchestrator.py` real-call path). Each trial ran in a scratch copy of the
  fixture — committed fixtures never mutated.
- Grader: the task's own `run_command` + `harness.validators.validate_all`
  with the manifest's flags, with the PRE-EDIT behavior snapshot captured at
  prep time passed as `before` (so `functional_equivalence` is real, not
  trivially true). The model is off the scoring path.
- Harness augmentation: for the three T3 bug/review tasks, one haiku lens
  review per task (the 5 sealed-shard lenses) fed findings to the solve
  trials. T0–T2 solved plain — the lenses do nothing for implement-from-spec.
- K = 3 trials per task; a task "clears" only at 3/3 (escalate.py
  clear_thresh=1.0).

## Ledger

`ledger.jsonl`: 39 rows = 36 solve trials (phase=baseline) + 3 lens reviews
(phase=harness). Estimated spend $1.46 of the $10 quota (14.6%).
NOTE on reconciliation: costs are shadow prices estimated from subagent token
counts at haiku-4.5 list price ($1/$5 per MTok, 90/10 in/out split) — the
solves ran as Claude Code session subagents, not billed API calls, so there
is no provider bill to `ledger.reconcile` against. Token counts are real
(from Agent tool usage reports); dollar figures are estimates.

## Effort ladder (from rungs.ladder(), unused — kept for a future residual)

1. claude-haiku-4-5@harness  ~$0.030/call   <- everything cleared here
2. claude-fable-5@low        ~$0.300/call
3. claude-fable-5@medium     ~$0.480/call
4. claude-fable-5@high       ~$0.780/call
5. claude-fable-5@xhigh      ~$1.200/call
6. claude-fable-5@max        ~$1.800/call

## Residual queue

(empty)

## Decision packet (limit.decision_packet)

recommendation: **DO NOT ESCALATE** — the map is complete within current
access; everything reached a clear. Escalating effort or access buys nothing.

## Adaptations (adapt.py, run/harness_log.jsonl)

- FREE / applied: solve_strategy — subagents WRITE the updated file in the
  scratch copy instead of returning content in chat (the template's
  "Return ONLY..." wording predates tool-using solvers).
- GATED proposals pending review: none.
