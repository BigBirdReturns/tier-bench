# Cross-engine protocol — one project, independent instruments

Claude and Codex map the same project from different model lineages. They share
the repository, deterministic graders and evidence contracts. They do **not**
share an identity, hidden context, or an unexamined conclusion.

This file is canonical. `AGENTS.md`, `CLAUDE.md` and engine-specific handoffs
point here instead of re-explaining the relationship in chat.

## The unit of independence

Every cross-engine record names:

- `engine_id`, `model`, provider `lineage`, and execution `surface`;
- a shared `pair_id`, source commit, task manifests and manifest hashes;
- whether the engine saw peer conclusions before its candidate was sealed;
- the raw response path, thread/run ID and content hash;
- the coordinator and deterministic grader that supplied the verdict.

Two rows are peers only when their source commit, task set, manifests, K, and
routing ladder match and their engine IDs and provider lineages differ. A model
name in prose is not pairing evidence.

## What “run it twice” means by work class

| Work class | First engine | Independent engine | Combined evidence |
|---|---|---|---|
| Code/build arc | Implements and tests | Adversarially reviews the sealed diff without the author's conclusion first | Review agreement/disagreement; do not duplicate code merely to count two |
| Hidden-graded benchmark | Solves a visible packet | Solves the identical visible packet independently | Coordinator grades both with the same hidden grader, then compares |
| Disposition/control probe | Answers cold | Re-administers cold or independently grades preserved verbatims | Separate contributor and grader-lineage flags clear independently |
| Capture/replay claim | Produces capture receipt | Audits cost/evidence and performs a distinct replay where authorized | Capture closes only under its replay/ROI burden, never by reviewer vote |
| Grader/oracle authoring | Authors frozen oracle | Reviews semantics before activation | Grader remains gated; neither subject edits it during a run |

ARC-A therefore needs a Codex adversarial audit and distinct replays, not a
second copy of the validator. ARC-B needs an independent review plus Codex solver
receipts over its frozen corpus, not a rewritten corpus. ARC-C compares the
resulting route/escalation/spend/abstention evidence.

## Sealed execution

1. Freeze the source commit and task manifests.
2. Run `scripts/export_solver_packet.py` once per task. The solver directory
   contains visible fixture files and `PROMPT.md`; the coordinator receipt stays
   outside the solver directory and names withheld grader hashes.
3. Start each engine in a fresh session scoped only to that solver directory.
   Do not provide peer results, the coordinator receipt, the original repository,
   reference keys, or hidden files.
4. Preserve the raw response and engine thread/run ID. Seal the candidate hash.
5. The coordinator copies the manifest-declared hidden grader into a grading
   copy, runs it, and independently repeats the grade. The engine narration is
   not used. `scripts/grade_solver_packet.py` performs this step and emits the
   receipt; it refuses packet drift and existing output directories.
6. Append one per-engine trial receipt. Recompute the Residue Broker decision and
   validate the complete run. `scripts/ingest_engine_trial.py` copies the sealed
   artifacts and performs this update atomically.
7. Only after both runs are sealed may `scripts/compare_engine_runs.py` expose
   agreements, disagreements, cost deltas and routing deltas.

## Durable failure defaults

- Missing peer run: `unpaired`, not corroborated.
- Peer saw the other conclusion before sealing: `contaminated`, not independent.
- Different commit, manifests, ladder or K: `incomparable`.
- Missing raw response, grader output or hash: `partial`.
- Solver equals grader: reject the verdict.
- Hidden file in solver packet: reject the run.
- Mixed K-window: collect another same-rung trial; never escalate.
- No isolated execution surface: remain unmeasured. Do not substitute a chat
  paraphrase or the coordinator's own answer.

## Required cross-lineage queue

The durable queue is evidence-shaped, not “let both models edit everything”:

1. Non-Anthropic grading of preserved control-set verbatims.
2. Codex adversarial review of the ARC-A capture ledger and ARC-B almanac corpus.
3. Independent Codex floor run over the ARC-B packets.
4. Matching Claude floor run over the same packet hashes.
5. ARC-C paired comparison and only then any justified residual escalation.
