# Blind-control packet v2 handoff

## Supersession

The operator authorized packet v2 on 2026-07-10 because the prepared v1 bytes
were unavailable and its declared SHA-256 could not be reproduced from any
committed source state. This supersedes v1; it does not claim that the v1 digest
was false or that different bytes matched it.

- superseded v1 SHA-256:
  `64e33f2a237adc0b034c79aaaa0341a5b5e4a33c233ddbe2fdd917e7470a5fea`
- v2 source corpus/rubric commit:
  `623cb1ed1672e04fecba48f04294067f78eaf02e`
- v2 exporter implementation commit: `ffafefd`
- v2 packet SHA-256:
  `98997bf9d9e43d85052e6ff0107476735cf35aeccfd7c4509dc4762ff48d7b11`
- private delivery repository: `BigBirdReturns/tier-bench-blind-grade-001`
- packet-only repository commit:
  `6771868bbdff156382796190271404fd72576936`
- packet item count: 80 declared, 80 actual

GitHub reported the delivery repository private and its complete commit tree as
the single file `control_packet.json`. No key or coordinator artifact was
placed in that repository.

## Identity and ordering boundary

V2 derives each 24-hex opaque ID from HMAC-SHA-256 over the source binding with
a freshly generated 256-bit private ID salt. It independently randomizes packet
order with a freshly generated 256-bit private permutation seed. The packet
contains SHA-256 commitments to both secrets, but neither raw secret.

The private key retains the full salt, permutation seed, source mapping and
packet digest in coordinator-only storage outside every Git checkout. The
exporter can regenerate the packet byte-for-byte from that key. The generated
packet and its regeneration both produced SHA-256
`98997bf9d9e43d85052e6ff0107476735cf35aeccfd7c4509dc4762ff48d7b11`.

The private salt prevents opaque IDs from being recomputed from the public
corpus. It does not make verbatim responses non-fingerprintable. Therefore the
instrument session must still receive only the packet repository: no tier-bench
checkout, private key, queue, peer grades or coordinator narration.

## Verification record

Generation passed all of these checks before publication:

1. packet schema is `tier-bench.control_blind_packet.v2`;
2. source commit is pinned to `623cb1e`;
3. declared and actual item counts are both 80;
4. all packet IDs are unique and exactly match the private key ID set;
5. the packet SHA-256 matches the private key;
6. both public secret commitments recompute from the private key;
7. raw ID salt and permutation seed are absent from the packet;
8. forbidden model, administration, grade and source metadata are absent;
9. regeneration from the private key is byte-identical; and
10. the publish repository commit contains exactly `control_packet.json`.

`scripts/merge_external_grades.py` publishes only the packet schema and public
commitments in its merge manifest. It does not copy the salt or permutation
seed into evidence artifacts.
