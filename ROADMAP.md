# ROADMAP — the AXM build sequence (say-go runway)

**This file is the marching orders.** When Fable (or any driver) is brought in
with high effort on, the operator says **"go"** and this file is the only thing
that needs reading. Every next PR is fully specced below — files, schema,
acceptance criteria — so no frontier token is spent re-deriving a plan that is
already decided. Do not re-litigate the ordering; it is set.

## The "go" protocol

1. Read **STATE** below. Find the first PR marked `NEXT`.
2. If the previous PR's branch (`claude/setup-algstb`) is still an open PR
   (unmerged), that PR must merge first — see EXECUTION. State is
   `BLOCKED-UNTIL-MERGE`; report that and stop. One branch, serial PRs.
3. Otherwise build that one PR to a **pushed PR with green CI**, then **STOP and
   report**. One "go" = one PR unless the operator says "keep going".
4. Update STATE (flip the finished PR to `DONE`, the next to `NEXT`) as part of
   the PR. The record is the plan.

Do not free-run past a merge boundary. Do not start two PRs at once. Do not
touch #50+ before #47–#49 have landed — the foundation must be hard first.

## STATE

> **Firehose status: ARMED.** PR #47 is merged to `main`; the branch
> `claude/setup-algstb` resets clean onto it. Bring the driver in with high
> effort on and say **go** — #48 is unblocked and fully specced below.

| PR | Title | Status |
|----|-------|--------|
| #47 | AXM provenance layer | **DONE / merged** — https://github.com/BigBirdReturns/tier-bench/pull/47 |
| #48 | Frontier capture ledger | **NEXT — armed** (reset onto main, build) |
| #49 | Edge-family + almanac hidden-knot corpus | queued |
| #50 | Orchestration-pattern benchmark | not yet — needs #48 + #49 first |
| #51 | OSS replay field | not yet |
| #52 | proof-knot closure-packet demo | not yet |
| #53 | embodied AXM action-authorization schema | not yet |
| #54 | terrain-divergence simulation packet | not yet |

## EXECUTION mechanics (one branch, serial)

The driver is pinned to `claude/setup-algstb`. So the PRs are **serial**, not
parallel:

```
merge PR #N  ->  git fetch origin main
             ->  git checkout -B claude/setup-algstb origin/main   # a merged PR is finished; never stack on it
             ->  build PR #N+1
             ->  push -u origin claude/setup-algstb (retry w/ backoff)
             ->  open PR, STOP, report
```

CI that must be green before "done": `breadth-durability` (compile + smokes +
`waterline.py --check` + the provenance guard) and `validate` (if data/results
changed). Fix red CI before reporting done — that is part of the PR.

## BUDGET discipline — how not to blow the model limit

**Firehose means dense demarcation, not uncontrolled spend.** Each run must make
clear which model/effort owns which work: cheap floor for mechanical plumbing and
settled cells, driver/Fable-class judgment for schema semantics and invariant
freezes, and the Fable effort gradient (`low → medium → high → xhigh →
ultracode/max`) only on residual work, walked bottom-up. A max-effort pass
without lower-rung receipts maps a ceiling, not the frontier.

This is the repo's own thesis applied to building the repo. **Fable's tokens are
for the judgment residue only.** Every PR below is split:

- **Fable-class (spend here):** schema design, evidence-class adjudication,
  provenance calls, grader/oracle authoring, invariant freezes. The nameable,
  judgment part.
- **Cheap (route to the floor):** JSON plumbing, validators, tests, CI wiring,
  data entry from ledgers that already exist, docs. Use haiku/sonnet-low; do NOT
  spend Fable on these.

Standing rules that cap spend (full text: `experiments/breadth/LESSONS.md`):
**DO NOT ESCALATE** — never spend a frontier token re-confirming a cleared floor.
**Effort before access** — walk the effort ladder before reaching for a bigger
model. **Never rerun settled cells.** **K-of-K is a ceiling; one miss is noise.**
**Adapt freely, never self-grade** (adapt.py FREE/GATED gate). **Never fabricate
a receipt** — broken pipelines mint neither PASS nor FAIL. **PII never enters the
repo** — almanac vectors are synthetic only.

**Burden discipline is first-class.** For any PR that introduces a new validator,
ledger, result class, shard, or authorization path, include a closure packet (see
`docs/burden-discipline.md`) naming the requested outcome, authority, predicates,
burden holder, evidence, verifier, gap, closure decision, and failure default. If
that packet cannot be answered, the state is `proposal`, `partial`, `unmeasured`,
or another explicit non-closed status — never silently closed.

---

## PR #48 — Frontier capture ledger

**Title:** `Add frontier capture ledger: measure when expensive cognition becomes reusable machinery`

The economic proof. Routing is not proof; the missing object is the ledger that
records: was expensive cognition converted into reusable machinery, how much did
it cost, how many future frontier calls did it retire, when did it break even.
PR #47 already seeded the `capture_ledger` primitive (status: synthesis, flagged
*captured-not-yet-amortized*) — this PR fills in what that reserved.

**Files**
```
docs/frontier-capture.md
schemas/capture_ledger.schema.json
schemas/delta_observation.schema.json
data/capture/task02_escape_class_boundary.jsonl
scripts/validate_capture_ledger.py
scripts/capture_roi.py
tests/test_capture_ledger.py
tests/test_capture_roi.py
```

