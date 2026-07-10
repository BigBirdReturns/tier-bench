# QUEUE.md — the shared assignment authority (both lineages)

*One queue, two readers. Claude sessions load `CLAUDE.md` → pointed here; Sol
sessions load `AGENTS.md` → pointed here. A task exists when it has a row; a
task is claimed when a commit flips its `state`; a task is done when its
`evidence` path exists and CI is green. Content keys only — never PR numbers.*

## Queue law

1. **Claim before work**: flip `state: open → claimed` (with your session/date
   in `note`) in a commit on your own branch before starting.
2. **Lane is binding**: `driver` rows get the repo; `subject`/`instrument`
   rows get a generated packet only — never both in one context.
3. **Done needs evidence**: a row closes only by pointing at committed
   artifacts (receipts, sealed layers, merged PRs) — burden discipline applies.
4. Owners: `sol` (GPT lineage), `claude` (Anthropic lineage), `either`,
   `operator` (human-only steps).
5. Append new rows; never delete history — strike through superseded rows.

## Active queue

| id | task | owner | lane | state | evidence when done | note |
|----|------|-------|------|-------|--------------------|------|
| SOL-1 | Blind-grade control packet (80 items, **v2**): return `[{id, score, rationale}]` per packet instructions | sol | **instrument** | **done** — one sealed v2 run, 2026-07-10 | `docs/agents/reviews/sol_1_blind_control_v2_20260710.md`; raw artifact + session record under `data/control-results/_external_grade_runs/sol-1-v2-019f4d56-c26f-7ec0-9d3e-67819c2270ec/` | Exact baseline agreement 48/80; 32 off by one; zero off by two. Operator reported a second attempt, but no second thread/artifact was discoverable, so it is not counted. |
| SOL-2 | Adversarial review of the capture ledger (`data/capture/`, validator, ROI) + almanac corpus (`tasks/almanac_*`, vectors, graders) — hunt the defect class same-lineage review missed | sol | driver (read-only) | **done** — 2026-07-10 | `docs/agents/reviews/sol_arc_ab_review_20260710.md` | Two P1 closure holes and four P2 durability defects recorded; remediation remains gated and open. |
| SOL-3 | Independent-architect pass on the Residue Broker (ARC-C) | sol | driver | **superseded / independence precondition lost** | PR #63 plus explicit contamination note | Operator-directed ARC-C implementation began before the coordination merge. This repo-aware author context cannot honestly recreate an independent-before-conclusions architecture pass. |
| ~~CLAUDE-1~~ | ~~Push blind packet to temp repo~~ — superseded: v1 bytes unavailable, SHA `64e33f2a…` irreproducible from any committed state (100-commit sweep, Claude 2026-07-10) | claude | driver | **superseded by CLAUDE-1b** | — | v1 packet existed only in the original session's working copy. |
| CLAUDE-1b | Verify packet **v2** delivery (coordinator pushed; supersession record `docs/agents/BLIND_CONTROL_V2.md` on codex branch) | claude | driver | **done** — independently verified 2026-07-10 | `docs/agents/BLIND_CONTROL_V2_VERIFICATION.md` | Commit `6771868` / single-file tree / schema / 80 items / no leaks: **confirmed**. Declared SHA `98997bf9…` is the CRLF rendering; canonical in-git digest is `e1a1dc6bfcee26a435e23107d08019870153ceb1cf6e646b46317663ad8afd06` (transport adjudication, not integrity failure). Key-side claims remain single-source until key disclosure. |
| CLAUDE-2 | Replays 2–4 of the task02 capture: DISTINCT task02-class work items (frozen edge-family variants / almanac knots), floor + scaffold packet, hidden-graded | claude | driver (subjects are cold floor runs) | **done** 2026-07-10 (2 validated + 1 partial; amortizing 3/4) | receipts under `run/replays/`, ledger rows, capture row update | Same-instance repeats do not count; 2 of 4 validated (crossing + replay03); replay02 spoiled 0/3, replay04 1/3 did not. |
| CLAUDE-3 | Same-session bare-vs-packet A/B on task02 (closes the prompt-wording confound named in the capture row) | claude | driver | **done** 2026-07-10 — confound closed (bare 3/5 vs packet 4/5, zero knot misses in packet arm) | sealed layer + confound note resolved in capture row `gap` | Cheap; shadow-estimated. |
| CLAUDE-4 | ARC-A P1 hardening: capture closure depends on distinct hash-bound replay events + computed break-even (one shared calculation) | claude | driver | **done** — PR open 2026-07-10 | `scripts/capture_math.py`, hardened `validate_capture_ledger.py`, restructured task02 row, `data/continuity/EPISODES.md` EP-001, 32+8 tests | Bounded repair from main; PR #63 untouched. Defect preserved as provenance (representation could not prove distinctness; claim itself was true). |
| OP-1 | Create empty private repo `BigBirdReturns/tier-bench-blind-grade-001` (no README/.gitignore) and grant the Claude GitHub integration access | operator | — | **done** 2026-07-10 | repo exists (verified private at add time); Claude integration access verified by clone | Session credential gets 403 on repo creation — human-only step. |
| ARC-C | Orchestration-pattern benchmark over the real knots | either (lead: claude) | driver | **in progress / partial** — Codex engine run sealed; paired conclusion open | compatible sealed Claude run plus comparator output | Codex floor is 3/3 on all three almanac cells with no escalation. Keep lineages separate: Claude summaries are not compatible receipts, and PR #63 is not a paired completion claim. |

## Done (most recent first)

| id | task | evidence |
|----|------|----------|
| SOL-1 | Non-Anthropic blind grade of the preserved control packet | `docs/agents/reviews/sol_1_blind_control_v2_20260710.md`; thread `019f4d56-c26f-7ec0-9d3e-67819c2270ec`; raw artifact SHA-256 `da69f26d…16af04c` |
| PACKET-V2 | Supersede unavailable blind-control v1 with private-salted v2 | `docs/agents/BLIND_CONTROL_V2.md`; private delivery commit `6771868`; canonical in-git digest recorded above |
| SOL-2 | Cross-lineage adversarial review of ARC-A capture + ARC-B almanac | `docs/agents/reviews/sol_arc_ab_review_20260710.md`; executable counterexamples; PR #63 |
| — | ARC-B: edge-family freeze + almanac corpus | PR #59, layer + CI drift guard |
| — | Crossing event: first validated replay (amortizing 1/4) | PR #58, `run/replays/task02_wildcard/` |
| — | ARC-A: frontier capture ledger | PR #57 |
| — | Blind-grading export/merge pipeline | PR #61 |
| — | Sol handoff doc | PR #60, `docs/agents/SOL_HANDOFF.md` |
