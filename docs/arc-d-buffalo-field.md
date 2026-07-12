# ARC-D buffalo field — exploratory contract

Status: **pilot subjects remain unadjudicated; B2/B4 charter activates only on
maintainer merge**

Authority: `docs/agents/QUEUE.md` authorizes the bounded `ARC-D-PILOT` spend. It
does not adopt a grader or pass criterion. Under `AGENTS.md` and
`experiments/breadth/adapt.py`, the rubric and every `HARVEST` gate below are
GATED. A model may propose them, but only an explicit operator adoption bound to
the exact protocol bytes may activate them. The separately versioned
`arc_d_buffalo_pilot_v2/harvest_charter.json` becomes that adoption only when
its exact bytes are merged to the default branch; before merge it remains a
ratification candidate.

## Question and unit

A **buffalo** is a pinned, public OSS work item used to search for a small piece
of reasoning that might become reusable machinery. The target unit is one
unique, falsifiable residue artifact that later causes a prospective
out-of-sample improvement. A diagnosis, patch suggestion, agreement with an
upstream proposal, or source-case test pass is not yet a harvest.

The pilot uses three convenience/adversarial work items. Selection happened
after the coordinator inspected public upstream proposals, so this is not a
blind or representative sample. Record `sampling_preregistered: false` and the
coordinator's reference exposure for every item. Two items may come from the
same project and are correlated; the denominator is still all three items, with
no post-response exclusions.

`p <= 0.10` is a deliberately pessimistic **simulation scenario**, not a
measured rate, calibrated prior, or conclusion from three observations. The
pilot tests packet, custody, and failure-preservation mechanics only. Any later
statistical protocol must separately freeze the sampling frame, prior or
scenario distribution, update rule, dependence assumptions, stopping rule, and
interval before candidate selection.

## Separation and custody

The coordinator is a driver and may inspect public references. Each subject is
a fresh, projectless packet-only session and receives only an allowlisted
`PROMPT.md`, issue snapshot, and source excerpts pinned to one base commit. It
receives no repository checkout, queue, peer answer, upstream PR identifier or
diff, hidden test, reference receipt, or coordinator conclusion. Network and
tools are disabled; any tool call or prior-context exposure makes the row
`CONTAMINATED`.

Before dispatch, freeze and hash:

- repository identity, base commit, issue snapshot, allowed files, and packet;
- complete prompt bytes and packet-builder version;
- model, effort, execution surface, fresh-context rule, and exposure flags;
- the excluded reference set and a deterministic packet leakage scan.

After dispatch, preserve the complete response bytes, thread/session/turn/event
identity, provider timestamps and usage when available, tool/command events,
and a hash-bound administration receipt. Missing or broken custody yields
`PARTIAL`, never a negative or positive scientific result.

## Evidence ladder

Progress is append-only. A later rung adds a new receipt; it never rewrites the
meaning of an earlier one.

| Rung | Entry and required evidence | Permitted state |
|---|---|---|
| **B0 — field freeze** | Freeze protocol bytes, selection/exposure record, item identity, issue snapshot, base commit, packet hashes, no-claim boundary, and gate state. Preseal any future transfer targets before a residue is authored. | `FIELD_FROZEN` or `PARTIAL` |
| **B1 — cold sighting** | Run one isolated packet-only subject and seal its raw response and administration receipt before reference comparison. | `SEALED_RESPONSE`, `CONTAMINATED`, or `PARTIAL` |
| **B2 — source-case review** | Under an operator-adopted gate, test atomic claims against authoritative executable evidence and record alternate-solution handling. Without adoption, retain the response without scoring. | `UNADJUDICATED`; later, if authorized, `CANDIDATE_RESIDUE`, `REFERENCE_AMBIGUOUS`, or `REJECTED_CANDIDATE` |
| **B3 — artifactization** | Encode one unique falsifiable rule or scaffold, its applicability predicate, exclusions, provenance, and content hash. Deduplicate semantically equivalent residue. | `ARTIFACTIZED`; no transfer claim |
| **B4 — prospective within-family transfer** | Unseal a previously frozen distinct target and run the matched A/B protocol below with a hidden executable grader. | `TRANSFER_VALIDATED`, `NO_INCREMENTAL_EFFECT`, `NO_TRANSFER`, or `TRANSFER_AMBIGUOUS` |
| **B5 — cross-project replication** | Repeat B4 on a predeclared target from a different repository and preserve negative transfer. | `TRANSFER_REPLICATED` or an explicit non-closed state |
| **B6 — economic closure** | Count multiple measured retirements, complete cost and maintenance accounting, and satisfy the capture-ledger burden. | only the capture authority may declare compounding or amortization |

The present three dispatches reached the B1 transport boundary but returned
provider `systemError` with no assistant bytes. Each is `PARTIAL`, not a
`SEALED_RESPONSE`; there are zero scientific observations to compare or
adjudicate. They cannot mint B2 or later states.

## Source-case gate — proposed here; adopted only by the v2 charter merge

If the operator later adopts this exact gate, B2 requires all of the following:

