# LEDGER — tier-uplift

Every run, in order. Score is on the **hidden** grader unless noted. Keep it all.

## Prior finding carried in (the three horizon confounds)

Before this experiment: three attempts to show memory giving Haiku a frame it
couldn't hold alone. All three, Haiku held the frame **without** memory —
recovered from the committed artifact (UI conventions), from local judgment
(refused to fabricate), and from first-principles reasoning (re-derived the
`min()` rule as "trust caps the weakest link"). Conclusion that motivates this
experiment: **judgment re-derives; it does not need memory.** What a cheap model
lacks is carried state + selection. That is what the harness must supply.

---

## Task 01 — parse_duration

Grader: `hidden_tests.py`, 38 cases (12 valid + 26 invalid). Visible validator
the harness may use: `visible_tests.py`, 11 cases.

### Pass 0 — baseline (solo, no harness)

| run | model | hidden score | notes |
|---|---|---|---|
| b0 | haiku | **38/38** | solo, one shot |
| b0 | sonnet | **38/38** | solo, one shot |
| b0 | opus | **38/38** | solo, one shot |

**Result: NO GAP.** Haiku one-shots parse_duration as perfectly as opus. A
fully-specified deterministic task tops out at the cheap tier — no ceiling for a
harness to reach. Task retired for uplift. This is consistent with the horizon
finding: well-specified *judgment* re-derives at every tier. The gap must be
sought where one-shot output is **variable or incomplete** — harder algorithms
(backtracking), or under-specified / long-horizon work.

---

## Task 02 — wildcard_match (`*`, `?`, `[...]`, escaping)

Backtracking on `*` plus character-class + escaping edge cases: where a single
shot slips. Oracle-graded against a curated + fuzzed case set (reference
hand-verified on the tricky cases).

### Pass 0 — baseline (solo, no harness)

| run | model | hidden score | notes |
|---|---|---|---|
| b0 | haiku | **10681/10681 (100%)** | solo, one shot |
| b0 | sonnet | **10681/10681 (100%)** | solo, one shot |
| b0 | opus | **10681/10681 (100%)** | solo, one shot |

**Result: NO GAP, again** — even on a genuinely hard task (backtracking + char
classes + escaping, 10.6k cases). Two hard, fully-specified tasks; zero tier
separation. Strong finding: **capability on checkable tasks is saturated at the
cheap tier.** The frontier gap is NOT on tasks with a clean spec + validator — it
is on tasks with *no clean validator*: ambiguous intent, subtle judgment,
completeness under uncertainty. Pivoting there.

---

## Task 03 — subtle bug-finding (planted bugs, graded subtlety)

Objective (known answer key) but *open* (a single read misses the subtle bugs; a
multi-lens sweep does not). This is where a tier gap should finally appear, and
where the harness (multi-modal sweep + selection, loop-until-dry) has real value.
Grading: a blind opus judge scores each candidate's bug list against the answer
key, N bugs found out of 7.

### Pass 0 — baseline (solo, no harness)

| run | model | bugs found / 7 | missed | notes |
|---|---|---|---|---|
| b0 | haiku | **6/7** | B5 off-by-one window | solo, one pass |
| b0 | sonnet | **7/7** | — | solo, one pass |
| b0 | opus | **7/7** | — | solo, one pass |

**GAP FOUND (finally).** Haiku missed exactly the subtle off-by-one (B5) that
both higher tiers caught one-shot. Per-bug grade audited against `answer_key.md`.
(All three also found a real empty-input bug not in the planted set — noted, not
scored.) The ceiling to close: **haiku 6/7 → sonnet 7/7.**

### Pass 1 — haiku + multi-lens sweep (harness)

Decompose the review into targeted lenses (boundary/off-by-one; state/side-effect;
error-handling/silent-failure; edge-cases), pool + dedupe the union. The
boundary lens exists specifically to make selection *see* B5. Target: 7/7.

| run | model | bugs found / 7 | notes |
|---|---|---|---|
| p1 | haiku×4 lenses (union) | **7/7** | boundary lens caught B5 with a full trace |

**PASS 1 SUCCESS — haiku + harness = sonnet.** Solo haiku 6/7 → haiku with a
4-lens sweep (boundary / state / errors / edge) 7/7, matching sonnet-alone and
opus-alone. The gap bug (B5, the off-by-one) was caught by the boundary lens —
the pass that does nothing but trace loop bounds. This is "iteration can only buy
what selection can see": the lens is what makes selection see it.