**Core capture schema** (worked task02 example is the acceptance artifact)
```json
{
  "capture_id": "task02_escape_class_boundary",
  "source_task_id": "task02_wildcard",
  "driver_model": "claude-sonnet-5",
  "driver_role": "residue_resolver",
  "capture_cost_usd": 0.681,
  "cost_basis": "real-billed",
  "captured_artifact": {
    "type": "edge_family + routing_rule",
    "path": "experiments/breadth/run/task02_edge_family.md",
    "description": "Backslash-inside-character-class invariant isolated as the rule-boundary residue."
  },
  "old_path": {"model": "claude-haiku-4-5", "status": "unstable", "success": "3/5"},
  "new_path": {"model": "claude-sonnet-5", "status": "cleared", "success": "3/3"},
  "break_even_reuse_count": null,
  "validated_replays": 0,
  "waterline_effect": "task moved from cheap-floor unstable to named sonnet-low residue",
  "status": "captured_not_yet_amortized"
}
```

**Delta taxonomy** (`delta_observation.schema.json`)
```json
{"delta_observation": {
  "from_model": "claude-haiku-4-5", "to_model": "claude-sonnet-5",
  "task_id": "task02_wildcard",
  "delta_types": ["edge_delta", "framing_delta", "routing_delta"],
  "what_lower_missed": "Backslash inside class treated as malformed escape instead of literal.",
  "what_higher_added": "Committed to literal-backslash interpretation and passed hidden oracle.",
  "capturable": true, "captured_as": "edge_family"}}
```

**Acceptance criteria**
```
- Capture ledger validates independently of data/results.
- ROI script computes break-even when old/new path costs exist.
- Capture entries distinguish real-billed, shadow-estimated, subscription-derived,
  and repaired/transport-adjudicated evidence.
- Capture entries include a burden packet: claimant, authority, predicates, burden
  holder, evidence, verifier, gap, closure decision, and failure default.
- `captured_not_yet_amortized` is a non-closed ROI state: missing replay evidence
  defaults to `needs_replay`/`partial`, not accepted amortization.
- Capture entries can link to waterline task IDs but do not mutate waterline automatically.
- At least one worked example exists for task02.
```

**Spend split** — Fable: the delta taxonomy, the evidence-class distinctions, the
break-even/amortization semantics. Cheap: the schema JSON, the validator, the
ROI arithmetic, the tests, the task02 row (data already exists in `ledger.jsonl`).

---

## PR #49 — Edge-family + almanac hidden-knot corpus

**Title:** `Freeze task02 edge-family invariants and add almanac hidden-knot vectors`

The new ruler. #47 gives provenance, #48 gives capture economics; #49 gives more
knots to measure so the project stops being "the wildcard thing." A small corpus
of black-letter hidden knots: deterministic, source-backed, hidden-graded, built
around rule-boundary commitments.

**Files**
```
experiments/breadth/run/task02_edge_family.md   # frozen as reviewed invariants, not notes
experiments/almanac/DESIGN.md
experiments/almanac/VECTORS.md
experiments/almanac/README.md
experiments/almanac/generate_vectors.py
experiments/almanac/hidden_oracle.py
tasks/almanac_rule_boundary_001.json
tasks/almanac_record_binding_001.json
tasks/almanac_exception_class_001.json
tests/test_almanac_vectors.py
```

**Knot families**
```
1. rule-boundary knot   — a written rule has one underspecified edge; commit correctly.
2. record-binding knot  — multiple records; bind the claim to the controlling source.
3. exception-class knot  — general rule applies unless a precise exception holds; classify without moving the boundary.
4. transport/adjudication knot — candidate looks wrong from serialization damage; classify transport vs capability failure.
```

**Example task manifest**
```json
{
  "task_id": "almanac_rule_boundary_001", "tier": "T3",
  "fixture": "experiments/almanac/fixtures/rule_boundary_001",
  "target_file": "solution.py",
  "public_spec": "Implement the rule exactly. Some examples are visible; edge cases are hidden.",
  "hidden_files": ["hidden_oracle.py"], "hidden_run_command": "python hidden_oracle.py",
  "knot_type": "rule_boundary",
  "source_basis": ["AXM primitive: black_letter_axm", "AXM primitive: proof_knot"]
}
```

**Acceptance criteria**
```
- task02 edge-family table is frozen as reviewed invariants, not notes.
- The invariant table names its closure authority/reviewer; disputed or unreviewed
  verdicts remain proposal-only and cannot become hidden graders.
- Almanac tasks have hidden graders and are listed by breadth_tasks.py as capability-valid.
- At least three hidden-knot tasks exist, but NO model results are claimed yet.
- Hidden graders are deterministic.
- Every almanac task links to a primitive source basis from PR #47.
- No Fable reruns of settled cells.
```

**Spend split** — Fable: freezing the edge-family invariant table (reviewed
verdicts, gated by adapt.py) and authoring the hidden oracles/vectors (grader
authoring is driver-owned). Cheap: task manifests, the generator plumbing, tests,
the synthetic PII-free vectors' mechanical bits.

---

## The arc, and why this order

```
#47 provenance      -> makes AXM attributable (no unsourced sprawl)
#48 capture ledger  -> makes frontier capture measurable (spend -> machinery)
#49 almanac corpus  -> makes the next benchmark family real (the new ruler)
#50 orchestration-pattern benchmark -> tests pilotfish/Anthropic-style routing against REAL knots
```

Orchestration (#50) is not next: without #48 and #49 it degenerates into another
"frontier orchestrator + cheap workers seems cheaper" routing demo. The measured
version — *frontier captured this knot grammar; cheap workers replayed it;
verifier caught failures; waterline moved; capture ledger computed amortization* —
requires the capture ledger and the knot corpus to exist first.

#51 OSS replay field · #52 proof-knot closure-packet demo · #53 embodied AXM
action-authorization schema · #54 terrain-divergence simulation packet — all
after the foundation is hard. Do not jump.
