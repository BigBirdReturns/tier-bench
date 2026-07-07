# Task 07 — the unverifiable residue: is taste flat across tiers?

Everything checkable turned out rentable (tasks 01–06). The residue is
**unverifiable judgment** — quality with no oracle. This task probes it directly.

**The task** (pure taste, no ground truth): write the first sentence of a novel
whose premise is "a woman discovers her reflection has started acting a
half-second late." Each tier (haiku, sonnet, opus) produced 4 candidates → a pool
of 12, anonymized and shuffled.

**The measurement** — with no oracle, the only honest signal is **inter-tier
agreement**. Each tier then ranks all 12 candidates *blind* (authorship hidden).
Two numbers fall out:

1. **Is taste flat across tiers?** — the rank-correlation between haiku's, sonnet's,
   and opus's blind rankings.
   - **High agreement** → taste is *shared*: a cheap model selects as well as the
     frontier, so the unverifiable residue is ALSO rentable (generate cheap,
     select cheap, trust the pick because all tiers agree what's good). This would
     mirror the origin finding — disposition was flat on *effort*; taste flat on
     *tier* would close the loop.
   - **Low agreement** → taste is tier-specific, AND unadjudicable (no ground truth
     to say who is right). That disagreement *is* the irreducible residue.

2. **Generation vs selection.** By consensus rank of the pooled candidates, whose
   *writing* wins? If haiku's lines place as high as opus's in the blind pool,
   there is no generation gap on taste — only a possible selection gap. If haiku's
   lines rank lowest even by its own blind judgment, the gap is in generation.

**Honesty seams.** "Quality" here is *panel preference*, never truth — labeled as
such, same doctrine as the rest of the repo. Judges rank blind, sources hidden,
order shuffled. A tier judging a pool that includes its own (anonymized) lines is
the point (self-preference, if any, becomes visible as a tier that ranks its own
work up). Tokens/cost captured like every other task — all the buffalo.

Files: `gen/<tier>.txt` (4 lines each), `pool.txt` (anonymized shuffled 12),
`judge/<tier>.txt` (each tier's blind ranking), `analysis.*` (agreement + winners).
