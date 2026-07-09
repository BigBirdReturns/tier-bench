# Almanac — deterministic birth-data engines with a citation trail

The driver's (Fable's) design for the web app: take any combination of birth
criteria (date, time, place) and compute the classical derived fields, each
output carrying its derivation — "cite the math." The systems themselves are
folk taxonomies; the *computations* are published, deterministic algorithms,
which is exactly what makes this buildable, gradeable, and tier-mappable.

## Architecture (backend first — the part that must be right)

```
engines/            pure functions, stdlib only, no I/O
  numerology.py     life path (Pythagorean digit reduction, master numbers)
  bazi.py           Four Pillars (sexagenary year/month/day/hour)
  western.py        tropical sun + moon sign/degree (Meeus low-precision)
api                 one endpoint: birth criteria in -> {field: {value, method, steps[]}}
explain             template layer: renders each computed field's standard read,
                    quoting the steps[] — prose cites the math, never invents it
```

Every engine returns `{value, method, steps}` — `steps` is the arithmetic
audit trail (e.g. `"(1981-4) % 10 = 7 -> 辛"`). The explanation layer may only
reference computed values. No engine output, no sentence.

## Convention registry (the design decision that matters)

Each system has variant schools; ambiguity is resolved by *declared convention*,
not silently. The API echoes the conventions used:

| Field | Convention chosen | Alternatives exist |
|---|---|---|
| Life path | reduce month/day/year separately; preserve 11/22/33 at every stage | reduce-all-digits variant |
| BaZi year boundary | solar year begins at lichun (sun λ=315°), not Jan 1 | lunar new year variant |
| BaZi month | branch from apparent solar longitude bands (315°+30k = month start — the jieqi ARE λ multiples of 15°); stem by five-tigers rule from year stem | table-of-dates approximations |
| BaZi day | sexagenary day cycle via JDN offset, anchored to corroborated charts | various epoch anchors (equivalent) |
| BaZi hour | civil clock time, 2h branches, five-rats rule for stem; day rolls at midnight (no late-zi adjustment) | true-solar-time; late-zi day rollover |
| Western | tropical zodiac; positions via Meeus low-precision sun (~0.01°) and truncated lunar theory (~0.3°) — sign-accurate except within ~1° of a cusp, which the output flags | sidereal; full ephemeris |
| Dermatoglyphics etc. | NOT derivable from birth data — accepted only as *observed* inputs, labeled `observed`, never computed | — |

## Verification (the harness gets the last word)

- `reference/engine.py` is the driver-owned reference implementation.
- It is corroborated against 10 independently hand-computed charts supplied by
  the operator (held locally — personal data never enters the repo; committed
  test vectors are synthetic, generated at dates that exercise the boundaries:
  pre/post-lichun, pre/post-liqiu, zi-hour, master-number years).
- Discrepancies with the operator sheet are adjudicated by the algorithm and
  reported as errata — a hand-computed sheet is `single-source`; the published
  formula is the ruler.

## The tier experiment this enables

Same spec, same hidden vectors, different models implementing `almanac.py`:
the spec is complete (like t3_parse_duration), the deciding vectors are hidden
(boundary dates), and the grader is exact equality against the reference. Tier
question under test: which rung reproduces calendrical/ephemeris algorithms
from spec — the strongest discriminating-task candidate yet, because
sexagenary + ephemeris math has real edge structure (year/month boundaries,
timezone/UT handling, master-number rules) that satisficing implementations
miss.

## Next: promotion to a graded lens family (TODO — design note, not a claim)

The reference engine is corroborated (34/35 field checks against ten
independently hand-computed charts, held locally; the two mismatches were
errata in the hand computation, adjudicated by the published algorithms and
the Meeus worked example). Before this becomes a graded task family:

- **Synthetic hidden vectors only** — committed vectors are generated at
  constructed datetimes, never from anyone's real birth data. PII never
  enters the repo; the operator sheet remains a local-only corroboration set.
- Vector coverage to author (each targets a judgment/boundary, mirroring the
  task02 edge-family shape):
  - dates within ±48h of lichun (year-pillar rollover)
  - dates within ±24h of each jieqi (month-branch boundary at λ = 315°+30k)
  - UTC-offset handling: same local time, different tz -> different pillars
  - late-zi hour (23:00–23:59) under the declared no-rollover convention
  - sexagenary day anchor: dates exactly 60k days apart must share a pillar
  - western cusp band (<1°): the cusp_warning must fire; sign must match a
    full-precision ephemeris at sign level
  - master-number numerology: component-level 11/22/33 preservation vs the
    reduce-everything school (convention must be cited in the output)
- The task framing to test tiers with: give the solver the DESIGN.md
  conventions + spec, hide the vectors — same visible/hidden daylight as
  t3_parse_duration_004.

Nothing in this section is a benchmark claim; no model has been graded on
almanac tasks yet.
