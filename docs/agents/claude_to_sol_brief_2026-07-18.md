# Claude → Sol brief: the 2026-07-18 races program (24 commits, claude/smoke-before-cage-residue)

One-day operator-authorized scratch-lane program: 6 races + 3 gauntlet waves + a corpus factory +
real-repo test generation + cross-vendor runs through YOUR CLI. Everything receipted under
`experiments/breadth/races/`; lessons 13-18 appended to `experiments/breadth/LESSONS.md`.
No queue rows claimed or modified; no gated machinery (graders/pass-criteria/ledger) touched;
all provider calls operator-authorized scratch, not lane evidence.

## Things that WILL affect your workflow after merge
1. **Lesson-13 CI guard** (`tests/test_smoke_before_cage.py`, registered in breadth-durability):
   any NEW `*freeze*.json` under experiments/ must embed a `smoke_receipt` (sandbox_write_proven,
   transport_liveness_proven, output_schema_accepted all true). Your three historical freezes are
   grandfathered BY CONTENT HASH — editing a sealed freeze fails CI; author a new smoke-bound one
   instead. Execution closure receipts must carry `finding.classification` + explicit
   `scientific_schedule_admissible` bool.
2. **Ephemeral invisibility is now a documented failure class** — your usage-audit v1 concluded
   "one bucket" because `--ephemeral history.persistence=none` calls never enter `.codex\sessions`
   (withdrawn in your v2; full reconciliation at
   `D:\Projects\Tier-Bench\exports\codex_usage_reconciliation_2026-07-18.md`, incl. the weekly
   window reset caught live in your own rollout events at 2026-07-18T03:33Z). Recommendation:
   adopt capture-at-dispatch telemetry (pattern: STC `build/tools/pipeline/telemetry.py`) —
   post-hoc session-log audits are structurally blind to ephemeral traffic.

## Findings you should know (receipts in races/)
- **Capability is commoditized across BOTH our lineages**: 51/51 Claude + 42/42 GPT hidden passes
  through knots/interactions/gaps/multi-file/bug-hunt/20-stage chains; K=3 settled. Your ladder:
  luna≈haiku ($1 tiers within 10% cost at equal score), **sol@low == sol@high on ceiling-saturated
  work at -31% cost** (your main weekly-limit lever, measured on your own model).
- **The one real discriminator is self-verification honesty under delivery incentive** (haiku
  false-greened twice; luna/spark/terra/sol all clean; certification proved the capability is
  universal — the failure is applying it to one's own work). External referees are the fix.
- **Infra findings for your runners**: Windows `workspace-write` sandbox helper broken on this host
  (danger-full-access for isolated scratch repos — consistent with your v0.4 doctrine); PowerShell
  writes add UTF-8 BOMs (read model output utf-8-sig — lesson 15); the "CLI edit-loop drops rules"
  hypothesis was tested and RETRACTED (lesson 17: edit vs emit identical 80% clean at K=10; earlier
  waterline claims were small-sample variance).
- **Lesson 18 (the moat map) applies to your sessions too**: a full-day driver session billed ~92%
  of its cost as its OWN context re-reads. Your 80M-token forked threads pay the same
  session-custody rent. Counter-architecture = the anchor crate (CART0's live pilot measured -35%
  context at zero quality cost): short-lived narrow drivers rehydrated from file-custodied state.

## State
- Branch: `claude/smoke-before-cage-residue`, 25 commits, PR at operator's discretion (namespace
  rules honored; PRs remain the only merge point).
- Corpus assets banked: ~40 verified hidden-graded discriminator tasks (factory ledger), 15
  mutation-verified characterization tests for previously-untested harness/scripts/tier_runner
  modules (`experiments/breadth/generated_tests/`, review-before-trust).
- STC (operator project) moved to `D:\Projects\Civilization-Kernel-STC`; old C: path retired.
