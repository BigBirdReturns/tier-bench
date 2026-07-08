# HYPOTHESES — the original claims vs. the data we now have

The repo was built on nameable hypotheses. This file is the ledger where they
meet measurements: every verdict cites rows you can re-derive (constitution §2:
measured and hypothesis are different words). Updated 2026-07-08, after the
first hidden-graded K=3 floor, real-dollar effort calibration, and the first
cross-provider rows.

## H1 — The commodity-markup thesis

> "Most of what people buy from frontier models is commodity work at a large
> markup; the genuinely frontier part is small, nameable, and worth measuring."

**Verdict: SUPPORTED on every cell measured so far.** haiku (~$0.037/trial,
shadow-priced) and fable@low (~$0.48/trial, real-billed) produced *identical
outcomes* on all cells where both ran — a ~13× price gap for equal results
(ledger: fable@low calibration 9/9; haiku floor 3/3 on the same tasks). The
frontier residue found to date is exactly one cell wide and precisely
nameable: task02's escape-inside-class malformed-vs-non-match judgment
(3/5 at the floor; `run/task02_edge_family.md`).
**Scope caveat:** 5 breadth cells + 14 router tasks, single-digit K, one
cheap model. Small, but the direction is unambiguous.

## H2 — The tier ladder (T0–T5 difficulty classes discriminate models)

> tasks/*.json tiers separate cheap from frontier; models carry tier_ceilings.

**Verdict: CHALLENGED — the axis is wrong, not the ruler.** With hidden
grading (so no answer-key reading), haiku 4.5 cleared T0 through **T4** 3/3 —
including the T4 plan-validity semantic judge and the hard-T3 spec task
(ledger 2026-07-08; `run/known_corner.jsonl` layer k3-floor-20260708).
GPT-5.5 matches from the subscription surface (task06 receipt; task01/02
derived-probable pending clean captures). **Difficulty-tiered spec-following
does not separate 2026 models at any tier we can author.** What separated
anything was task *type*: derivation/judgment (task06 counterexample
construction; task02's judgment boundary) vs. spec-following. The ladder's
new axis is settled-vs-derived work, not junior-vs-staff difficulty.
models.json `tier_ceiling`s remain DECLARED for every model without measured
rows — but "haiku: T2" is now measurably wrong as a ceiling; its
hidden-graded floor is ≥T4 on spec-following.

## H3 — Uplift: cheap + harness reaches the tier above

> What a cheap model lacks is carried state and selection, not judgment;
> a harness supplies both.

**Verdict: SUPPORTED, with a sharpened mechanism.** The lens harness lifted
haiku through the T3 bug/security tasks (Phase 1); *framing* lifted it through
task06 — prompted to *search* for a counterexample (the harness move), haiku
found genuine ones 3/3, though it may not have *judged* the code wrong
unprompted (caveat recorded in the sediment). The uplift claim survives in a
stronger form: the harness converts derivation tasks into search tasks, and
cheap models can search.

## H4 — Designed right, you never escalate access

> Effort before access; the cascade clears everything before quota runs out.

**Verdict: SUPPORTED twice.** Two full runs ended DO NOT ESCALATE with empty
residuals. The one Fable spend ($4.31, fable@low calibration) was ruled a
process error after the fact (LESSONS rule 2: don't pay frontier prices to
re-confirm a cleared floor) — i.e., even our only frontier spend was
avoidable. A real session-limit wall was hit mid-run and resolved by waiting,
not upgrading.

## H5 — Disposition lives in the weights, flat on effort

> (From the control-set baseline: opus 18=18, haiku 14=14 across effort.)

**Verdict: UNCHANGED (single-source, lineage-flagged).** Nothing this
overhaul measured contradicts it; fable@low solving everything it touched is
weakly consistent (low effort lost nothing). Still needs the independent
non-Anthropic grader and a second contributor (HANDOFF gap 2).

## H6 (new, minted by this overhaul) — The frontier residue is judgment at
## boundaries, not capacity at scale

Every crack found so far is a *decision between two valid rules* on a
pathological input (malformed-vs-non-match; counterexample-vs-review framing),
never a failure to follow a stated rule. **Falsifiable prediction:** the
task02 edge-family probes (8 designed) and almanac boundary vectors
(lichun/jieqi/tz/cusp) will separate models *within* the same task where
difficulty tiers did not — and the separation will track model, not effort.

---

## The going-forward test plan (what would move each verdict)

| Priority | Test | Moves | Needs |
|---|---|---|---|
| 1 | Clean GPT-5.5 task02 captures (3 pastes, raw-function transport) | H1/H2 cross-provider | operator UI, ~10 min |
| 2 | Freeze the task02 edge-family invariant table → build probes → run haiku/sonnet/gpt/fable-low K=3 | **H6 (the new thesis's first real test)** | operator review of the invariant table (gated), then cheap trials |
| 3 | Almanac boundary vectors as the second judgment family (synthetic, PII-free) | H6 generality | driver authoring + cheap trials |
| 4 | Re-axis models.json: `tier_ceiling` → measured `settled_floor` + `judgment_residue` fields where rows exist; everything else stays declared | H2 repair | no spend |
| 5 | Non-Anthropic grader over the control-set verbatims + second contributor | H5 | any OpenAI/Gemini key or a human hour |
| 6 | Fable medium→max rungs | nothing yet | **do not run** until a wall exists (LESSONS rule 2) |

The router (orchestrator + cost guard) is unaffected as *plumbing* — but its
routing table should eventually key on settled-vs-derived task class, not
tier difficulty. That is the product consequence of H2's verdict.