Per-bug source in the union: B1 state+edge+errors · B2 state · B3 errors+edge ·
B4 boundary · **B5 boundary (full trace)** · B6 errors · B7 errors+edge.

**Honest cost.** Recall matched sonnet, but the sweep over-reports: the errors
lens raised a false positive (`running_average` empty-history ÷0 — impossible,
`append` runs first). Recall up, precision down; 4 passes vs sonnet's 1 (token
cost not optimized yet, per the charter). The FP is exactly what Pass 2 (a
verify/critic pass) must filter — selection proper, not just coverage.

### What this task cannot show
sonnet and opus BOTH scored 7/7 at baseline here, so this task can't demonstrate
`sonnet + harness → opus`. That needs a harder task where opus out-finds sonnet
solo. Built as task 04.

---

## Task 04 — ledger (8 bugs, several cross-function)

Larger module (a payments ledger); bugs include cross-function invariants
(non-atomic transfer breaking money conservation) and interaction bugs
(self-transfer). Graded against `answer_key.md`, 0.5 = right location/partial.

### Pass 0 — baseline (solo, no harness)

| run | model | bugs / 8 | missed |
|---|---|---|---|
| b0 | haiku | **4.0** | L4, L5, L7, L8 |
| b0 | sonnet | **6.5** | L7 (self-transfer); L6 partial |
| b0 | opus | **8.0** | — |

**A full gradient, finally: haiku 4 < sonnet 6.5 < opus 8.** The bug separating
sonnet from opus is L7 — the self-transfer (`from_id == to_id`) — which only opus
flagged. Two ceilings to climb on ONE task: haiku→sonnet and sonnet→opus.

### Pass 1 — 4-lens sweep on BOTH tiers (harness)

Lenses: atomicity/state · interaction/adversarial (the L7 lens) · type/precision ·
validation/degenerate. Union + dedupe, grade each tier's union.

| run | model | bugs / 8 | target | verdict |
|---|---|---|---|---|
| p1 | haiku×4 (union) | **7.5** | ≥ 6.5 (sonnet) | ✅ **past sonnet, near opus** |
| p1 | sonnet×4 (union) | **8.0** | 8.0 (opus) | ✅ **= opus** |