1. the subject response was sealed before grading or reference exposure;
2. the diagnosis names behavior supported by authoritative executable evidence;
3. a proposed regression test states the expected behavior without inventing an
   API or contract;
4. the residue is falsifiable, bounded by an applicability predicate, and
   distinct from previously counted artifacts; and
5. every decision cites exact subject byte spans and exact test, source, or
   authority hashes.

An open or unmerged PR is **proposal state**, not ground truth. It may locate a
possible fix or test, but cannot close correctness by itself. Competing,
incomplete, failing, or contract-disputed references default to
`REFERENCE_AMBIGUOUS`. An alternative implementation is admissible when the
authoritative behavior and executable tests support it.

No same-lineage model grader is called independent merely because it uses a new
thread. It may provide a procedurally isolated review, but deterministic tests,
an authorized human, or a genuinely cross-lineage adjudicator must supply any
closing verdict. Unsupported or disagreeing adjudication defaults to ambiguity;
the driver cannot override it.

## Prospective A/B gate — proposed here; adopted only by the v2 charter merge

`HARVEST` may be emitted only after explicit operator adoption and B4 evidence:

- the distinct transfer target was selected and sealed before artifact
  creation or exposure;
- arm A receives the target packet without the artifact and arm B receives the
  identical packet plus only the frozen artifact;
- both arms use three fresh sessions (`K=3`) with the same model, effort,
  surface, instructions, and deterministic hidden grader;
- the coordinator independently reruns the grader and binds candidate and
  grader hashes; and
- arm A is `0/3` while arm B is `3/3`.

That crossing permits one `TRANSFER_VALIDATED`/`HARVEST` event for the unique
artifact. If A clears, the result is `NO_INCREMENTAL_EFFECT`; if B is `0/3`, it
is `NO_TRANSFER`; every mixed window is `TRANSFER_AMBIGUOUS` and requires more
same-rung evidence rather than a favorable interpretation. B5 is required
before any cross-project generality claim. B6 is required before any compounding
or amortization claim.

## Simulation boundary

Monte Carlo output is illustrative sensitivity analysis only. Freeze the code
hash, seed, scenario grid, hunt count, baseline event probability, transfer
validation probability, applicability, task correlation, deduplication, and
cap. The bounded v1 projection includes positive-lift and null scenarios only;
it does **not** model decay, maintenance, or harmful/negative transfer. Those
channels must be added and frozen before any calibrated field or economic claim.
Only B4-validated unique artifacts may affect later simulated hunts, and only
inside their frozen applicability family. Report provider usage by its actual
evidence class; subscription-derived usage is not billed USD.

## Failure preservation and no-claim boundary

Every miss, contaminated run, partial receipt, ambiguous reference, rejected
candidate, failed transfer, and negative transfer remains in the original
denominator and append-only evidence tree. Do not alter the rubric, target,
reference, applicability rule, or stopping rule after seeing a response.

This pilot does **not** establish a model capability, an upstream fix, an OSS
acceptance decision, a harvest rate, a calibrated prior, cross-lineage
agreement, reusable generality, compounding, capture amortization, or a
waterline move. Until an adopted gate and its required evidence exist, the
failure default is `UNADJUDICATED` and all closure remains open.

### Separately versioned retry

After v1 was merged as an immutable three-error partial, the operator authorized
continuation. `arc_d_buffalo_pilot_v2` first ran an excluded exact-response
capacity preflight, then dispatched at most one fresh projectless thread for each
v1 prompt in the preregistered order. All three completed without tools. Their
responses, normalized event receipts, thread snapshots, timestamps, and hashes
are preserved under `data/oss-replay/arc_d_buffalo_pilot_v2/`.

The retry changes only administration capacity and attempt identity. It does not
change the source cases, prompt bytes, gate, grading authority, or claim boundary.
The three v2 rows therefore stop at `SEALED_RESPONSE_UNADJUDICATED`; they are not
HARVEST observations and do not update the illustrative prior or projections.

## Burden packet

```text
requested_outcome: Preserve a bounded low-yield OSS replay pilot and define the
  evidence required before reusable-residue or compounding claims.
claimant: ARC-D-PILOT coordinator.
authority: QUEUE authorization for exploratory execution; an exact operator
  adoption plus executable evidence for any future gate.
predicates: lane separation, byte-bound custody, frozen rules and targets,
  append-only failures, authorized adjudication, and prospective matched A/B.
burden_holder: whoever asserts HARVEST, transfer, generality, or economics.
evidence: protocol, packets, raw events, administration receipts, artifacts,
  hidden grades, A/B receipts, cost records, and their hashes.
verifier: deterministic validators and graders plus the named authorized
  adjudicator; never the subject narration or driver alone.
gap: the gate is not adopted; the convenience sample is nonrepresentative; the
  present pilot stops with unadjudicated B1 responses.
closure_decision: protocol proposed and exploratory subjects permitted; all
  harvest and compounding closure held open.
failure_default: UNADJUDICATED / remain open; preserve the failure.
```
