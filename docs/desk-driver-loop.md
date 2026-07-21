# Desk Driver Loop

The desk driver loop is the goal-to-DAG orchestrator that bridges ordinary-language intent to patch acceptance. It takes a work goal or a serialized plan, decomposes it into a directed acyclic graph of items via the planner, verifies each item's acceptance logic before sealing, runs the DAG through Tier Desk, and records every drift event as it proceeds through repair rounds and escalation.

## What It Does

The loop orchestrates work that Tier Desk will execute, but does not start the desk itself. It handles planning, checkers, DAG admission, watch-and-repair cycles, and patch application.

First, the loop contacts Tier Desk, retrieves a mutation token from the root page, and queues items. It then resumes the scheduler and polls each task to a terminal state: ACCEPTED, REJECTED, ERROR, CANCELLED, or INTERRUPTED. If a run times out before reaching terminal state, the item is marked failed and the loop continues.

For items that hit ACCEPTED, the loop fetches the patch and applies it to the repository with `git apply` when `--apply` is set. It then reruns the exact acceptance command in the authoritative checkout before staging or committing. If that post-apply observation disagrees with the isolated acceptance result, the loop records `post_apply_rejected`, reverses the exact patch, and fails the lineage instead of emitting `applied`. Only a passing authoritative rerun may be committed. For REJECTED or ERROR items with repair rounds remaining, the loop builds a repair brief containing the original task text, the last error, the patch text (if any), and a tail of the run log. It calls the planner again with this brief, expects a single new work item, and re-admits it with the task ID suffixed `-r<n>` and the arm advanced one step along the escalation list.

The loop writes a driftmap (JSONL) recording every state transition, rejection, error, escalation, spec revision, and acceptance. On exit, it prints a summary of event kinds and a verdict: "DRIFTMAP: within spec" if every item was accepted within rounds, or "DRIFTMAP: goal drifted outside spec (<reason>)" otherwise.

## How to Run

### Default: Planner via Codex

```console
python scripts/desk_driver_loop.py \
  --repo C:\path\to\repo \
  --goal "Implement login form validation" \
  --desk http://127.0.0.1:8876
```

The loop invokes `python scripts/planner_codex.py` (or `PLANNER_CMD` override) with a brief file and an output path. The planner runs Codex in a sandboxed ephemeral session, reading the goal or repair brief from stdin, and writes canonical JSON to the output file.

### Precomputed Plan

```console
python scripts/desk_driver_loop.py \
  --repo C:\path\to\repo \
  --plan-file work.json \
  --desk http://127.0.0.1:8876
```

The `--plan-file` argument skips planning; the loop loads `{"work_items": [...]}` and proceeds directly to admission and execution.

## Work Item Contract

A work item is a JSON object with:

- `id`: Unique identifier matching `^[A-Za-z0-9._-]{1,80}$`.
- `title`: Human-readable name.
- `task`: Plain-text instruction for the model.
- `files`: List of repository paths or directory scopes (relative, no `..`, not under `.git`).
- `acceptance`: Shell command that exits 0 if the work is done, run in the repository.
- `depends_on` (optional): List of item IDs that must reach ACCEPTED before this item is queued.
- `arm` (optional): Arm name for initial dispatch; defaults to `--arm`.
- `checker_files` (optional): List of `{path, content}` pairs to write before running acceptance, used to validate that the acceptance command can discriminate truth from falsehood.

The planner may return `{"questions": ["..."]}` instead of work items, signaling ambiguity or missing context. The loop exits 3 and prints the questions.

## Fail-Closed Guards

The loop enforces three guards before admitting any item, each triggering exit code 2 and recording a driftmap event:

**1. ID uniqueness and dependency validity.** Every item ID must be unique and match the format. Every ID in `depends_on` must reference a known item. This prevents cycles and broken references.

**2. Scope consistency.** Every path in `files` must be relative, contain no `..`, and not live under `.git`. Every path in `checker_files` must be outside ALL items' `files` scopes. This prevents graders from modifying what they measure. (A measured false accept: a grader inside a writable scope was deleted by the hands model and a broken patch was accepted.)

**3. Discriminative pre-check.** Before admitting items, the loop writes each item's `checker_files` (UTF-8, newline `\n`), runs the acceptance command (subprocess, `shell=True`, `cwd=repo`, env `PYTHONUTF8=1`), and checks its exit code. If acceptance exits 0 BEFORE any patch is applied, that proves nothing—it means the acceptance cannot distinguish a no-op from real work. The loop records this as `nondiscriminative_acceptance` and exits 2. This guard is measured: without it, broken patches passed acceptance checks because the verifier had already been satisfied by the initial repository state.

## Driftmap Events

The driftmap is an JSONL file (one JSON object per line) recording each transition. Every event includes:

- `ts`: ISO-8601 UTC timestamp.
- `kind`: Event type (see table below).
- `task_id`: Item ID or null.
- `round`: Attempt number (0 for initial, 1+ for repairs).
- `detail`: Human-readable context or error text.

| Kind | Meaning |
|------|---------|
| `planner_questions` | Planner returned ambiguity questions instead of items. |
| `nondiscriminative_acceptance` | Acceptance command exits 0 before any patch, guard failed. |
| `scope_guard_violation` | Path scopes overlap or grader files conflict, guard failed. |
| `accepted` | Run completed with ACCEPTED state. |
| `applied` | Patch was fetched and applied to repository. |
| `post_apply_rejected` | Desk accepted the isolated candidate, but the authoritative checkout failed acceptance after apply; the exact patch was rolled back and no apply commit was made. |
| `rejected` | Run completed with REJECTED state; repair round queued. |
| `error` | Run completed with ERROR state; repair round queued. |
| `escalated` | Item re-admitted with advanced arm (e.g., arm_a). |
| `spec_revision` | Repair item's task text differs from original (planner changed the spec). |
| `instruction_violation` | Run receipt reports non-empty `changes.scope_violations`. |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Every item accepted within rounds. |
| 1 | One or more items not accepted after all repair rounds exhausted. |
| 2 | Fail-closed guard triggered (invalid IDs, scope conflict, nondiscriminative acceptance). |
| 3 | Planner returned questions instead of items. |

## Relation to Other Systems

This loop implements the admission and escalation row described in CHATGPT-DAG-DESK-1 (Sol's utterance-to-bundle spec): planner proposes a DAG, the loop verifies checkers are outside the writable scopes, admits items in dependency order, watches for terminal states, and feeds rejection evidence back for spec revision.

The `--arm` and `--escalate-arms` flags integrate with `pilot_backends.json`. The initial arm defaults to `arm_b`; on each repair round, the arm advances one position along `[initial] + escalate-arms`. For example, with defaults (`--arm arm_b --escalate-arms arm_a`), the escalation sequence is `arm_b → arm_a → arm_a`. This allows cheaper attempts first, escalating to more capable arms only when repair evidence justifies it.

## Summary

The desk driver loop takes a work goal or precomputed plan, verifies its acceptance checkers are sound (by running them before any patch to ensure they discriminate), admits the DAG to Tier Desk ordered by dependencies, polls each task to completion, applies accepted patches, feeds rejection evidence back to the planner for repair rounds, and escalates between arms as work deepens. Every state transition is recorded in a driftmap JSONL file; exit codes distinguish graceful success, incomplete work, ambiguous planning, and fail-closed guard violations. It runs planner_codex.py as a subprocess to decompose goals into work items, and uses only urllib for desk client communication, keeping the tool portable across Windows and Unix environments.
