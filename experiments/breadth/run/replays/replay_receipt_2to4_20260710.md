# Replays 2–4 — distinct task02-class work items, floor + scaffold packet (2026-07-10)

Three NEW work shapes minted from the frozen edge family
(`run/task02_edge_family.md`), each embedding the backslash-in-class knot
unannounced. Hidden vectors derived MECHANICALLY from the settled task02
reference oracle (`_ref`); every grade run by the driver. Key material verified
both directions before any trial: reference implementation 100% on all three;
a naive escape-in-class implementation fails all three (11/14, 14/17, 6/10).
Candidates, specs, vectors, and the grader are committed alongside; re-verify:
`python run/replays/hidden_grade.py run/replays/<item> <candidate>`.

| Item | Trials (hidden) | Knot vectors | Verdict |
|---|---|---|---|
| replay02_charclass_filter | 13/14 ×3 | all passed, 3/3 trials | **VALIDATED** (adjudicated) |
| replay03_validate_patterns | 17/17 ×3 | all passed, 3/3 trials | **VALIDATED** |
| replay04_count_matches | 6/10, 10/10, 9/10 | trial0 knot REGRESSED | **NOT validated** (partial) |

## Adjudications (driver, on the record)

- **replay02 `[!]` vector**: every trial missed only `[!]` (expected ValueError).
  The replay02 spec as authored never states that `!` consumes the negation slot
  — the vector is spec-underdetermined, an AUTHORING artifact, not a capability
  miss. All knot-bearing vectors (`[\]`, `[\*]`, `[a\-z]`) passed in all trials.
  Verdict on determined vectors: 13/13 ×3.
- **replay04 trial0**: the knot bit THROUGH the packet — all four misses are the
  backslash-in-class family, scoring identical to the naive implementation.
  With trial2's separate `[]a]*` first-position miss, replay04 is 1/3 clean and
  does NOT count. Finding: packet transfer degrades when the knot is embedded in
  an aggregate-count shape — the commitment can be held and still dropped at
  application depth. This is the first measured LIMIT of the scaffold artifact.

## Count

validated_replays: 1 (crossing event) + 2 (replay02, replay03) = **3 of projected 4**.
replay04 stays open as the partial; its failure receipts are part of the corpus.
