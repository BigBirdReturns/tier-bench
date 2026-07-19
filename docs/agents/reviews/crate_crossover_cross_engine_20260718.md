# Cross-engine comparison — the S* crossover, two independent runs (2026-07-18)

Per CROSS_ENGINE_PROTOCOL: both measurements sealed independently before this
exchange. Claude sealed `crossover_v1` at `dcadc9d` (branch
`claude/smoke-before-cage-residue`) with no knowledge of the Codex run; Sol
sealed `codex_crate_crossover_10` at `7f21b58` (branch
`codex/crate-crossover-1`) as an administrative partial. This note compares
conclusions; it mints no new capability evidence.

## The two designs

| | Claude `crossover_v1` | Sol `codex_crate_crossover_10` |
|---|---|---|
| tasks | 3 fresh T1 flags, frozen desk referee | 10 crate replays/deterministic tasks |
| arms | fable full-ceremony desk + haiku hands vs haiku tenants | fable pointer-only desk + haiku subjects vs haiku subjects |
| completed | both arms 3/3 (complete) | 4 matched pairs of 10 (partial) |
| desk cost | $2.85 (24 turns, crate authoring + adjudication) | $0.27 (30.9k ctx, pointer-only instructions) |
| hands/subjects | $0.227 vs tenants $0.208 | observed subjects $0.508 across 8 |
| verdict claimed | 14.8× desk loss; S* = capability line (lesson 20) | none — administrative partial, ratio withheld |

## Where the engines agree

1. **Hand-cost parity.** Sol's four matched pairs price C and D subjects nearly
   identically per task ($0.051/$0.054, $0.062/$0.058, $0.114/$0.089) — the
   same mechanism Claude's run isolated: hands cost what hands cost; only the
   overhead above them differs. Independent designs, same core observation.
2. **Denominator discipline held on both sides.** Claude receipted both arms'
   full costs; Sol kept 12 policy-blocked and 2 failed cells in the
   denominator and refused a ratio from 4 pairs against a desk priced for 10.

## Where Sol's data sharpens Claude's claim

Claude's 14.8× is the ceremony's **upper bound, not its floor**. Sol's desk
spent $0.27 emitting pointer-only instructions for ten tasks — a 10× leaner
desk than Claude's full crate-authoring session. A lean pointer-desk over
Claude's own hands would have lost ~2.4×, not 14.8×. Lesson 20's direction
survives (the desk still loses below the capability line) but its magnitude is
a design variable: **ceremony cost is chosen, not fixed.**

## What Sol hit that Claude didn't

A third wall type: 12/20 subjects blocked by the external-disclosure safety
reviewer **before any provider spend**, six task families symmetrically denied
in both arms. The program's walls to date: transport (Spark app systemErrors),
sandbox non-equivalence (Sol-root NO-GO), and now disclosure policy. All three
fire before capability is ever measured — reinforcing lesson 20's corollary
that the tallest walls in cheap delegation are not model walls.

## Open

Sol's N=10 remains unresolved (no retry authorized by the partial); the six
policy-blocked families are unmeasured in both engines; neither run measured
capability-wall tasks — the regime where the desk is predicted to earn its
keep is still untested in both lineages.
