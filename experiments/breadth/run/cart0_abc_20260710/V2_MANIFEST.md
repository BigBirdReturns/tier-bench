# CART0 resurfacing experiment — v2 run manifest (FROZEN)

**Frozen 2026-07-10.** Authority: operator steering. This manifest is a
pre-registration a rerun loads verbatim. It is FROZEN: any change to the
estimand, arms, boot map, boundary messages, protocol, grading, or disposition
rules mints a **new version id** (`cart0-abc-v3`, …); you do not edit v2 after a
solver call has run against it. Supersedes the *design* of the v1 run
(`receipt.json`, confounded — see EP-007), not its evidence.

Why v2 exists: v1 was causally non-discriminating because the two-turn plan-first
protocol let every planner restate the boot-loaded rule before the boundary, so
all arms self-resurfaced (EP-007). v2 removes that **structurally** and preserves
the administration transcript that v1 did not.

## Registered estimand (do not drift)
After a rule is loaded at boot, does **reactivating the applicable rule at the
consequential boundary** outperform boot exposure alone (A) and generic recency
(C)? Common boot exposure in every arm is the **registered control, not a
confound**. This is NOT a test of first-time just-in-time instruction injection.

## Fixed design
- **Item:** `count_matches` — the measured depth-regression item (bare spec:
  `../replays/claude2_distinct_items_20260710/replay04_count_matches/spec.md`).
- **Common boot map (every arm):** the bare `count_matches` spec with this exact
  scaffold block appended (the target rule — the registered control):

  ```
  ## Rule commitments (hold these; do not re-derive)

  - escape-inside-class malformed-vs-non-match boundary: inside a character
    class, a backslash is a literal member (and a legal range endpoint), not an
    escape prefix. Outside a class, backslash is an escape prefix. Hold this
    as a fixed rule interpretation — do not second-guess it mid-solve.
  ```

- **Protocol (structural anti-rehearsal — the v1 fix):**
  1. Deliver the common boot map.
  2. Require a **fixed-format first response of exactly `READY`** — no free prose,
     so the solver cannot rehearse/restate the rule before the boundary. (v1's
     planning turn is deleted; do NOT replace it with "plan but don't mention the
     rule" — that is a judgment gate that drifts, EP-007 residue.)
  3. Deliver the registered boundary message for the arm.
  4. Solver implements `solution.py`.
- **Arms (boundary message is the ONLY manipulation):**
  - **A — boot-only (neutral):** "Planning phase complete. No further constraints to add at this point beyond what the spec already gave you earlier. Now implement: write solution.py in your working directory and verify with python visible_tests.py until it passes. Reply with only the final exit status."
  - **B — applicable rule resurfaced:** "Before you write, hold the applicable rule commitment: inside a character class, a backslash is a literal member (and a legal range endpoint), never an escape prefix; outside a class it escapes. Now implement: write solution.py and verify with python visible_tests.py until it passes. Reply with only the final exit status."
  - **C — irrelevant-but-valid (recency control), length-matched:** "Before you write, hold this standing project rule: never create or modify any file other than the one you were asked to produce, and never read anything outside your working directory. Now implement: write solution.py and verify with python visible_tests.py until it passes. Reply with only the final exit status."
- **Balanced blocks:** run `A_k B_k C_k` per block, k = 1..K (start K=5). An early
  credit stop yields complete blocks, never A=5/B=3/C=1.
- **Fresh session per trial; same model + effort across all arms.**

## Mandatory preservation (the v1 administration-custody fix)
Before any solver call, the harness MUST capture to the repo, per trial:
- the exact boot prompt bytes as delivered;
- every turn's message and response verbatim (including the `READY` turn);
- per-trial model-invocation receipt (model, effort, tokens, session/thread id);
- administration order and block index;
- abort records.
A CART0 causal claim is not independently replayable until the transition that
caused it is preserved as bytes. Missing transcript ⇒ the administration is
**ineligible** for the causal comparison (not a failure — ineligible).

## Grading & disposition (GATED — not editable by the solver)
- Hidden grader only; candidates **sealed before grading**; solver off the
  scoring path; every grade re-run by the driver.
- **Aborted or ineligible (missing-transcript) trials mint neither pass nor fail.**
- **No comparative verdict** until the balanced blocks are complete AND every
  counted trial has a preserved transcript. Report per-arm pass rates with n.
- Prediction (for falsification, not to steer grading): resurfacing (B) dominates
  residue-consequence accuracy; A and C do not separate on it.

## Headline factorial (only after the causal A/B/C run is clean)
2×2: map resolution {256, 4096} × delivery {boot-only, resurfaced}. Resolution is
expected to help narrative reconstruction; resurfacing to dominate
residue-consequence accuracy.

## Deferred second experiment (do NOT fold in as an arm)
"Does self-generated articulation during planning reactivate a boot-loaded
constraint?" — the v1 incidental signal (single-turn 1/3 vs two-turn plan-first
5/5, same item). Runs as its OWN experiment after the clean external-resurfacing
run; adding it as a fourth arm reconflates the two causes.

## Provenance
- Confound that motivated v2: `data/continuity/EPISODES.md` EP-007.
- v1 run (confounded, not sealed) + corrected analysis: `./receipt.json`,
  `./ADMINISTRATION.md`.
- Doctrine: `data/continuity/CART0_CONTRACT.md` (projection + gate; the boundary
  message is the gate reasserting the applicable constraint at the transition).
