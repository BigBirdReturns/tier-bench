# Claude floor run — the ARC-C almanac pairing, Claude lane

**Run:** `claude-floor-arcc-almanac-20260711` · solver: `claude-haiku-4-5`
(Agent-tool subagents, cold, text-only quarantine, `tool_uses: 0`) · coordinator:
`claude-opus-4-8` (this session) · K=3 per task · cost: subscription-derived,
$0.00 real-billed.

This is the **Claude-lineage half** of the cross-engine ARC-C almanac pairing.
Sol (GPT-5.6 via Codex) sealed the other half as `arc_c_almanac_v1`
(`data/orchestration/`, `origin/codex/arc-c-residue-broker`). Both halves solve
the same three hidden-graded almanac knot tasks, pinned to the same
`source_commit` **e416462**, at K=3.

## Protocol

- **Sealed source.** All grading ran in a detached worktree pinned at
  `e416462fdf36c711faf06717212d8de19cd07216`. At that commit the three task
  manifests hash to `392dd0d1…` / `b9c20e53…` / `0e7c6760…` — **byte-identical
  to the manifest hashes Sol declared** in `arc_c_almanac_v1.json`.
- **Quarantine.** Each solver worked entirely from a single prompt message: no
  tools, no repo, no files. Hidden vectors were never in any solver context.
- **Seal before grade.** All 9 candidates were sha256-sealed (`seals.json`,
  reproduced in each `grade_receipt.json`) **before** any grader ran. Every
  sealed hash equals the hash the grader later read back (`seal == graded`
  verified for all 9).
- **Independent hidden grading.** `scripts/grade_solver_packet.py` copied the
  solver packet, wrote the candidate into `input.py`, compiled it, ran the
  visible check, then injected the hidden grader and ran it **twice**
  (determinism check). All 9 grades were deterministic across the two runs.

## Result

| Task | Passes (K=3) | Clears floor (K-of-K) | Broker decision |
|---|---|---|---|
| `almanac_exception_class_001` (T2, life-path master numbers) | **3/3** | ✅ | seal @ floor |
| `almanac_record_binding_001` (T3, day+hour pillars) | **3/3** | ✅ | seal @ floor |
| `almanac_rule_boundary_001` (T3, year+month solar pillars) | **2/3** | ❌ | escalate @ floor |

**8 of 9 candidates passed. The Claude haiku floor clears two of the three
tasks; it does NOT clear `almanac_rule_boundary_001`.**

### The discriminating knot: lichun year boundary

The single failure is `rule_boundary` trial r3. Its hidden vectors:

```
FAIL (2020, 2, 3, 12.0, 0.0): got ('庚子','己丑'), want ('己亥','丁丑')
FAIL (2020, 2, 4, 3.0,  0.0): got ('庚子','己丑'), want ('己亥','丁丑')
FAIL (2020, 2, 4, 12.0, 8.0): got ('庚子','己丑'), want ('己亥','丁丑')
```

r3 chose the solar year with a **civil-month proxy** (`if m >= 2: year = y`)
instead of the sun's longitude. Early-February 2020 births fall **before**
λ reaches 315° (lichun), so the solar year is still 2019 (己亥) — but the proxy
reports 2020 (庚子). The two passing candidates got this right: r1 with an
explicit `m == 2 → λ ≥ 315` check, r2 by binary-searching the lichun instant.
This is exactly the knot the task was built to catch: the spec says every
boundary is a position of the sun, and the civil calendar is a decoy.

## Cross-lineage contrast (floor vs floor)

Sol's `arc_c_almanac_v1` floor (GPT-5.6-sol, low effort) **cleared all three
tasks 3/3**, including `rule_boundary`. The Claude floor (haiku) clears only
two. At the decision level:

| Task | Sol floor (GPT-5.6) | Claude floor (haiku) | Agree? |
|---|---|---|---|
| `exception_class` | cleared 3/3 → seal@floor | cleared 3/3 → seal@floor | ✅ |
| `record_binding` | cleared 3/3 → seal@floor | cleared 3/3 → seal@floor | ✅ |
| `rule_boundary` | cleared 3/3 → seal@floor | **2/3 → escalate@floor** | ❌ |

**Honest reading:** on 2 of 3 tasks the cheap floor of both lineages is
frontier-equivalent; on the third, the GPT-5.6 floor absorbed the lichun knot
that the Claude haiku floor did not reliably clear at K=3. This is a genuine
capability difference at the floor rung, not a harness artifact — same source
commit, same manifests, same hidden graders, sealed-before-grade on both sides.

## Two protocol findings (why this is a contrast, not a sealed pair)