**BOTH RUNGS CROSSED, ONE TASK, ONE HARNESS.** haiku 4.0→7.5 (clears sonnet's
6.5, approaches opus's 8); sonnet 6.5→8.0 (matches opus). The gap bugs were
caught by the lens built for them: atomicity → L1/L2/L8; validation → L4/L5;
**interaction → L7** (sonnet's interaction lens found the self-transfer even more
precisely than opus solo — the phantom `total_deposits` inflation on a no-op
self-transfer). haiku's L7 is 0.5 (raised the case, analyzed it via the L1 lens).

Per-bug union sources:
- haiku: L1/L2/L8 atomicity · L2/L6/L7½ interaction · L3 precision · L4/L5 validation
- sonnet: L1/L2/L8 atomicity · L6/L7 interaction · L3 precision · L4/L5 validation

**Honest cost.** Recall soared; the price is 4 passes per tier + a pooling step
(≈4× baseline tokens, not yet optimized). Precision was decent — sonnet's lenses
correctly CLEARED the double-open case as not-a-bug rather than over-flagging.
The remaining haiku 0.5 gap on L7 is the kind of thing a 5th "adversarial
semantics" lens or a verify/critic pass would close.

---

## Task 05 — intervals (portability + the reasoning-vs-attention boundary)

Run with the **FROZEN GENERIC lens set** (`../lenses.md`), NOT bug-tailored — the
fair test of "harness vs experimenter." 5 bugs: B1 is a deep algorithm bug
(greedy sorted by start not end); B2–B5 attention/validation. `busiest_point` is
a correct-but-suspicious trap.

### Pass 0 — baseline (solo)

| bug | class | haiku | sonnet | opus |
|---|---|:--:|:--:|:--:|
| B1 greedy sort-key | deep | ✓ | ✓ | ✓ |
| B2 merge touching | attn | ✓ | ✓ | ✓ |
| B3 input mutation | attn | ✗ | ✓ | ✓ |
| B4 endpoints | attn | ✓ | ✓ | ✓ |
| B5 no start≤end validation | valid | ✗ | ✗ | ✗ |
| **total /5** | | **3** | **4** | **4** |

**Two findings that invert the prior hypothesis:**
1. The **deep** bug (B1, greedy sort-key) was caught by ALL tiers incl. haiku —
   *not* the residual. (Caveat: B1 is a textbook result, so this is likely
   pattern **recall**, not fresh reasoning; a novel-algorithm probe is still
   owed to find the true reasoning floor.)
2. The haiku→opus gap is **B3, an attention/state bug**, not the algorithm. And
   **B5 (validation) is missed by all three** — a shared blind spot, elicitable
   but not a tier differentiator.

So even here the gap is *deployment* (attention), consistent with the spine.

### Pass 1 — haiku + FROZEN generic 5-lens sweep

Prediction: state lens → B3, contracts lens → B5. If 5/5, haiku+generic-harness
**beats opus-solo** (which missed B5) using untailored lenses = portability +
above-teacher signal.

| run | model | bugs /5 | target | verdict |
|---|---|---|---|---|
| p1 | haiku×5 generic (union) | **5/5** | > 4 | ✅ **beats opus-solo (4) AND sonnet-solo (4)** |

Union sources: B1 adversarial · B2 control/data/contracts/adversarial · B3 state ·
B4 all lenses · B5 contracts. The two bugs haiku missed solo (B3, B5) were caught
by the lenses built for them — state and contracts — from a set frozen BEFORE the
bugs existed.

**Two hard results:**
1. **Portability confirmed.** Generic, untailored lenses lifted haiku 3→5. The
   uplift is the harness's, not experimenter tailoring. ("Am I the harness?" → no.)
2. **Above-teacher signal.** haiku+generic-harness (5/5) > opus-solo (4/5) and
   sonnet-solo (4/5) — both missed B5. The harness makes the cheap model exceed
   the raw frontier model's single pass. This is the distillation-target thesis
   proven: harness-amplified cheap output can beat the teacher that would label it.

Honest caveats: the 5 lenses also over-report (structure-validation, tuple-type
extras — some defensible, some noise); precision cost unmeasured here. B1 is a
textbook result (recall, not novel reasoning) — the true reasoning floor is still
unprobed. N=1 task for the portability claim.

## Verdict so far

- **Checkable tasks (01, 02): no gap** — cheap tier already tops out; nothing to lift.
- **Judgment/coverage tasks (03, 04): real gap, and the harness closes it.**
  - Task 03: haiku 6/7 → **7/7 (= sonnet)**.
  - Task 04: haiku 4.0 → **7.5**; sonnet 6.5 → **8.0 (= opus)**.
  - Task 05: haiku 3 → **5/5 (> opus-solo's 4)** with a FROZEN GENERIC lens set.
- The mechanism is always the same: **decompose the work into targeted lenses so
  selection can see what one pass misses.** "Iteration can only buy what selection
  can see" — the lens is the aperture. Coverage is bought at a precision/token
  cost that a verify pass (Pass 2, next) is meant to pay down.

**What the boundary looks like now.** The tier gap, everywhere it appeared, was a
*deployment/attention* gap, not a knowledge gap — even the one "deep" algorithm
bug (B1) was caught by every tier (though it's a textbook pattern, so recall, not
proof of novel reasoning). The two things that are NOT elicited-by-default and DO
separate tiers were both attention (B3 mutation; and the shared B5 blind spot). A
generic harness elicits them, and in doing so a cheap model **exceeded the raw
frontier model** (task 05). This is the strong form of the thesis: the frontier's
single-pass edge on this class of work is an *allocation* advantage the harness
can rent — and then hand to a smaller model, or distil into its weights.

**Still owed (honest gaps):**
- A **novel-algorithm** probe (not a textbook bug) to find the true *reasoning*
  floor — the one place elicitation might fail and only bigger weights suffice.
- **Precision**: the sweep raises recall but over-reports; a verify/critic pass
  (Pass 2) to filter false positives, and a measured FP rate.
- **Token efficiency**: still ~4–5× baseline; unoptimized by charter.
- **Portability at N>1**: task 05 is one datapoint for the generic-lens claim.
