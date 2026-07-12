# Codex ARC-C floor-run seal — 2026-07-10

> **SUPERSEDED 2026-07-12 — source-custody review.** The validator originally
> compared manifest hashes to the current checkout instead of the declared
> source commit. Four observations predated the first commit containing their
> exact source bytes, and two later observations depended on an excluded
> predecessor. This historical seal is retained as provenance but no longer
> authorizes the nine-trial/three-cell claim. The active run retains only the
> independently source-bound rule-boundary 3/3 observations; see
> `sol_arc_c_source_custody_correction_20260712.md`.

Status: the Codex engine run is sealed. The cross-engine ARC-C claim remains
partial because no compatible sealed Claude run has been ingested or compared.

## Contract

- run: `arc_c_almanac_v1`
- engine: `codex_gpt_5_6_sol` / OpenAI lineage
- normalized rung: `floor`
- binding: `gpt-5.6-sol`, effort `low`, Codex subscription surface
- source administration: `e416462fdf36c711faf06717212d8de19cd07216`
- K: 3
- decisive observations: 9
- escalations: 0

The task manifests and graders are bound by their receipt hashes. The original
Windows administration retained CRLF fixture bytes that were later committed
byte-for-byte in PR #63; the continuation reconstructed that administration by
matching the manifest, hidden-grader, prompt and solver-packet hashes rather than
assuming the old commit blob alone reproduced the checkout bytes.

## Sealed result

| Task | Floor result | Broker action |
|---|---:|---|
| `almanac_exception_class_001` | 3/3 | seal at floor |
| `almanac_record_binding_001` | 3/3 | seal at floor |
| `almanac_rule_boundary_001` | 3/3 | seal at floor |

Every candidate was sealed before grading. The coordinator injected the
manifest-declared hidden grader and ran it twice; all 18 hidden-grader executions
returned zero and each pair was deterministic. No 0/K wall existed, so the
broker never authorized a higher effort rung.

## Fresh thread identities added in this continuation

| Task / trial | Thread ID | Verdict |
|---|---|---|
| record-binding / 2 | `019f4d6f-9568-7293-96b6-ab00644cc747` | pass |
| record-binding / 3 | `019f4d72-4a65-7063-b4a0-f35ea32a82c3` | pass |
| rule-boundary / 1 | `019f4d74-d6ff-7683-9804-b667539ef265` | pass |
| rule-boundary / 2 | `019f4d76-beb7-7ed0-95d9-e72218b65039` | pass |
| rule-boundary / 3 | `019f4d78-59e9-7e62-ae06-b87d3e88fbce` | pass |

The Codex desktop thread API exposed task/turn identity and final text but not
provider-raw token events. Each new receipt therefore marks
`usage_available: false`; its zero token fields are schema sentinels, not usage
claims. The committed JSONL is explicitly labeled
`coordinator-derived-codex-app-thread-snapshot`. Raw response text remains
separate and hash-bound.

## Excluded transport observation

Thread `019f4d6e-a3b5-7ad1-89d7-be4201c526e4` received mojibake Chinese
characters through the first app handoff. It was detected before grading,
excluded from the broker, and preserved under
`data/orchestration/excluded/arc_c_almanac_v1/`. It is not a trial, failure,
wall, or escalation predicate.

## Remaining boundary

Claude's reported almanac summaries are not compatible orchestration receipts:
they do not supply the matching sealed packet, candidate, raw response, grader
output and provenance contract required by `scripts/compare_engine_runs.py`.
They remain separate observations. PR #63 must stay draft/partial until a
compatible peer run is sealed and the comparator admits it.
