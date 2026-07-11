# SOL-4 adversarial review — PR #67 CART0 A/B/C ceiling run

Date: 2026-07-10

Reviewer: Codex/OpenAI lineage, repo-aware driver lane

Scope: PR #67 at `141ff2814708198180e7fc1da35f0e9eb85bc520`

Disposition: changes requested to evidence custody and causal framing; review
artifact only, with no grader, result, waterline, or pass-rule mutation.

## Executive result

The numerical result is reproducible: all 15 candidates independently regrade
to 10/10 twice, all 45 declared candidate/raw/grader-output hashes match the Git
blobs, and the hidden vectors are byte-identical to replay04. The run therefore
supports the narrow observation **A = B = C at ceiling under this two-turn
administration**.

It does not yet support a sealed causal conclusion about plan-time rehearsal.
The artifacts omit the turn-1 plans and per-trial session identities on which
that interpretation and the quarantine claim depend. The seal files also lose
integrity in a default Windows clone because their evidence directory has no
`-text` policy. Those are custody defects, not score disputes.

## Findings

### P1 — the deciding turn-1 evidence and administration identities are absent

`RESULTS.md` says 14 of 15 solvers restated the rule commitment in their own
turn-1 plans, that all 30 turns used zero tools, and that fresh sessions could
not contaminate each other. None of the trial directories preserves a turn-1
response, thread/session ID, turn-level event record, or tool-use receipt.
`raw_response.txt` contains only the final code response; repository search
finds `PLAN COMPLETE` only in `turn1_prompt.txt`.

Consequences:

- the 14/15 rehearsal count cannot be recomputed;
- fresh-session independence cannot be checked;
- condition assignment and the exact turn-2 continuation cannot be bound to a
  session;
- `tool_uses: 0` is a narrative assertion rather than preserved evidence.

Required repair before causal sealing: preserve the exact turn-1 response,
turn-2 response, stable session/thread identity, condition assignment, and raw
turn/event metadata per trial. Hash-bind those objects in the trial seal.
Existing missing plans must not be reconstructed from final code comments.

### P1 — all 45 seals are checkout-dependent

Every seal matches the committed Git blob, but PR #67 does not mark
`experiments/breadth/run/abc_causal_task02_20260711/**` as binary/exact-byte
evidence. In a Windows `core.autocrlf=true` checkout, all 45 candidate,
raw-response, and grader-output hashes differ from their seals. `git check-attr`
reports `text: unspecified` for these paths.

Required repair: add an evidence-scoped `-text -whitespace` rule for this run
directory and a fresh-clone regression that recomputes every seal. Do not change
repository-wide normalization.

### P2 — seal chronology and the second grade are self-attested

Each `seal.json` contains candidate/raw/output hashes plus `deterministic: true`,
but no timestamps or append-only event order, prompt/condition hashes, grader
hash, vector hash, administration ID, or two separately preserved grader
outputs. The current bytes prove what was committed, not the claimed order
"candidate sealed before any grading" or that two grade executions occurred.

Required repair: record an append-only event stream or structured receipt with
candidate-sealed and grade-run events, bind the prompt, both turn payloads,
grader, vectors, candidate, both raw grader outputs, and session identity, and
validate chronology mechanically.

### P2 — the PR title/body overstate the rehearsal interpretation

The experiment directly measures a ceiling and no A/B/C separation. It has no
same-administration single-turn control. The 1/3 comparator is a historical run
from another session and prompt shape, whose exact administration was not
replayed here. `RESULTS.md` correctly labels the plan-first account a hypothesis
and names this confound, but the PR title/body say rehearsal “defuses” the
boundary and that the mechanism is “confirmed.”

Required repair: frame the conclusion as **ceiling/no separation; plan-time
rehearsal is one plausible explanation**. Keep the protocol-shape contrast
descriptive until a contemporaneous control isolates the plan turn. The next
iteration remains a gated proposal.

## Grader-fidelity checks that passed

- 15/15 candidates independently regraded twice to `SCORE 10/10`; paired
  outputs were identical.
- 45/45 seal hashes match the Git blobs.
- `hidden_used/hidden_vectors.json` is byte-identical to the committed replay04
  vector file (`af19f6be…e97b`).
- The adapted grader applies the same ten vectors and reproduces replay04's
  expected 6/10 naive failure pattern and 10/10 passing behavior.
- Turn-2 message lengths match the stated control band: A/B/C are 60/56/55
  words respectively.

## Burden packet

- requested outcome: preserve PR #67 as proposal-layer ceiling evidence without
  promoting an unverified rehearsal mechanism
- claimant: SOL-4 Codex driver review
- authority: PR head Git blobs, independent regrading, hash recomputation, and
  artifact-presence search
- burden holder: PR #67 author before causal sealing
- verifier: fresh Windows clone hash check; per-trial transcript/session receipt
  validator; independent double regrade
- gap: missing turn-1/session/tool-use evidence, non-portable seals, no preserved
  chronology, and no contemporaneous single-turn control
- closure_decision: review complete; causal claim held open
- failure_default: retain only the 15/15 ceiling/no-separation observation

