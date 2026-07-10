# Almanac hidden-knot vectors — coverage map

Three graded task families (`tasks/almanac_*.json`), each a complete
black-letter spec whose hidden vectors decide a **boundary application**, not
spec recall. All expected values derive from `reference/engine.py` (the
corroborated oracle) via `generate_vectors.py`; `--check` runs in CI so the
frozen fixtures can never drift from the reference silently. Every date is
synthetic — constructed to sit on a boundary — no real birth data (PII never
enters the repo).

## almanac_rule_boundary_001 — the lichun/jieqi knot (T3)

The written rule: the solar year begins at the *instant* λ = 315°, months are
30° λ-bands. The knot: January belongs to the previous solar year; the flip
happens mid-day at lichun, and the timezone moves the UT instant across the
boundary while the civil date reads the same.

| Vectors | Probe |
|---|---|
| 2020-01-15, 2020-02-03 | pre-lichun dates → previous year pillar |
| 2020-02-04 03:00 vs 15:00 UT | same civil date, opposite sides of the instant |
| 2020-02-04 12:00 @ +8 vs 22:00 @ +8 | tz shifts the UT instant across λ=315 |
| 2020-12-31 / 2021-01-01 | Jan 1 does NOT start a solar year |
| 2019-08-07/08 (liqiu), 1970-11-08 (lidong) | month-band edges away from lichun |
| 1984-02-06, 2000-05-05 | five-tigers stem coverage; mid-band ordinary |

Knife-edge guard: the generator asserts every vector's λ is ≥ 0.1° from any
band edge — no float ties, deterministic verdicts.

## almanac_record_binding_001 — which record governs (T3)

The written rule: day and hour pillars are functions of the **civil record**
(local date, local clock; anchor JDN 2458631 = 甲子); the sun-position pillars
elsewhere in the system need the absolute instant, which is why `tz` is in
every input. The knot: binding day/hour to UT (the "convert everything first"
reflex) moves pillars that must not move.

| Vectors | Probe |
|---|---|
| 1993-08-17 23:30 @ −11 / 0 / +13 | identical civil reading → identical pillars |
| 2020-02-04 12:00 @ +8 vs @ 0 | tz flips the year pillar elsewhere; day/hour must hold |
| 2019-05-27, +60d, −6000d | the anchor and 60k-day cycle consistency |
| 1999-12-31 23:59 / 2000-01-01 00:00 | 23:xx is 子 of the SAME civil day (declared no-rollover) |
| 1988-03-03 00:59 vs 01:00 | two-hour branch band edge |

## almanac_exception_class_001 — masters terminal at every stage (T2)

The written rule: digit reduction stops at 11/22/33 at ANY stage. The knot:
the exception class only changes the answer when a stage lands on a master —
the all-digits school and the final-only school agree everywhere else (digit
sums are congruent mod 9).

| Vectors | Probe |
|---|---|
| 1996-07-08 → 22, 1902-03-05 → 11, 1948-02-09 → 33 | totals landing on masters (the schools diverge here) |
| 2002-11-11, 1929-11-22, 1988-11-29, 1975-04-22 | component-stage masters (11 month, 22 day/year, 29→11) |
| 1990-06-15, 1966-03-06, 2000-01-01, 1984-12-28, 1959-09-09 | ordinary reductions incl. two-stage (28→10→1) |

## Status

**No model results are claimed on any almanac task.** The corpus is the ruler;
the first floor run against it is future work and will be sealed as its own
evidence layer when it happens.
