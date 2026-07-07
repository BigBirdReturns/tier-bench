# The living lens shard — the registry, sealed on AXM Genesis

The lens library is the compounding asset: every validated lens is a captured
frontier move a cheap model can run. This makes it **sovereign** — a signed,
verifiable, queryable AXM Genesis shard instead of only a Python list.

- Every lens is a **claim**, bound to the exact source bytes of its instruction
  (byte-range provenance).
- The whole registry is one **BLAKE3 Merkle tree**, signed **axm-hybrid1**
  (Ed25519 ‖ ML-DSA-44 / FIPS 204). Flip one byte and `axm-verify` fails.
- It is read **deterministically** — no model on the query path.

This is the AXM shape applied to capability: a validator (or the frontier, once)
at compile time; deterministic query at read time. It is the same move
`experiments/tier-uplift` makes for capability and the kernel paper makes for
knowledge — take the stochastic processor off the authority path.

## Verify it (the guarantee)

```bash
axm-verify shard memory/lenses/shard --trusted-key memory/lenses/shard/sig/publisher.pub
# {"status": "PASS", "error_count": 0}
```

Tamper one byte of any sealed table or the source and it fails closed:

```
E_MERKLE_MISMATCH: Merkle root mismatch: computed <a> stored <b>
```

## Read it (zero-dep, model off the path)

```python
from capability_harness.lens_shard import load_lenses
from capability_harness import review
lenses = load_lenses("memory/lenses/shard", verify=True)   # verify=True refuses a tampered shard
review(open("mycode.py").read(), call, lenses=lenses)
```

`load_lenses` reconstructs the registry from the sealed `content/source.txt` with
**stdlib only** — the harness never imports the AXM toolchain. Verification is a
separate, stronger step that does.

Once the shard is mounted in a local AXM store you can also query it in natural
language (`axm chat query "which lenses catch boundary errors"`) — the same
deterministic-SQL path the `memory/` decisions shard uses.

## Rebuild / make it living

The shard is **living**: it grows as the community adds validated lenses.

```bash
# 1. add a lens to capability_harness/lenses_contrib.py, proven by scripts/validate_lens.py
# 2. re-seal:
python memory/lenses/build_lens_shard.py --private-key <publisher.key> --out memory/lenses/shard --verify
```

On a re-seal the Merkle root and shard identity move and the lineage records the
supersession — a new signed version, not an in-place edit.

Anyone can mint a **sovereign shard of their own** (their own publisher key) in
one command — the AXM sovereignty model, no permission needed:

```bash
python memory/lenses/build_lens_shard.py --keygen memory/lenses/keys --out memory/lenses/shard --verify
```

## Keys & honesty

- Only the **public** key ships (inside `shard/sig/publisher.pub`); the secret
  `publisher.key` is git-ignored and belongs offline / in CI. Verification needs
  only the public key.
- A sealed claim is a *claim*, cryptographically bound to its source — the
  signature proves **who** sealed it and that it is **untampered**, not that the
  lens is good. The lens earns "good" upstream, from `scripts/validate_lens.py`
  (held-out lift) and corroboration. Same doctrine as every number in the repo.
