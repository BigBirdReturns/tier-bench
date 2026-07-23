# Monster Wrangler side-by-side — PR #118 vs PR #119 (2026-07-19)

Two independent desk implementations, two lineages, same target files —
at most one merges as-is. Reviewed by two parallel read-only scouts against
a rubric drawn from the frozen kernel-contract cards (PR #116). Claude-lane
adjudication; scout reports are the evidence, this doc is the synthesis.

## Verdict table

| dimension | #118 `agent/monster-wrangler-desk` | #119 `codex/monster-wrangler-v1` |
|---|---|---|
| Closure authority | **PASS** — state from `receipt.state`, gated through `tier_runner.cli verify`; nonzero/not-ok → forced `ERROR`; exit codes powerless | **PASS** — same referee-gated pattern; missing receipt → `ERROR` |
| Receipt discipline | PASS — consumes canonical receipts; adds only a strict INPUT envelope (`tier-bench/tier-run-envelope@1`) | PASS — re-runs `tier verify`, stores canonical receipt; control state in separate DESK_SCHEMA store |
| Credential custody | PASS — loopback bearer token only (secrets.token_urlsafe, constant-time compare); no key transit | PASS — plain env passthrough to the sealed CLI; no credential handling |
| Tank/quota honesty | PASS, modest — observed-cost daily limits, honest by omission | **PASS, rich** — fail-closed staleness (`snapshot_max_age_seconds`, reset-after-snapshot → blocked), `capability_basis`/`quota_basis` validated per route, tested |
| Evidence-boundary | PASS — only `cli.py` modified, additive | PASS — only `cli.py` modified, additive |
| Scope honesty | PASS — 16 files, +2719/−32, exactly as described | Mostly — accurate claims doc, but its own "transport state, do not merge" self-diagnosis is STALE (archive deleted at `0c13fe9`, real source at HEAD) |
| Test honesty | WEAKEST — ~20 real tests but closure path (receipt→verify→override) never exercised end-to-end (FakeExecutor) | 15 real witnesses incl. event-chain tamper detection; same FakeExecutor gap on the live subprocess path |
| Transport/merge | PASS — complete importable source | ONE BLOCKER — dead `pull_request`-triggered `monster-wrangler-assemble.yml` with `permissions: contents: write` referencing a deleted assembler: supply-chain smell, delete before merge |

## Headline finding

**Both engines independently implemented the constitutional invariant
correctly**: neither closes work on process exit or model self-claim; both
derive state from the receipt and gate it through the referee. Two lineages,
zero coordination, same bright line — the strongest evidence yet that the
frozen contracts describe implemented reality, not aspiration.

## Stale-intel corrections (recorded per bytes-over-summaries)

1. Cold-desk report claimed #118 was "162 files, over-reported" — false;
   16 files, description matches bytes exactly.
2. Cold-desk report (and #119's own claims doc) said #119 is transfer
   machinery, "must not merge in this transport state" — stale; the source
   tree landed at HEAD, archive deleted.

## Recommendation

**#119 as base** (its tank snapshots, basis labels, and hash-chained event
ledger are the policy-kernel card already implemented), with three merge
gates: (1) delete the dead write-scoped `assemble.yml`; (2) one shared
end-to-end closure test — both builds share the FakeExecutor gap, and a
regression to exit-code-trust would pass both CIs today; (3) port #118's two
best organs: heartbeat-owned worker lifetime (child self-terminates on stale
heartbeat — would have prevented the amortization_v1 orphan) and the
fail-closed CLI envelope with flag mutual-exclusion. #118's remaining ideas
are filed here as review findings, not discarded; its closure guard stands
as independently-confirmed prior art.

Sequencing stays operator-gated: merge order vs the kernel-contract cards
(#116) and the smoke is the operator's call; this review creates no
authority.

---

## Cross-engine disposition addendum (2026-07-19, post-Sol audit)

Sol's independent audit (`sol_wrangler_audit_20260719.md`) REFUTES this
review's aggregate recommendation. Accepted at the desk:

1. **Event-chain finding (new, both scouts missed it):** #119's sealed
   head/count metadata lives in the same mutable SQLite as the chain;
   `verify_event_chain()` is exposed but not enforced at scheduler startup or
   tick — detectable corruption does not stop dispatch. GATE 4 (Sol's):
   externally anchor the chain head and fail closed on verification at
   admission.
2. **Conformance overclaim:** #119's tank/basis machinery does not conform to
   the frozen policy card as this review implied.
3. **Disposition change:** "#119 as base" is downgraded from recommendation
   to HYPOTHESIS. Operative verdict: CHANGES_REQUESTED_BEFORE_EITHER_MERGE;
   the independently-converged referee-gated closure remains the valuable
   cross-lineage evidence; #118's heartbeat-supervised modular surface is
   undervalued above.

The resident desk's original text is preserved unedited above, per
strike-through-not-delete law.
