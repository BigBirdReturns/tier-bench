# Breadth-scaling: the first measured waterline (2026-07-18, overnight)

One spec, N independent field-normalization rules (12 primitive ops), per-rule
recall measured with isolating probes -> we see EXACTLY which rules drop.
Smoke: reference hits 1.0 at every N. All grading BOM-tolerant (lesson 15).

## Monolithic recall vs N (Spark 5.3, effort low)
| N  | recall | drops |
|----|--------|-------|
| 10 | 1.000  | 0 |
| 20 | 1.000  | 0 |
| 40 | 1.000  | 0 |
| 80 | 0.9875 | 1 (suffix_trim) |
| 120| 1.000  | 0 |
| 160| see K=3 below |
| 240| 1.000  | 0 (single run) |

## N=160, K=3 (Spark): {0.9688, 0.9812, 1.000}  mean ~0.983, drops {5,3,0}
Adjudicated REAL, not harness: e.g. rule "if f53 ends with '_old' remove it",
probe "name_old" -> Spark returned "name_old" UNCHANGED. Rule simply not
implemented. Drops are STOCHASTIC (120 and one 160-run were clean) and
concentrated in LOW-SALIENCE rules (suffix_trim, upper, strip, abs_cap,
bool_flip, mod, lower) - the boring one-liners easy to overlook in a long list.

## Cross-model: Luna 5.6 N=160 = 0.9812 (dropped strip, bool_flip, suffix_trim)
The breadth waterline is GENERAL, not Spark-specific. Both cheap tiers drop
~2-3 of 160 rules. This is the first place ANY model measurably degraded in the
whole program - and it is on BREADTH (many independent requirements), not DEPTH
(20-stage chains held) or DIFFICULTY (knots held).

## Rescue: decomposition (4 scoped passes of 40 rules) N=160 -> 1.000 (run 1)
K=3 rescue confirmation in progress. If it holds, scoping context per pass is
the first structural intervention with a measured QUALITY delta (not just the
~35% context-cost delta CART0 crates showed) - the payoff the crate thesis
predicted, now at scale.
