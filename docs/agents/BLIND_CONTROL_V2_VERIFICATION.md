# Blind-control packet v2 — independent verification (Claude lineage)

*Verifier: Claude session (driver lane), 2026-07-10. Verified directly against a
fresh clone of the private delivery repository; nothing below is taken from the
generator's narration.*

## Verified (checked, not reported)

| Claim (BLIND_CONTROL_V2.md) | Result |
|---|---|
| Delivery repo commit is `6771868bbdff156382796190271404fd72576936` | **confirmed** (clone HEAD) |
| Remote tree is exactly `control_packet.json` | **confirmed** (`git ls-tree -r HEAD`: one blob) |
| Packet schema `tier-bench.control_blind_packet.v2` | **confirmed** |
| Source commit pinned to `623cb1ed…` | **confirmed** (in `_meta`) |
| 80 declared / 80 actual items | **confirmed** |
| All opaque IDs unique, 24-hex | **confirmed** |
| No forbidden metadata keys in any item | **confirmed** (model/effort/score/grader/etc. absent) |
| Commitments present, raw secrets absent | **confirmed** (`id_salt_commitment`, `permutation_commitment`; no raw salt/seed) |

## Adjudicated: the declared packet SHA is the wrong serialization

The handoff record declares packet SHA-256
`98997bf9d9e43d85052e6ff0107476735cf35aeccfd7c4509dc4762ff48d7b11`.
The bytes actually committed at `6771868` hash to:

```
e1a1dc6bfcee26a435e23107d08019870153ceb1cf6e646b46317663ad8afd06
```

Cause, demonstrated: `98997bf9…` is the SHA-256 of the **CRLF** rendering of the
identical content; git stored the **LF** form. (`sha256(LF_bytes) = e1a1dc6…`;
re-expanding every `\n` to `\r\n` reproduces `98997bf9…` exactly.) Under the
transport/adjudication knot taxonomy this is a **transport artifact, not a
capability or integrity failure** — same content, different line endings.

**Canonical digest for all downstream evidence (SOL-1 merge manifest, QUEUE,
agreement reports): `e1a1dc6bfcee26a435e23107d08019870153ceb1cf6e646b46317663ad8afd06`**
— the digest of the bytes a grading session actually receives from git.

## Still single-source (cannot be third-party verified, by design)

- The private key's contents; that regeneration from it is byte-identical.
- That the commitments recompute from the real salt/seed (verifiable only at
  key disclosure — the commitments make that check possible later).

## Repository privacy

Reported private by the coordinator and by GitHub at add time; not
independently re-verifiable from inside a session that has been granted access.
