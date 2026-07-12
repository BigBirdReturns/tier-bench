# A/B/C causal test — decision-boundary resurfacing on `count_matches`

**Run:** `abc-causal-task02-20260711` · coordinator: the 2026-07-11 driver session
(Claude, lead agent) · solver: claude-haiku-4-5 fresh subagents · K=5 per
condition · cost: ~$0.85 shadow-estimated, $0.00 real-billed.

Design as pinned in the CART0 contract addendum
(`data/continuity/CART0_CONTRACT.md`, branch `claude/capture-ledger-p1-hardening`),
with the operator's one logged FREE-class adaptation: the **work item is held
constant** across conditions — `count_matches`, the deepest-embedding shape,
where the boot-load regression was measured at 1/3 (replay04, layer
`claude2-distinct-replays-20260710` on `claude/driving-assistance-r5mtu1` @ 72adaac).
Fresh sessions cannot contaminate each other; a constant item isolates the
boundary variable exactly.

## Protocol

- **Map constant:** every solver booted with the identical context — the
  emit_scaffold task02 packet (rule commitment + discipline), spec.md, visible
  tests (committed here as `turn1_prompt.txt`; hidden vectors + grader pinned
  under `hidden_used/`, byte-identical to the replay04 materials).
- **Two turns:** turn 1 plan-only (no code); turn 2 delivers the condition
  message at the decision boundary (`turn2_{A,B,C}.txt`, 55–60 words each):
  - **A** boot-only: neutral equal-length go message.
  - **B** applicable constraint resurfaced (in-class backslash is literal).
  - **C** recency control: equal-length valid-but-irrelevant constraint
    (DO-NOT-ESCALATE wording).
- **Quarantine:** solvers instructed no tools / no files / no repo;
  `tool_uses: 0` on all 30 agent turns. Hidden vectors never in any solver
  context; held by the coordinator only.
- **Sealing:** all 15 candidates extracted mechanically and sha256-sealed
  (`trials/*/seal.json`) BEFORE any grading; grader then run twice per
  candidate (determinism check).
- **Key material verified before any trial:** replay04 reference solution
  scores 10/10 on the pinned grader; a naive escape-inside-class
  implementation scores 6/10 — exactly the replay04 trial0 baseline score,
  corroborating vector fidelity.

## Result

| Condition | Perfect (10/10 hidden vectors) | Knot-vector failures | Deterministic |
|---|---|---|---|
| A — boot-only | **5/5** | 0 | 5/5 |
| B — applicable resurfaced | **5/5** | 0 | 5/5 |
| C — irrelevant control | **5/5** | 0 | 5/5 |

**Ceiling. No separation measured.** The predicted condition-A regression
(the replay04 1/3 behavior) did not appear anywhere: 15/15 candidates passed
all ten hidden vectors including every backslash-knot vector.

## Interpretation (hypothesis, not a sealed claim)

**The two-turn protocol itself defused the knot.** Turn-1 plan-only
elicitation caused **14 of 15 solvers to restate the rule commitment in their
own plan** ("Key rule from packet: inside `[...]`, backslash is NOT an escape…"),
and the 15th implemented it correctly regardless. Writing the constraint into
one's own plan is self-administered resurfacing: by the time the boundary
message arrived, every condition was effectively condition B.

The honest contrast this run adds is therefore not A-vs-B but
**protocol-shape**: same model, same packet, same work item —

- single-turn, packet-at-boot, straight to code (replay04): **1/3**, misses on
  the exact captured rule;
- two-turn, plan-first (this run, pooled): **15/15**.

That is a large measured effect of *making the solver rehearse the map before
acting* — CART0's mechanism confirmed from an unexpected direction: decision-
point resurfacing works even when the solver is the one who performs it, at
plan time. What this run does NOT establish is the marginal value of
protocol-delivered boundary messages once rehearsal has occurred (redundant
here), nor anything about the 256-vs-4096-token resolution axis.

This is LESSONS rule 11 operating at the protocol layer: spec guarantees can
defuse a knot, and so can an elicitation step that invites the solver to
recite the deciding constraint.

## Next iteration (proposal only — GATED, operator review)

To unmask the boundary variable, the next design must prevent plan-time
rehearsal from saturating the effect: (a) single-turn with an absorbing
prefix task (the original replay04 shape) and the condition message injected
mid-stream; or (b) plan turn constrained to architecture-only with the
constraint-recitation channel closed. Prediction to test: A regresses toward
the 1/3 baseline while B holds ceiling.

## What is NOT claimed

- No waterline or known_corner writes; this directory is proposal-layer
  evidence pending operator seal.
- **Not a validated replay** for the capture ledger: same work instance as
  replay04 (`count_matches`) — the same-instance rule forbids credit.
- The 1/3-vs-15/15 contrast spans two sessions and prompt shapes; the
  replay04 baseline's exact bytes were not re-run here (named confound, same
  class as the bare-vs-packet wording confound already on the capture row).

## Burden note (docs/burden-discipline.md)

```text
requested_outcome: record the A/B/C causal run as sealed proposal-layer evidence (ceiling; no separation)
claimant: the 2026-07-11 driver session
authority: pinned task02-derived hidden vectors (hidden_used/, byte-pinned) + CART0 contract design
predicates: candidates sealed before grading; grader deterministic (2 runs each); key material verified naive-fails/reference-passes; solver quarantine held (tool_uses 0)
burden_holder: this directory
evidence: trials/*/ (raw, candidate, seal, grader output), grades_summary.json, turn prompts
gap: A/B/C separation unmeasured (protocol saturated it); resolution axis untouched; baseline bytes not re-run
closure_decision: held (pending operator review)
failure_default: keep_open
```