**Finding 1 — packet non-reproducibility / custody gap.** Sol's exported
solver packets were never committed byte-for-byte; only their hashes were. The
export bakes a platform-dependent baseline execution into `PROMPT.md`, so a
packet rebuilt on Linux (`6d933131…` for exception) does not reproduce Sol's
declared packet bytes (`232a4421…`). The cross-engine comparator
(`compare_engine_runs.py`) is robust to this — it keys comparability on
`source_commit` + `task_manifests` + `task_set` + normalized `rungs` + `k`, NOT
on packet bytes — so a valid comparison is still runnable. But the packet is
not the reproducible custody object the protocol implies it is; the manifest is.

**Finding 2 — engine-identity asymmetry (why the pair cannot seal from this
session).** Sol sealed `arc_c_almanac_v1` with `pairing.peer_engine_id =
"claude_fable_5"` — it expected the Claude peer to be **fable-5 at low effort**.
This run used the breadth **floor** solver, `claude-haiku-4-5`, because the
fable quota was exhausted (fable is reserved for the next-rung / knot-authoring
work). Two consequences under the sealed schema
(`schemas/orchestration_run.schema.json` + `validate_orchestration_run.py`):

1. The comparator requires `left.pairing.peer_engine_id == right.engine.engine_id`.
   Sol's declared peer (`claude_fable_5`) ≠ this run's honest engine
   (`claude_haiku_4_5`). Relabelling haiku as fable to force a green
   `comparable` would misrepresent provenance — the exact self-gaming the
   harness forbids — so it was **not** done.
2. Independently, a **sealed** orchestration run may contain no `escalate`
   decision. Because `rule_boundary` is 2/3 at the floor, the deterministic
   residue-broker decision for that task is **escalate**, so a truthful Claude
   run is `status: partial`, not `sealed`. The comparator requires **both**
   sides sealed, so it would return `unpaired` regardless of the identity
   question.

Either finding alone blocks a schema-sealed pair from this session. Together
they say the same thing: **the first genuine cross-lineage seal needs the
reserved fable-5 floor run (which may itself escalate `rule_boundary`), plus a
reviewed merge of Sol's ARC-C broker onto main.** What this run delivers is the
honest precursor — a real, sealed-before-grade, hidden-graded Claude floor
measurement that can be dropped straight into the comparator once the peer
identity is reconciled and Sol's broker lands.

## What is NOT claimed

- **Not a sealed pair.** No `compare_engine_runs.py` green result is claimed;
  see Finding 2. The decision-level contrast above is read directly off both
  runs' hidden grades, not off the comparator.
- **Not a fable-5 run.** The solver was `claude-haiku-4-5`. The pairing Sol
  sealed against names `claude_fable_5`; reconciling that is operator/Fable work.
- **No waterline or capture-ledger writes.** This is a run record under
  `experiments/breadth/run/`, not a settled-tier or amortization claim.

## Addendum (2026-07-12) — fable-low escalation clears the residual

Per the roadmap's own rule ("one attempt per tier; if it fails, escalate; do
not retry") and the residue-broker's effort ladder, `almanac_rule_boundary_001`
was escalated one rung from the haiku floor (2/3, did not clear) to
**fable-low** (K=3, same sealed packet, same hidden grader, same worktree
pinned at `e416462`).

**Result: 3/3 — clears K-of-K.** See
`escalation_fable_low/almanac_rule_boundary_001/{f1,f2,f3}/` and
`escalation_fable_low/receipt.json`. All three candidates handle the lichun
boundary correctly (each with a different, independently-derived boundary
test), unlike the haiku floor's r3, which used a civil-month proxy. Sealed
(sha256) before grading; all three seals match their graded hashes; hidden
grader run twice per candidate, fully deterministic.

**This closes the one open task-level gap from the floor run**, purely at the
Claude-lineage effort-ladder level: `exception_class` and `record_binding`
clear at floor, `rule_boundary` clears at fable-low. It does **not** change
either protocol finding above (packet non-reproducibility; the Sol pairing
still names `claude_fable_5` as the peer, and the ARC-C schema/broker/
comparator still only exist on `codex/arc-c-residue-broker`) — those are
identity/tooling gaps, not capability gaps, and this run doesn't touch them.

**Secondary purpose:** this batch was also run to put real Fable token data
into `experiments/breadth/quota.py`'s gauge, which previously had haiku-only
numbers. Measured: ~15.4k new tokens/trial for fable-low on this task (first
call pays a ~46k cache-write, the other two hit cache-read on the same prompt
— so amortized cost per trial after the first is small). Logged to
`escalation_fable_low/ledger.jsonl` and appended to
`experiments/breadth/run/burn_log.jsonl`. The combined haiku+fable burn log
still contains **zero recorded `limit_hit` events**, so the quota gauge
honestly remains `UNMEASURED` — this adds real per-trial cost data, not a
quota number, which per `quota.py`'s design can only come from an actual wall.

