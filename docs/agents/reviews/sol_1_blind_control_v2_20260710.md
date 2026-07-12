# SOL-1 blind-control v2 external grade

Status: one complete external grading run is sealed and merged additively. This
record reports agreement with the existing baseline; it does not assign an
aggregate benchmark verdict.

## Binding and custody

- packet repository commit:
  `6771868bbdff156382796190271404fd72576936`
- packet SHA-256:
  `98997bf9d9e43d85052e6ff0107476735cf35aeccfd7c4509dc4762ff48d7b11`
- packet source commit:
  `623cb1ed1672e04fecba48f04294067f78eaf02e`
- grade run ID:
  `sol-1-v2-019f4d56-c26f-7ec0-9d3e-67819c2270ec`
- Codex desktop thread ID:
  `019f4d56-c26f-7ec0-9d3e-67819c2270ec`
- completed turn ID:
  `019f4d56-dfb9-7913-896f-345bad70e645`
- raw grade artifact SHA-256:
  `da69f26df5d9bcf55391b7a3deaf00505125aafd00bd6a961aed4eab016af04c`

The operator identified the fresh task as SOL-1 using `gpt-5.6-sol`. The desktop
thread record does not independently expose a model field, so that model name
is operator-attested rather than inferred from the answer. The recorded trace
shows only reads of the pinned private repository commit and
`control_packet.json`; it contains no Tier Bench checkout read, peer conclusion,
private key access or baseline-score access.

The returned JSON is preserved unchanged as `grades.raw.json` beside the run
manifest and session record. The private key was used only by the repo-aware
coordinator after the instrument turn completed.

## Validation

All coordinator checks passed:

1. valid JSON array;
2. exactly 80 items;
3. every object has exactly `id`, `score`, and `rationale`;
4. all IDs are unique;
5. the ID set exactly matches the v2 private key;
6. every score is an integer in `{0, 1, 2}`; and
7. every rationale is a non-empty string.

`scripts/merge_external_grades.py` then wrote eight additive regraded control
files and preserved all original baseline scores.

## Agreement with the existing baseline

| Comparison | Count | Rate |
|---|---:|---:|
| Exact | 48 | 60.0% |
| Off by 1 | 32 | 40.0% |
| Off by 2 | 0 | 0.0% |
| Total | 80 | 100.0% |

### By administration

| Administration | n | Exact | Off by 1 | Off by 2 |
|---|---:|---:|---:|---:|
| `fable-5__high__bigbird__20260707` | 10 | 6 | 4 | 0 |
| `fable-5__high__bigbird__20260707__b` | 10 | 6 | 4 | 0 |
| `haiku__high__bigbird__20260707` | 10 | 6 | 4 | 0 |
| `haiku__low__bigbird__20260707` | 10 | 5 | 5 | 0 |
| `opus__high__bigbird__20260707` | 10 | 9 | 1 | 0 |
| `opus__low__bigbird__20260707` | 10 | 7 | 3 | 0 |
| `sonnet__high__bigbird__20260707` | 10 | 4 | 6 | 0 |
| `sonnet__low__bigbird__20260707` | 10 | 5 | 5 | 0 |

### By probe

| Probe | n | Exact | Off by 1 | Off by 2 |
|---|---:|---:|---:|---:|
| P1 | 8 | 4 | 4 | 0 |
| P2 | 8 | 8 | 0 | 0 |
| P3 | 8 | 4 | 4 | 0 |
| P4 | 8 | 5 | 3 | 0 |
| P5 | 8 | 8 | 0 | 0 |
| P6 | 8 | 8 | 0 | 0 |
| P7 | 8 | 2 | 6 | 0 |
| P8 | 8 | 2 | 6 | 0 |
| P9 | 8 | 5 | 3 | 0 |
| P10 | 8 | 2 | 6 | 0 |

The disagreement concentration is descriptive only. It does not authorize a
rubric, baseline or pass-rule change.

## Reported second attempt

The operator reported that SOL-1 finished twice. At sealing time, the Codex
desktop task index exposed one completed blind-grader thread and one completed
turn. No second thread ID or second JSON artifact was available. Therefore this
record admits one run only; it does not duplicate the first artifact or invent a
second receipt. A later distinct artifact can be assigned its own grade run ID.
