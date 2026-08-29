# Strict-state block verification — full-depth result (2026-08-28)

Every numerical and PASS claim below is produced by the committed verifier
chain, not by prose. The authority is
`strict_baseline_gate.gate()`, invoked by `run_strict_block_verify.py`; its
output is bound in the committed capsule
`data/estate/k3-strict-state-20260828/STRICT-STATE-CAPSULE.json`, whose
aggregate private-evidence root is:

    743445ce88508bf7352066cae457e0644e3ca39bdf153c8aae6e2145f2c10a7e

Sealed sequential-baseline manifest aggregate root (pinned by the gate with
`--expect-baseline-root`; a substituted baseline is refused):

    a92f102b3459a613b86ed1a013209cf59006b6bbf8666d18b1c81370a96a2293

Reproduce, on a host holding the authorized private evidence root:

```
python data/estate/k3-strict-state-20260828/verify_strict_state_capsule.py                    # CAPSULE_VERIFIED
python data/estate/k3-strict-state-20260828/verify_strict_state_capsule.py --private-root <R> # + PRIVATE_BYTES_VERIFIED, PRIVATE_EVIDENCE_VERIFIED
python -m k3_dspark_speculative.strict_baseline_gate --run-dir <R> --parent-run-dir <P> \
    --baseline-manifest <M> \
    --expect-baseline-root a92f102b3459a613b86ed1a013209cf59006b6bbf8666d18b1c81370a96a2293 \
    --expected-accepted 2   # REQUIRED
```

That baseline root is now the digest of the **complete canonical manifest**,
excluding only its own root field. Under the `@1` rule it covered the layer,
checkpoint and logit digests alone, so a substituted manifest could rewrite the
model index, the parent checkpoint, the parent sequence length, the accepted
denominator, or an `appended_token` - the token ground truth itself - and still
satisfy `--expect-baseline-root`. Nothing outside the root field is unbound now.
The manifest additionally carries the parent prefix digest, the accepted
denominator, per-position content roots for the attn_res bank and final hidden,
and the comparison policy the gate must implement.

`--expected-accepted` is **required**. Omitting it made the boundary criterion
unconditionally true and left no record of whether a denominator had been
supplied, so a committed capsule could not distinguish a gated PASS from an
ungated one. The gate now refuses to run without it, checks it against the
manifest's own denominator, and serialises it into the verdict and the capsule.

## Headline (capsule-cited)

**STRICT_CANONICAL_COMMIT: PASS**, emitted by the gate, on all seven criteria:
exact token stream; exact accepted boundary (K=2 against the declared
denominator); all components present; every component root bit-exact; baseline
manifest and run identities verified; no unbound state; adopted checkpoint at
the exact accepted boundary.

- **93/93 layer caches exact at each accepted position** (69 KDA:
  conv_q/conv_k/conv_v/recurrent; 24 MLA: key/value), plus attn_res bank,
  final hidden, position, and prefix — content-bound roots from
  `contracts.py`. Zero divergent components; `first_divergence: null`.
- Committed tokens `12200, 636, 1891` equal the sequential chain; the
  correction equals the sealed baseline argmax.
- Checkpoint K=2 is adoptable as canonical continuation state **without
  sequential replay**.
- Baseline custody is rehashed inside the gate: every named baseline layer
  cache, checkpoint, and logits file must match the manifest digest before it
  is used as ground truth.

Logit equivalence is reported **separately** and never weakens the state gate:
`LOGIT_ARGMAX_EQUIVALENCE` true and `LOGIT_MARGIN_EQUIVALENCE` true at both
positions; `LOGIT_NUMERICAL_EQUIVALENCE` false (max abs diff ~8e-6), confined
to the stateless batched finalize matmul, which reduces in a different order
than the 1-row sequential finalize. Logits are recomputable and hold no
continuation custody.

KDA-only checkpointing would not have sufficed: adoption required kda + mla +
attn_res bank + position + prefix, all captured per position.

## Economics (this fixture, accepted K=2, cache-warm)

| custody mode | wall (s) | economics |
|---|---|---|
| VERIFY_ONLY (chunk lane) | 871.6 | 2.83x verification throughput — **noncanonical** |
| EXPERIMENTAL_BLOCK_STATE_ADOPTION | 871.6 | measurement only; chunk state is kernel-drifted in 93/93 layers |
| STRICT_CANONICAL_COMMIT (this run) | 1280.1 | **1.38x canonical, replay-free** |

The strict lane matches the previous honest 1.39x while eliminating the
sequential reconstruction that figure required. The 872-vs-1280 s gap is
per-position MoE expert streaming (union mean 67.5 experts/layer, max 97, vs
the chunk path's 44.6 — the drifted chunk activations under-covered the expert
set). Target weight bytes read 311.4 GB in one traversal.

Speedup scales with acceptance: the sequential lane costs (K+1) x 588 s while
the strict traversal grows sublinearly under weight residency. K=2 is the
current drafter limit, not a lane limit.

## Repository state vs local state

- **Local physical observation:** PASS (this run, this host).
- **Repository reproducibility:** `CONDITIONAL_PASS`. A fresh checkout reaches
  `CAPSULE_VERIFIED` on its own — which now includes binding the two files that
  compute the verdict (`run_strict_block_verify.py`, `strict_baseline_gate.py`)
  by **repository-stable coordinates**: the canonical LF byte stream git
  actually stores, and git's own blob id for it. The previous capsule recorded
  the Windows working-tree CRLF digest, which no fresh checkout on any platform
  could ever reproduce, and nothing rehashed it.
  With the authorized private root the verifier reaches
  `PRIVATE_EVIDENCE_VERIFIED`, which is no longer a reading of the precomputed
  adjudication: it loads the authenticated baseline manifest, reloads all 188
  retained per-position state tensors and both candidate checkpoints, and
  **re-invokes the committed gate** to recompute all seven criteria from the
  physical artifacts. The stored adjudication is then only a cross-check.
  Digest-correct stub tensors reach `PRIVATE_BYTES_VERIFIED` and stop there —
  the test fixture that once expected them to verify now asserts exactly that
  refusal.
- **Admission:** for the council. Nothing here merges itself.

## Next levers (not started)

1. Expert-union batching inside the resident layer — removes most of the
   1280-vs-872 s gap without touching numerics.
2. Deeper acceptance (better drafter / multi-draft).
3. Energy per committed token, which falls with acceptance. Thermals during
   this run stayed ~95 W / 44-45 C on the verify card, inside the admitted
   envelope.