## Addendum 2 (2026-07-12) — source-custody rebind; Sol's retraction supersedes the contrast table

PR #63's cleanup landed a **source-custody correction**
(`docs/agents/reviews/sol_arc_c_source_custody_correction_20260712.md`): the
validator had compared manifest hashes against the current checkout rather
than the declared source commit, and `e416462`'s almanac manifest bytes do
**not** hash to the declared values. Sol rebound their run to
`3d3837165ac9e046acf2cecc27e01f9c41c302e5` (the first commit containing the
exact bytes), excluded six of their nine observations for execution-time
custody violations, and downgraded the run to `partial` /
`measurement_claim: false`.

**Effect on this run's declaration (labeling defect, same class as Sol's):**
the packet receipts here declare `source_commit: e416462`, but the bytes
actually exported and graded were the codex-branch overlays — which are the
`3d38371` bytes exactly (manifests `392dd0d1…`/`b9c20e53…`/`0e7c6760…`,
hidden graders `fcc7c830…`/`fec244b9…`/`cccea756…`, all verified matching
`3d38371`). Under Sol's own adjudication standard this run's declaration is
hereby **rebound to `3d38371`**. Custody chronology: `3d38371` was authored
2026-07-10T16:09Z; every trial here (haiku floor 2026-07-11T06:51–53Z,
fable-low escalation 2026-07-12) executed after it, against those exact
bytes, with no broker-route dependence on any excluded observation. All 12
observations remain admissible. This also *confirms* Finding 1: the manifest
and grader hashes were the binding custody objects all along; the commit
label was the weak link on both lineages independently.

**Effect on the cross-lineage contrast (the table above is superseded):**
Sol's "cleared all three 3/3" is retracted for two tasks. The admissible
state after the correction:

| Task | Sol (admissible) | Claude (this run) |
|---|---|---|
| `exception_class` | **unmeasured** (3 obs excluded, pre-source-commit) | cleared 3/3 @ haiku floor |
| `record_binding` | **unmeasured** (1 excluded + 2 route-dependent) | cleared 3/3 @ haiku floor |
| `rule_boundary` | cleared 3/3 @ floor (gpt-5.6@low) | 2/3 @ haiku floor → **3/3 @ fable-low** |

The only surviving comparable cell is `rule_boundary`, where the genuine
divergence stands: GPT-5.6's cheapest rung absorbed the lichun knot; the
Claude ladder needed one rung above haiku. On the other two tasks the
lineages now hold **complementary evidence** — Claude has admissible floor
clears exactly where Sol has holes. Note the ladder alignment: Sol's "floor"
is gpt-5.6@**low**, so its Claude mirror is fable-5@low (the rung Sol's
pairing names as peer), and the haiku floor is a cheaper sub-floor rung with
no Codex counterpart — a real asymmetry the paired run manifest must state
rather than paper over.

## Burden note (docs/burden-discipline.md)

```text
requested_outcome: run the matching Claude floor half of the ARC-C almanac cross-engine pairing, sealed-before-grade against the hidden graders
claimant: the 2026-07-11 driver session (Claude, coordinator claude-opus-4-8)
authority: task manifests + hidden graders at source_commit e416462 (hashes match Sol's arc_c_almanac_v1 declarations)
predicates: candidates sealed before grading (9/9 seal==graded); hidden graders injected only at grade time; each candidate graded twice, all deterministic; solver quarantine held (tool_uses 0); source commit and manifest hashes match the peer run
burden_holder: this directory (experiments/breadth/run/almanac_floor_arcc_20260711)
evidence: receipt.json, trials/*/{candidate.py,grader_outputs.json,grade_receipt.json}, seals reproduced per grade_receipt
verifier: scripts/grade_solver_packet.py (rerun-verifiable at e416462); cross-check against experiments/breadth/run/almanac_floor_20260710 (prior Claude haiku floor, rule_boundary 1/3)
gap: not a schema-sealed pair — comparator would return unpaired. Task-level gap (rule_boundary K-of-K) CLOSED by addendum 1 (fable-low 3/3). Declaration gap (wrong source_commit label) CLOSED by addendum 2 (rebound to 3d38371; bytes verified). Remaining: Sol's broker/schema must merge (PR #63), and a schema-valid Claude run at the fable-5@low floor rung needs K=3 fable-low cells for exception_class and record_binding (rule_boundary's fable-low cell already exists)
closure_decision: partial
failure_default: keep_open — the pair does not seal until Sol's ARC-C broker merges and a schema-valid fable-5 run is produced against it
```
