# CART0-PROFILE-1 independent-review remediation — 2026-07-14

Status: deterministic driver-lane remediation complete locally; independent
delta retest pending. The sealed Claude report SHA-256 is
`9a75696089c7e7ef0e8fa11a75fb09e0ed905556cfe5c2223f63764654b844bb`.
The report and the failed v1 archive remain unchanged.

## Changes

- `rehydrate()` now reads the exact verified source blob OID, rechecks the full
  file hash, re-slices the bound line range, and rechecks span hash/length
  immediately before emission. It never re-reads mutable HEAD for source bytes.
- `safe_path()` rejects every C0/DEL control and any `.git` component at any
  depth before subprocess. The Git wrapper converts OS/argument failures to
  `AnchorError`. CLI NUL input cleanly emits `CART0_ANCHOR_REFUSED`.
- Quarantine v2 uses a projection/card-bound nonce delimiter; one generated
  begin/end pair is asserted while the semantic/instruction-safety limitation
  remains explicit.
- Claude witness hashes are frozen in
  `claude_independent_witness_manifest.json`; TOCTOU, unsafe paths, and
  delimiter hardening are additive conformance vectors. Positive guards remain.
- The v2 portable artifact contains complete Git history, an exact tested tree,
  SHA256SUMS, and a one-command verifier. It was run successfully from a new
  directory outside the source repository with no network or borrowed Git state.

## Commits

- `89df8c6` — record independent-review remediation in the queue;
- `3292102` — fix immutable-blob rehydration/path refusal and add regressions;
- `a30ca1a` — seal fresh 15-vector and B0 receipt trees;
- `0557aee`, `5fed4ab`, `d05ab5f`, `ad48ab8` — add and fresh-extraction-harden
  the offline Git-custodied verifier.

## Exact results

`py_compile`: PASS. `test_cart0_anchor.py`: PASS. Historical attack receipt:
PASS and still reports the preserved 4/10-safe, 6/10-gap result. Fresh repaired
conformance: **15/15**, 10 negative and 5 positive, reject-all guard PASS, zero
model calls. The TOCTOU vector emits `PROCEED_VERIFIED_BLOB`; six NUL/C0/DEL
and nested-`.git` paths all cleanly refuse; nonce-delimiter hardening passes.

Fresh B0: A = 51,754 bytes / 12,939 bytes/4 proxy tokens; B = 2,824 bytes /
706 proxy tokens; demonstrated saving = 48,930 bytes / 12,233 proxy tokens;
reduction = **94.5434%**; anchor = 971 bytes / 243 proxy tokens; wall time =
5,077.44 ms; model calls = 0.

Receipt SHA-256 values:

- conformance: `b0852cd14222bd671d965179149a4fa549355760984af23437642b43238a3278`;
- B0 A/B: `aae308336ef918a73c7bb655d57e25c8bf1a06ca2c7eb1868351bd9a63e80ed1`;
- B0 bundle: `47c5b8440929de1d1d63257abb5f2c3c2382f92bdd717b20c59177498ce15642`;
- portable raw verification output:
  `01d55b0edc80f112aab05801c8c1697cc8f6fc409f5aac0c5238674be6e9b405`.

Portable archive:
`experiments/cart0_anchor_prototype/cart0-profile-1-independent-verification-v2-a30ca1a.zip`

SHA-256:
`fb912f39d08681ff60108e0cf5ca7199f339de25bc36bfe1d1c5300602f66bdc`

The fresh-extraction verifier ended `PORTABLE_CART0_PROFILE_1_VERIFIED` after
exact-tree comparison, both deterministic tests, fresh conformance, remediated
B0 verification, and preserved historical B0 verification.

## Bounds

No semantic truth, instruction-safety proof, production Genesis custody,
provider billing saving, downstream quality, or context-window solution is
claimed. The measured saving is prompt payload only. B1 remains unauthorized;
a separate committed provider/model experiment row is still required.
