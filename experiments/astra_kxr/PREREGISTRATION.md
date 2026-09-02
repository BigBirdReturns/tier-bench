# ASTRA-KXR-1 — Preregistered recurrent compute-geometry fingerprint (stage-1 freeze)

```yaml
id: ASTRA-KXR-1
stage: 1
frozen_at: 2026-09-02
subject: the OpenAI model publicly named Astra, once an exact callable model
  identifier exists; no such identifier is bound by this document
base_head: 8013709c6aaedc129905bf622df7a9a759891f42
instrument: frontier_fingerprint observatory (this repository)
governing_doctrine: HYPOTHESES.md (H1, H6), experiments/model_waterlines,
  LESSONS rule 2 (effort before access)
decision_rules: experiments/astra_kxr/DECISION_RULES.json
limitations: experiments/astra_kxr/KNOWN-LIMITATIONS.md
claim: docs/agents/claims/CLAUDE-ASTRA-KXR-PREREG-1.md
```

## 1. What this document claims, and what it does not

This preregistration freezes hypotheses, campaign design, admission gates,
analysis structure, and terminal states for a black-box measurement of
Astra's externally observable compute geometry, before Astra is callable.

Chronology, stated so a hostile reader can check it:

- The measurement instrument and its doctrine predate Astra's public
  existence: the first Fable 5 disposition baseline landed 2026-07-07
  (PR #6), the doctrine ledger 2026-07-08 (PR #43, HYPOTHESES.md), and the
  driver-boundary hypotheses were preregistered 2026-07-13 — all before the
  first public Astra report (2026-08-07).
- The frontier-fingerprint observatory, including its `astral-candidate`
  placeholder manifest, was committed 2026-09-01/02, AFTER Astra's name was
  public. No claim of pre-naming anticipation attaches to that manifest.
- This preregistration is valid as a prediction record only if its freeze
  commits are in remote custody before Astra is publicly callable. If Astra
  becomes callable first, the document remains a protocol but loses its
  prediction standing, and must say so wherever cited.

The public evidence tier at freeze time: OpenAI confirms Astra's existence,
Critical cyber designation, token-efficiency claim versus GPT-5.6 Sol, and
chain-of-thought monitoring plus classifiers; a single paywalled report
attributes recurrent depth (repeated processing through the same layers);
no public source confirms a parallel-latent K×R architecture. The K-blocks ×
R-iterations construction is LOTUS's (arXiv:2606.31779), not a confirmed
property of Astra.

## 2. Governing order — waterline before geometry

Per H1 (the measured frontier residue to date is narrow and nameable) and H6
(the residue is judgment at boundaries, not capacity at scale), the campaign's
first authority question is the waterline question: does Astra clear cells
that the cheap floor and local controls do not, and at what shadow price?
Architecture geometry is instrumentation captured on the same calls, and is
the explanation for residue found — never the headline over it. Budget
discipline follows LESSONS rule 2: cheap floors first, one attempt per rung,
escalate only real walls, never pay frontier prices to re-confirm a cleared
floor.

## 3. Hypothesis families and expected signatures

Task-level width K = number of independent active lanes; task-level depth
R = length of the dependent transformation chain per lane. E = the provider's
exposed reasoning-effort setting, treated only as a proxy for internal
computation. Expected external signatures, conditional on truthful provider
token accounting (see §7):

| Family | Reported reasoning tokens | Latency residual | K response | R response |
|---|---|---|---|---|
| token-serial | scale ~ K·R | small, token-tracking | rising | rising |
| recurrent-depth | ~flat in R | grows with R at constant tokens | rising or flat | strongly rising |
| parallel-latent-width | ~flat in K below knee | K-flat below knee, R-sensitive | flat then knee | rising |
| routed-or-ensemble | discontinuous | variance-structured, route-correlated | irregular | irregular |

A flat K curve alone proves nothing: a conventional transformer already
processes positions in parallel. Only the joint pattern across families,
task generators, and controls carries weight, and no individual latency
curve may carry an architectural claim.

## 4. Task design

Fixed-envelope state-propagation lattice: every prompt carries 32 equal-size
lanes (transition tables, start states, active-lane mask, zero-padded
recurrence count); only K lanes contribute; inactive lanes carry matched
decoy material; each active lane requires R dependent transformations; the
response is one fixed-length hexadecimal checksum. Three generator families,
fresh tables and nonces per request: (a) independent pointer-chasing lanes,
(b) coupled-ring propagation (every round depends on neighbor lane state),
(c) branch-reconcile with a final witness selection.

Admission gates per matched cell: identical provider-reported input-token
counts (byte equality is insufficient under tokenization variance), fixed
output length, identical sampling parameters, no retries, concurrency one,
route-identity stability within a block. Cells failing any gate are
invalidated before analysis and reported as invalidated.

Observable vector: request start, first response header, first SSE event,
first visible token, final token, inter-event timing, total latency, exact
correctness, input/cached/output/reasoning token counts, stopping state,
response-side model string, backend fingerprint when present, selected
processing and rate-limit headers, hashed request identifiers — captured and
authenticated under the observatory's existing receipt discipline.

## 5. Campaigns

Launch sentinel: K ∈ {1, 8, 32} × R ∈ {1, 4, 16} × two nonzero effort rungs
× 4 blocked randomized replicates = 72 subject calls, plus 8 reserved for
cache twins, no-op controls, identity checks, and transport baselines, under
the existing 80-request ceiling. Baselines (GPT-5.6 Sol, local controls,
cheap floor) run under separate manifests and never consume subject budget.
The sentinel's verdict authority is PROVISIONAL ONLY: it publishes the
heatmap, invalidated-cell ledger, and a provisional terminal. Architectural
conclusions require the confirmatory campaign — additional seeds, task
families, and time blocks — and reproduction in at least two task families.

Four frozen analyses: (1) the K×R lattice (width and depth elasticity);
(2) the effort staircase (accuracy and TTFT versus E, including discrete
plateaus); (3) the token-compute residual (latency unexplained by observed
input, cached, output, and reasoning tokens); (4) the continuation-reuse
probe, whose PRIMARY endpoint is accuracy — a continuation that answers
better than a byte-identical reconstructed transcript at matched
cached-token counts indicates state carried beyond text; latency is
secondary because KV reuse is universal.

## 6. Terminal states

Exactly one terminal per campaign, from:

```text
TOKEN_SERIAL_CONSISTENT
RECURRENT_DEPTH_CONSISTENT
PARALLEL_WIDTH_CONSISTENT
ROUTED_OR_ENSEMBLE_CONSISTENT
HIDDEN_SERIAL_OR_RECURRENT_INDISTINGUISHABLE
INCONCLUSIVE
```

PARALLEL_WIDTH_CONSISTENT additionally requires an R-sensitive residual
surface, K-flat behavior below an estimated capacity knee, stable route
identity, preserved accuracy below the knee, and reproduction across two
task families plus the confirmatory campaign.

## 7. The reporting-truthfulness condition

RECURRENT_DEPTH_CONSISTENT requires residual compute growing with R at
approximately constant reported reasoning tokens. If reasoning-token
accounting for the subject is absent, quantized, summarized, or internally
inconsistent across matched cells, recurrent-depth and hidden token-serial
implementations become observationally equivalent, and the strongest
admissible terminal for any R-sensitive result is
HIDDEN_SERIAL_OR_RECURRENT_INDISTINGUISHABLE. This condition is frozen now
because it is the failure mode most likely to occur.

## 8. Two-stage freeze

Stage 1 (this commit): hypotheses, design, gates, analyses, terminals, and
the rules in DECISION_RULES.json marked `stage: 1`.

Stage 2 (required before any subject call): numeric classification
thresholds derived from the local calibration atlas — LOTUS (3B, looped
K-blocks × R-iterations), LoopCoder-v2 (7B family, parallel-loop, whose
published non-monotonic loop curve supplies the saturation control), and a
conventional transformer negative control — expressed only as normalized
shape invariants (signs, normalized slopes, knee locations, monotonicity
classes), never absolute timings, because local serving does not transfer
to provider fleets. Stage 2 also freezes the generator implementations the
verifier rebuilds requests from. Stage-2 amendments may add numeric values
to rules stamped `stage_2_numeric: pending`; they may not alter hypotheses,
terminals, gates, endpoints, or this section. Any other change after stage 1
is a new preregistration under a new id.

## 9. Conflicted-party disclosure

This preregistration was drafted in a Claude Fable 5 session. Fable 5 is a
resident frontier lineage in this repository, the observatory's first
measured subject (`fable-5-baseline-v1`), and a commercial rival of the
campaign subject. Per the repository constitution, such a session is a
conflicted party in every judgment about models, especially about itself
and its rivals. Accordingly: no session narrative from this lineage carries
evidentiary standing; qualification and closure remain machine-derived at
exact source heads; graders, pass criteria, and ledger closure remain gated;
and the campaign's conclusions are whatever the authenticated receipts
support, including nothing.

## 10. Publication rule

Null and inconclusive results publish under the same protocol, format, and
venue as positive results. The Astra system card, when released, is admitted
afterward as a separate external evidence object; it may corroborate or
contradict the behavioral record but may not alter frozen hypotheses,
thresholds, or terminals.
