# Strict-state block verification — first full-depth result (2026-08-28)

Mission OCTO-L01-PR-STACK-AND-STRICT-STATE-CLOSURE-001, phase 8. Fixture: the
existing CLAUDE-12 campaign fixture (parent generation-011, sequence length
139, depth-7 DSpark proposal `12200,636,347,47603,36,8,316`). No CLAUDE-10
registered item consumed. Raw run artifacts and per-position states remain in
private estate custody (`pr-stack-strict-state-closure-20260828/
phase8-strict-successor/`), digest-cited here.

## Headline

**STRICT_CANONICAL_COMMIT: PASS.**

`SEQUENTIAL_WITHIN_LAYER_STRICT` (one weight residency per layer; positions
advanced inside the resident layer in the exact sequential recurrent order
with the exact single-position kernels; CPU state round-trip between
positions) reproduces the sequential cached chain's continuation state
**bit-exactly**:

- token stream: accepted 2 (drafter-limited), correction 1891; committed
  `12200, 636, 1891` — exactly the sequential chain.
- per-position full-state checkpoints at positions 1 and 2 vs the sealed
  ARM A sequential baselines (generation-012 @140, generation-013 @141):
  **93/93 layer caches exact at both positions** (69 KDA: conv_q/k/v +
  recurrent; 24 MLA: key/value), attn_res residual bank exact, final hidden
  exact, position and prefix exact. Content-bound hashing (contracts.py @2),
  zero divergent components.
- checkpoint adoption law satisfied: checkpoint K=2 is adoptable as canonical
  state **without sequential replay**.
- per-position logits: argmax and margins equal (636 @13.8013; 1891 @11.7123);
  not bit-equal to the sequential finalize (max abs diff 8.1e-6) because the
  batched K-row lm_head matmul reduces in a different order than the 1-row
  sequential finalize. Logits are stateless and recomputable; continuation
  custody is unaffected.

KDA-only checkpointing would NOT have sufficed: adoption required kda + mla +
attn_res bank + position + prefix, all captured per position.

## Economics (this fixture, acceptance 2, cache-warm)

| custody mode | wall (s) | committed speedup vs 588 s/token sequential |
|---|---|---|
| VERIFY_ONLY (chunk, predecessor) | 871.6 | 2.02x on the committed-3 basis (predecessor verification-throughput figure: 2.83x) |
| EXPERIMENTAL_BLOCK_STATE_ADOPTION (chunk) | 871.6 | noncanonical — 93/93 layers kernel-drifted (phase 7 re-audit) |
| STRICT_CANONICAL_COMMIT (this run) | 1280.1 | **1.38x with canonical state adopted free** |

Reading: the strict lane now matches the old honest 1.39x number while
*eliminating the sequential reconstruction entirely* — the 1.39x predecessor
figure required replaying the committed tokens through the sequential runner;
the strict lane's 1.38x is a single traversal that verifies AND commits
canonical state. The remaining gap to the chunk lane's wall (1280 vs 872 s) is
per-position MoE expert streaming: exact per-position routing touched
union-mean 67.5 experts/layer (max 97) vs the chunk path's 44.6 — the
chunk-drifted activations under-covered the expert set, which is itself
evidence the strict path is doing different (correct) work. Weight bytes read:
311.4 GB, one traversal.

Speedup scales with acceptance: at acceptance K the sequential lane costs
(K+1) x 588 s while the strict traversal grows sublinearly (weight residency
amortized). Acceptance 2 is the current drafter limit, not a lane limit.

## Verdict language (binding)

- The **2.83x** figure remains chunk-lane verification throughput. It may not
  be called canonical committed throughput.
- The **honest canonical number is now 1.38x measured under
  STRICT_CANONICAL_COMMIT** (previously 1.39x via sequential reconstruction).
- The canonical K3 chain remains the sequential cached chain; strict-lane
  checkpoints are admissible because they are bit-identical to it.

## Next levers

1. Expert-union batching inside the resident layer (route all positions
   first, load the union once, execute per position) — removes most of the
   1280-vs-872 s gap without touching numerics.
2. Deeper acceptance (better drafter or multi-draft) — the speedup
   denominator grows linearly while the traversal grows sublinearly.
3. Thermal/energy: run held ~95 W / 44 C on the verify card — far inside the
   admitted envelope; energy per committed token drops with acceptance.
