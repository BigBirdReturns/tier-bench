# ARC-D B2 first grading attempt — public-safe partial summary

Disposition: **PARTIAL_UNPAIRED; NO B2 RESULT**

The ratified exporter produced three official one-response packets locally.
Three fresh projectless OpenAI Grade A tasks returned raw outputs. Those outputs,
their receipts, and packet metadata remain local-only: the execution safety
policy denied uploading workspace-derived grading artifacts to this public
repository even after the operator explicitly approved publication.

A local fail-closed validator classified two Grade A receipts as structurally
valid and rejected one because it treated non-authority issue material as
authoritative. This summary does not reproduce any disposition, rationale,
excerpt, raw grade, receipt, packet content, task identity, or content hash.
Because the evidence is not committed and independently verifiable here, none
of the three is an admitted Grade A observation.

The Anthropic Grade B lane did not execute. After a specific risk notice and
explicit operator approval, the execution safety gate still rejected disclosure
of the sealed private packets to Anthropic. The rejection occurred before any
provider command ran: provider dispatches 0, packet disclosures 0, raw grades 0.
No workaround, substitute grader, or post-disclosure rubric change was used.

The comparator requires two admitted, mutually blind grade receipts per item.
Both preconditions are absent: Grade A is local-only and Grade B does not exist.
Therefore comparison was not claimed or run. The failure default is binding:
zero comparison receipts, zero authoritative B2 dispositions, zero candidate
residues, and zero HARVEST claims. ARC-D remains at B1.

## Burden packet

```text
requested_outcome: preserve the public-safe state of the first B2 grading
  attempt without disclosing prohibited grading artifacts.
authority: ratified charter and operator-authorized grading attempt.
predicates: both grade lanes admitted, receipts committed and validated, and
  peer blindness preserved.
burden_holder: whoever asserts a B2 disposition or later HARVEST claim.
evidence: public repository contains only this non-content summary; required
  grade evidence is absent.
verifier: queue/roadmap state and repository tree.
gap: Grade A evidence cannot be admitted here; Grade B was never dispatched.
closure_decision: PARTIAL_UNPAIRED; comparator forbidden.
failure_default: no B2 result, candidate residue, or HARVEST claim.
```

## Second attempt update

A second OpenAI Grade A attempt ran three fresh projectless sessions against the
same ratified packets. Its three payloads and receipt sets validate locally, but
the underlying grading artifacts remain outside this public repository and are
therefore not admitted public evidence.

Grade B commit `f4d4962` was then imported and validated from its canonical Git
blobs before comparison. Its recorded raw and payload hashes match those blobs,
but the lane is not charter-admissible: the manifest records a non-projectless
repository-container surface and a model id different from the frozen one; it
does not supply the required per-item grade receipts, session identities,
timestamps, and validator results; and only one of three payloads passes the
authority rules. The other two mark explicitly non-authoritative packet
material as authoritative.

The comparator therefore remains forbidden. There are zero comparison receipts,
binding B2 dispositions, candidate residues, or HARVEST claims.

## Grade B attempt 2 and attempt 3 authority

Grade B attempt 2 (`5008f3b`) moved to physically projectless `fable-5@high`
sessions and added receipt machinery, but it still admits zero items. The attrs
receipt marks `ORIGINAL_PROMPT.md` as authoritative even though the packet makes
it non-authoritative. The httpx-3614 item reached a provider-refusal wall and
records administration defects. The httpx-3221 item has two non-bare samples
with conflicting dispositions and no admissible receipt. None may be repaired,
selected, or converted into a comparison input.

The operator said `go` on 2026-07-13, authorizing a new versioned Grade B
attempt 3 under the unchanged charter. Each item requires one fresh physically
projectless packet-only `fable-5@high` session, exact bare-JSON output, correct
packet authority classification, and a complete validated per-item receipt.
Every refusal, malformed output, and disagreement must remain preserved. Until
all three receipts validate, comparison and every downstream B2/HARVEST claim
remain forbidden.
