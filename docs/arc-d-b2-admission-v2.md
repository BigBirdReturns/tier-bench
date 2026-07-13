# ARC-D B2 private-custody admission v2

Status: **ratification candidate; effective only by default-branch merge**

This amendment specifies a prospective resolution to the evidence-venue problem without rewriting the B2
rubric after results became known. It pins the full v1 charter Git blob plus
separate canonical digests for the decision-critical sections. The
sealed ARC-D subject responses do not rerun. Both grading lanes must rerun:
three new Grade A sessions and three new Grade B sessions, all after this
amendment and a custody profile are active.

The amendment is deliberately narrow. It does not relax the bare-JSON rule,
change source authority, alter disagreement handling, or grandfather the valid
parts of earlier attempts. The Grade A local attempts and Grade B attempts 1–3
remain immutable `PARTIAL_UNPAIRED` history.

## What private custody can and cannot prove

Private raw artifacts plus public hashes give the public tamper-evident
commitments and let a designated independent verifier reproduce the audit.
They do **not** let an arbitrary public clone inspect withheld bytes or verify
their meaning. Claims under this design must therefore say **publicly
commitment-verifiable and independently audited**, not publicly reproducible.
Loss of verifier access suspends new comparison and promotion.

## Activation

Merge of this proposal adopts the rule but leaves it
`ADOPTED_PENDING_CUSTODY`. It is a specification merge, not operational
admission plumbing. Grading remains closed until later merged work supplies a
custody profile, a separate activation receipt, public attempt
preregistration/dispatch ledger, full private-Git object validation, and an
authenticated signed-commit or OIDC audit mechanism. A content-blind preflight
must prove both venues work without placing grader content in the public
repository. The verifier may not be the v1 rubric-author task, either grading
instrument, or the coordinator.

No governance document can override a platform safety or publication denial.
If sanctioned private custody cannot be established, the lawful state remains
`PARTIAL_UNPAIRED`.

The canonical Git blob of this amendment becomes immutable authority at
adoption. The companion custody and receipt schemas in this proposal are draft
interfaces, not operational authority. The later activation receipt must bind
the exact final schema/tool/authenticator Git blobs. Any byte change to this
amendment requires a new amendment version and maintainer merge.

## Attempt and admission sequence

Each v2 attempt has exactly one dispatch for each of the three items in each
lane. Every outcome—success, refusal, malformed output, or provider failure—is
sealed. No per-item retry, repair, wrapper stripping, or favorable sampling is
permitted inside the attempt.

1. Reuse the ratified v1 grader-visible packet format and instructions. After
   activation, export from one default-branch source commit, preregister one
   exact packet hash per item, and use the same item hash in both lanes.
   Outside grader scope, bind those hashes to this amendment and the custody
   profile. The governance amendment is not added to the packet because
   governance remains on the v1 denylist.
2. Dispatch six fresh projectless packet-only sessions under the unchanged
   instruments and strict output rule.
3. Before peer or comparator disclosure, seal each complete private bundle in
   its lane venue and record its immutable commit/object identity.
4. A distinct mechanical verifier reads the raw bundles, recomputes hashes,
   validates the payload and full receipt, checks spans and evidence authority,
   and attests exact model/surface/session chronology and lane separation.
5. Only after all six private bundles seal may content-free public admission
   receipts be proposed. One batch receipt proves 3×2 completeness and that
   public disclosure followed the final private seal.
6. One default-branch merge admits the six receipts atomically. Comparison then
   runs over the audited private semantic receipts. A later merge, not the
   admission merge, makes any comparison result binding.

Any defect makes the whole attempt `PARTIAL_UNPAIRED`. A new full attempt needs
separate authorization and preserves the failed attempt.

## Public receipt boundary

The public side may carry protocol, attempt, item and lane identifiers; parent
and amendment hashes; packet/prompt/subject-response commitments; immutable
private object identity; artifact hashes and sizes; committed session-identity
hash; exact instrument labels; chronology; validator provenance; and audit
result. Before the six-bundle seal it carries no grader prose, payload,
disposition, plain session identity, private path, credential, or token.

The public validator can prove structural completeness and commitment
consistency. It must label that result `PUBLIC_COMMITMENT_SHAPE_VALID`, never
`ADMITTED`. It cannot assert that unavailable private bytes are semantically
correct. Admission therefore additionally requires the designated verifier's
authenticated audit receipt and a private-to-public derivation check over exact
private Git commit/tree/blob objects.

## After B2

Even a binding `B2_CANDIDATE_RESIDUE` is not HARVEST. The unchanged v1 ladder
still requires a unique frozen B3 artifact and then a separately authorized B4
matched A/B whose target was sealed before artifact exposure. Only A=0/3 and
B=3/3 under the frozen hidden grader mints exactly one HARVEST event.

```text
requested_outcome: Admit fresh ARC-D B2 grades without publishing raw grading
  artifacts and without changing the result-aware substantive rubric.
claimant: ARC-D-B2-ADMISSION-V2 driver.
authority: operator fan-out plus maintainer merge of the exact amendment,
  schemas, validator, tests, and later custody profile.
predicates: parent substantive hashes unchanged; prospective activation; six
  fresh sessions; separate immutable lane custody; all attempts preserved;
  independent raw-read audit; atomic public admission; comparison stays shut
  until admission merges.
burden_holder: whoever claims an admitted grade, binding B2 disposition, or
  downstream HARVEST event.
evidence: parent/amendment hashes, custody preflight, private bundle manifests,
  immutable locators, public receipts, audit receipts, batch seal, validator
  provenance, and later comparison receipts.
verifier: deterministic private validator plus the named independent verifier;
  the public validator checks commitments only.
gap: no custody profile, activation receipt, attempt preregistration/ledger,
  authenticated audit verifier, private-to-public derivation tool, fresh v2
  grade, or admitted batch exists at amendment-ratification time.
closure_decision: merge adopts custody/admission law but does not dispatch or
  admit grading evidence.
failure_default: PARTIAL_UNPAIRED; zero binding B2, B3, B4, or HARVEST claim.
```
