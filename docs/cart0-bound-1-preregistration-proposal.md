# CART0-BOUND-1 — inactive preregistration and queue-row proposal

Status: **PROPOSED / NOT AUTHORIZED / ZERO SUBJECT DISPATCHES**.

This proposal implements only B1 functional equivalence. It does not activate
B2 causality, B3 capacity, B5 portability, B6 economics closure, or B7
production custody. `CART0-B4-ATTACK-1` found six safety gaps; the operator must
decide whether to repair and re-freeze the bridge before activating this study,
or intentionally test the frozen vulnerable revision as-is.

## Question and claim boundary

Across a small, frozen set of previously unused hidden-graded tasks, does a
<=256-token CART0 anchor plus mechanically selected cards retain the task
performance of complete pinned project context while materially reducing
provider-reported input usage?

The study reports paired outcomes and named failures. It cannot establish
universal non-inferiority, a context-window solution, production safety, or
cross-provider portability.

## Frozen design requiring operator ratification

- **Cells:** three distinct task IDs x two arms = six fresh subject sessions.
- **Task selection:** before packet export, the coordinator freezes an
  eligibility manifest of existing hidden-graded tasks never used in a CART0
  result, then selects the first three by UTF-8 task ID. No grader, vector,
  task, or pass criterion is changed.
- **Arm A:** exact task bytes plus the complete pinned project-context files.
- **Arm B:** identical task bytes plus one <=256-token-proxy CART0 anchor and
  cards selected mechanically for the same transition.
- **Freeze:** evidence HEAD, reducer, profile, full-context file list, card
  revisions, card review labels, task IDs, packet exporter, model, effort,
  provider, tools, turn schedule, grader, and output contract are hash-bound
  before the first dispatch. Cards cannot change after any response disclosure.
- **Subjects:** one fresh packet-only instrument session per cell. No subject
  receives the repository, queue, peer response, hidden grader, or comparison.
- **Turns:** fixed two-turn protocol for every cell. Turn 1 accepts either the
  candidate or a machine-readable rehydration request. Turn 2 supplies only the
  requested pinned spans, or an equal-form neutral no-additional-evidence
  message, then requires the final candidate. No planning turn rehearses the
  deciding constraint.
- **Sealing:** exact prompt, response, usage telemetry, tool events,
  rehydration request/result, candidate bytes, thread/turn identity, timestamps,
  and hashes are preserved before grading. Candidates are sealed before the
  unchanged hidden grader runs.
- **Comparison:** per task, report A/B hidden grade, prohibited-action
  violations, rehydration requests, incorrect retrievals, input/output tokens,
  cache writes/reads, latency, and billed cost. Never average away a paired
  disagreement.
- **Failure default:** broken dispatch, missing telemetry, invalid output,
  grader error, or custody failure is `PARTIAL`; it mints neither pass nor fail.
- **Stopping rule:** exactly six valid dispatch attempts; no replacement cells
  or retries after response disclosure.

## Analysis rule requiring explicit operator choice

Recommended conservative rule: call B fidelity-preserving **for this frozen
sample only** iff every task passed by A is also passed by B, B introduces zero
additional prohibited-action violations, and all custody checks pass. Otherwise
report the exact A-pass/B-fail tasks as missing-context or card-boundary
counterexamples. This is an analysis label, not a change to any task's grader or
pass criterion.

The operator must ratify or replace this rule, plus the exact model, effort,
provider, and eligibility manifest, before the queue row can become claimed.

## Economics recorded, not closed

Record provider telemetry for:

```text
compilation cost + card-review cost + retrieval overhead
versus repeated full-context input cost
```

Report cache writes and reads separately. Calculate break-even only after real
billed per-task savings exist. Subscription runs retain
`cost_basis: subscription-derived`; no fabricated dollar conversion is allowed.

## Exact proposed queue row

This line is a proposal to append to `docs/agents/QUEUE.md`; this document does
not activate it:

```markdown
| CART0-BOUND-1 | Preregister and run the bounded CART0 B1 fidelity experiment: freeze three eligible distinct hidden-graded tasks, export paired full-context vs <=256-token-anchor-plus-card packets, dispatch six fresh packet-only subjects, seal raw prompts/responses/usage/candidates before unchanged hidden grading, and compare paired fidelity, violations, retrievals, latency, tokens, cache telemetry, and billed cost | sol | driver (administration only; subjects are fresh packet-only instruments) | **open — blocked on operator ratification of model/effort/provider, eligibility manifest, analysis rule, and the disposition of six CART0-B4-ATTACK-1 gaps** | future preregistration, frozen packet manifest, six raw custody receipts, unchanged grader outputs, and paired comparison | Scope forbids card changes after any response disclosure, retries/replacement cells, grader/vector/task/pass-criterion changes, production integration, Genesis-signing claims, B2-B7 claims, and any universal context-window verdict. |
```

## Activation blockers

1. Operator ratification of model, effort, provider, task eligibility manifest,
   and the sample-level analysis rule.
2. Operator decision: repair/re-freeze the six B4 gaps first, or deliberately
   test commit `dbfc13d` as the vulnerable frozen candidate.
3. The proposed queue row must be appended and claimed by commit before packet
   construction or any subject dispatch.

Until all three are satisfied, no B1 prompt may be sent and no hidden grader may
be invoked.
