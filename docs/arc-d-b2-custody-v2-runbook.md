# ARC-D B2 custody-v2 activation runbook

This runbook instantiates the admission-v2 law without opening grader scope.
The merged component build remains `PENDING_DESIGNATION_AND_PRIVATE_PREFLIGHT`
until every activation input below exists and a later maintainer merge carries
the exact activation receipt.

## Hard boundary

- Do not dispatch a grader from this component-build branch.
- Do not place raw grades, payloads, session identities, private paths, tokens,
  or credentials in the public repository.
- Do not reuse or wrap any Grade A v1 or Grade B attempt 1–3 artifact.
- Public validation may report `PUBLIC_COMMITMENT_SHAPE_VALID`; it may never
  report semantic admission.

## Required designation

The operator must name all three identities before preflight:

- custodian: controls retention, recovery, access logs, and export;
- coordinator: administers packets and the public ledger without grading;
- verifier: a distinct mechanical identity with raw read access, not the
  rubric author, either grading instrument, custodian, or coordinator.

For GitHub Actions OIDC, record the exact repository and main-branch workflow
certificate identity. The verifier workflow must use GitHub-hosted runners and
the authentication check pins its source commit and rejects self-hosted
runners. A signed-commit verifier instead records the exact OpenPGP
fingerprint.

## Activation sequence

1. Create separate sanctioned private venues for `grade_a` and `grade_b` with
   separate write boundaries and immutable Git objects.
2. Give the designated verifier raw read access to both venues. Grading
   instruments receive no peer-lane access.
3. Write, read back, and seal one non-grader sentinel in each venue. Publish
   only a conforming
   `schemas/arc_d_b2_custody_preflight_receipt.schema.json` receipt.
4. Fill a custody profile conforming to
   `schemas/arc_d_b2_custody_profile.schema.json`. Its preflight hash must bind
   the exact receipt; its validator/authenticator hashes must come from the
   implementation commit.
5. Fill a separate activation receipt conforming to
   `schemas/arc_d_b2_custody_activation_receipt.schema.json`. Bind every exact
   schema and tool blob listed by the receipt.
6. Validate the candidate from its implementation commit:

   ```text
   python scripts/validate_arc_d_b2_custody_v2.py profile PROFILE.json --preflight PREFLIGHT.json
   python scripts/validate_arc_d_b2_custody_v2.py activation ACTIVATION.json --component-ref IMPLEMENTATION_COMMIT
   ```

7. Merge the profile, preflight, activation receipt, schemas, validator, and
   authenticator atomically to `main`. On the exact `origin/main` checkout,
   rerun activation with `--component-ref HEAD --official`. Only the exact
   success state `ACTIVE_FOR_FRESH_V2_GRADING` opens fresh-v2 packet export.

## Fresh attempt sequence

After activation only:

1. Export all three unchanged v1 packets from one default-branch source
   commit. Preregister their exact hashes before any dispatch.
2. Maintain the content-free six-cell dispatch ledger as a hash-linked,
   append-only revision chain. Revision zero is the all-`NOT_DISPATCHED`
   grid; each later revision binds the previous ledger bytes and commit,
   changes at least one cell, and never rewrites a terminal cell. Validate
   each successor with `dispatch --previous-ledger PREVIOUS.json`. Every cell
   receives exactly one outcome; a sealed attempt may not retain
   `NOT_DISPATCHED`.
3. Seal each complete private bundle in its lane Git venue. Validate the exact
   commit/tree/blob objects, not a checkout or copied directory:

   ```text
   python scripts/validate_arc_d_b2_custody_v2.py private-bundle \
     --repository PRIVATE_REPO --commit COMMIT \
     --manifest-path BUNDLE/MANIFEST.json --public-receipt RECEIPT.json
   ```

4. Authenticate each audit using
   `scripts/verify_arc_d_b2_audit_auth.py`; then run the `audit` mode so the
   designation, exact private object, validator, authentication evidence, and
   public commitment are cross-bound.
5. Propose public receipts only after all six private seals. Validate the
   exact keyed 3×2 batch. The result remains public commitment shape until one
   later atomic default-branch admission merge.

Any missing, malformed, unavailable, mutable, contaminated, pre-activation,
selectively reported, or unauthenticated input returns to `PARTIAL_UNPAIRED`.
