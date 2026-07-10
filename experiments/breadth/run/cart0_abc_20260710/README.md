# CART0 A/B/C resurfacing run — 2026-07-10 (INCOMPLETE + CONFOUNDED, NOT SEALED)

This directory is the exact work the Fable session completed before a provider
credit abort. It is preserved for cross-engine review (Codex), not sealed.

**One-paragraph orientation.** The registered A/B/C design held a common boot
map (the target rule present at boot in ALL three arms — this is the CONTROL,
not a confound) and varied only the decision-boundary message: A neutral, B the
applicable rule reactivated, C an irrelevant valid rule. The estimand: does
reactivating an already-known rule at the boundary beat boot-exposure-alone and
generic recency? The run is **confounded** because the two-turn protocol let
every planner restate the boot-loaded rule in its turn-1 plan — so all arms,
including the controls, self-administered the treatment before the boundary.
6 of 15 trials aborted on credit exhaustion (missing, not failed); the 9 that
completed all graded 10/10. **No comparative verdict.**

**What is here (hash-bound):** `receipt.json` (full causal analysis + the
corrected clean rerun), and `{A,B,C}/trial*/` each with the candidate
`solution.py` and its deterministic `grader_output.txt`.

**Corrected clean rerun** (see receipt): keep common boot; PROHIBIT the planning
turn from restating the target; deliver A/B/C boundary messages as registered;
add a mechanical contamination check (planner articulates target pre-boundary =>
contaminated, neither pass nor fail); run balanced blocks. Do NOT switch to
bare-boot first-time injection — that tests a different mechanism.

Episode: EP-007 in `data/continuity/EPISODES.md` (PR #64 branch).
