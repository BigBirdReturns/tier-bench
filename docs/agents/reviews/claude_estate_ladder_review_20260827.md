# Estate session review — GPU fabric + K3 aperture ladder (2026-08-27)

**Author:** Claude (Fable 5 lineage), session on OCTO-L01
**For:** cross-lineage review (Sol + Claude council)
**Branch:** `claude/queue-estate-ladder-20260827`
**Lane:** driver (tier-bench repo). Heavy raw artifacts live in the estate tree; the committed
fabric-qualification capsule (`data/estate/fabric-qual-20260827/`) binds them by digest.

## What this asks the council to check

Not code correctness of a feature — this is an **operations + direction** review. Three questions:

1. **Are the new QUEUE rows (CLAUDE-5..11, OP-2/3) scoped right**, and is CLAUDE-7's redefinition honest?
2. **Is the fabric-qual evidence sufficient** to call the dual-3090 pool qualified, or does a claim overreach?
3. **Is the prize framing correct** — K3 + Fable-fingerprint aperture across 4×3090 — given K3 is 1.5 TB and streamed, not resident?

## What happened this session (all evidence on-disk, paths below)

### 1. Thermal requalification (supersedes prior dual-3090 calibration)
The card pair changed under the kit's feet: Dell-A gone, an MSI card now at bus 04. It was found
running an **inherited overclock** (Afterburner applying the departed card's bus-keyed cfg) and
**idling in P0 at ~98 W** — traced, after eliminating displays/CUDA-contexts/Afterburner, to three
orphaned llama-server runners holding contexts (root cause is core-side: hot spot 14 °C over its
sibling → repaste, tracked as OP-2). Kit hardened: per-card `coreLockCapMHz`, `validatedPairUuids`
gate, mutex singleton for fan-guard, heartbeat liveness. **2 h re-soak PASSED**: MSI (1200 cap)
89.7/92 °C, Dell-B (+800) 92.4/96 °C, 0/706 ≥99 °C, bench_bw verify_fails=0 both.
→ `gpu-thermal-kit/RUNBOOK.md`, `calibration/{cards.json,OCTO-L01.json}`, D-- memory.

### 2. Aperture night-shift v2 — 11.7 h all-engine saturation
K3 image **verified 96/96 vs HF download-metadata sha256, 0 mismatches** (integrity question
closed). Tensor census 8/96 at the time (now 34+, 0 NaN/Inf, resumable). Decode 2.1 M tokens/0
errors, NPU 648k infers, iGPU 918k. Self-healing sentinel recovered a `os.replace` write-race
mid-mission. → `estate/aperture-night-shift-v2-20260826/` (corrected receipt @1; the sentinel's
@0 receipt read a retired ledger path and is wrong — flagged in-packet).

### 3. GPU-fabric qualification — CLAUDE-5, **the headline**
Dual-3090 48 GB pool over Thunderbolt, four phases:

| mode | model | result |
|---|---|---|
| single | qwen3.5:27b, 1 card | 33.8 tok/s |
| **double-up** | 27b ×2, 1/card, concurrent | **69.4 tok/s aggregate — 2.05×, 98.5% retention** |
| split (capacity) | qwen3.5:35b-a3b-q8, 39 GB | 51.6 tok/s (MoE beats single-card dense) |
| split (worst case) | deepseek-r1:70b dense, 43.7/48 GB | 18.1 tok/s decode / 157 prefill |

Serving layer registered AtLogOn (`fabric-serves`). → `estate/fabric-qual-20260827/QUAL-SUMMARY.json`.
**Council check:** the "48 GB pool" claim rests on the 70B phase loading 43.7 GB across both cards
and serving; is that the right bar, or should a claim wait on a model that fills the pool tighter?

### 4. K3 cached decode — CLAUDE-7, **the recon reversal**
The July "KDA/MLA states not retained → no continuation" limitation that framed this rung was
**stale**: a 2026-08-03 session already built `run_cached_continuation.py` and proved 5 cached
tokens greedy-exact vs the 7¾ h monolithic oracle at 10.5×. This session **extended the chain to
10 tokens** — continuation reads *"The user is asking a technical systems question about
mixture[-of-experts]"*, and **margins grew** (gen-10: 11.05 logits, p₁ 0.907), i.e. the greedy
trajectory is decisive, arguing a monolithic anchor can be deferred.
→ `estate/k3-cached-chain-extension-20260827/SUMMARY.json`,
`estate/cached-chain-referee-fused-20260803/FINDINGS.md`.
**Council check:** is "margins grew, defer the anchor" sound, or is a sparse anchor still owed
before trusting the trajectory?

### 5. Doctrine captured
`estate/ESTATE-PLAYBOOK.md` — 19 rules (identity-by-UUID, heartbeat liveness, Task-Scheduler
ownership, Vulkan-pinning trap, os.replace race, solo benchmarks don't compose, resumability), each
citing the packet that paid for it.

## The prize and its blocker (CLAUDE-11 / OP-3)

Target: **K3, Fable-fingerprinted, as an aperture across 4×3090.** Framing the council should
sanity-check: K3 is 1.5 TB — it is *streamed per-layer off disk*, never resident, so 4 cards is a
**throughput/parallelism** play (and concurrent contrast probes), not capacity. The Fable
fingerprint is currently `PROVISIONAL_NONDISCRIMINATING` (contrast 0.0028, p=0.8) — so the aperture
*is* the contrast-probe campaign (CLAUDE-10): Fable-shaped vs neutral prompts through the cached
oracle, diffing routing geometry. Runnable on 2 cards now; scales to 4.

**Hard blocker:** OCTO-W01 (the second 3090 pair) is online on the tailnet (4 ms direct pong) but
exposes **no listener** — sshd/RDP/WinRM/ollama all closed, and it advertises no Tailscale SSH
(banner timeout; contrast n01 which does). Nothing can drive w01's GPUs until a listener exists
(OP-3, human step on that keyboard). n01 Tailscale SSH works but needs an operator browser-auth and
is the 4060 nuc, not a 3090.

## Files to review

Exact changed-file denominator of this branch after the 2026-08-28 repair commits
(vs `main`): **5 files** —

- `docs/agents/QUEUE.md` — rows CLAUDE-5..11 + 13, OP-2/3
- `docs/agents/reviews/claude_estate_ladder_review_20260827.md` — this brief
- `data/estate/fabric-qual-20260827/CAPSULE.json` — committed CLAUDE-5 evidence capsule (@3: adds the identity evidence denominator, serve pinning table, phase→serve binding, and per-card role keys; aggregate root `7d858295…` over 14 raw artifacts)
- `data/estate/fabric-qual-20260827/verify_capsule.py` — deterministic verifier with three levels (CAPSULE_ONLY / RAW_BYTES / RAW_SEMANTICS; CLAUDE-5 closure supported only at RAW_SEMANTICS_VERIFIED, where raw artifact contents must reconstruct every decision-critical claim — GPU UUIDs, card roles via UUID-pinned serve ports, effective core locks under the committed min-rule, ollama manifest digests, every per-sample token count, and recomputed decode *and* prefill medians for both streams)
- `tests/test_fabric_capsule_verifier.py` — hostile witnesses: internally-valid, correctly-rehashed raw evidence that contradicts the capsule must refuse (29 tests)

**Identity binding, stated honestly.** The @2 capsule asserted GPU UUIDs, core locks and
ollama manifest digests that nothing in its evidence denominator supported — those fields
could be rewritten and all three levels still passed. @3 closes that by adding the
*contemporaneous* artifacts to the denominator: the serve launcher's port→UUID pinning
table, the host mode + card registry + the applier that implements
`min(mode.coreLock, card.coreLockCapMHz)`, the three ollama manifest files themselves, and
a post-run device attestation. Card roles are now derived
role → UUID → pinned serve port → receipt stream, never from an nvidia-smi ordinal.
What this does **not** establish is named in `claim_boundary.non_claims`: the phase
receipts carry no per-run device telemetry, so the binding is policy-level. Closing that
needs a future run that emits per-run UUID and clock telemetry, not a rewrite of this one.

An earlier revision of this branch also changed `tier_runner/kimi3_common.py` and
`tests/test_kimi3_observatory.py` (blanket `.lock` partial-suffix rule). That behavior
change was out of the declared queue-and-review scope and is **reverted** on this branch;
the underlying lock-artifact problem moved to queue row CLAUDE-13. The revert commits
leave those two files byte-identical to `main`, so they no longer appear in the diff.

Estate-side context (cited, not committed):
- `estate/fabric-qual-20260827/QUAL-SUMMARY.json` — the headline evidence
- `estate/ESTATE-PLAYBOOK.md` — the doctrine
- `estate/k3-cached-chain-extension-20260827/SUMMARY.json` — the 10-token trajectory
