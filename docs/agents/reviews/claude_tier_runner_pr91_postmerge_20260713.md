# Cross-lineage review — `tier_runner` (PR #91), post-merge

Reviewed by: Fable (Claude lane). Requested by: Sol, relayed by operator
("Fable has an exact-head adversarial review request").

**Status note before the findings below:** by the time this review resumed
(after a session gap), PR #91 had already merged (`0bd5110`, exact reviewed
head `9f779d9`), following a full review/fix cycle attributed to a separate
Fable session (per the PR body and `docs/agents/QUEUE.md` TIER-RUNNER row —
one merge-blocking voided-session-freshness finding, fixed, six non-blocking
items also addressed). This review does not re-litigate that closed round.
It independently re-examined the merged head at `9f779d9` and reports one
residual, executable, currently-live finding that the merged fix does not
fully close, plus explicit confirmation of what is now sound.

**Conflict of interest disclosed up front, per standing practice:** this
runner is the vehicle for the driver-boundary pilot that measures both
resident frontier lineages' (Claude's and Sol's) own necessity as drivers.
Neither lineage is a neutral party on whether it works.

## Method

Fetched `9f779d9` (merged head) and diffed it against the pre-merge head this
review had already partly examined (`4c921e3`). Read the full diff in
`tier_runner/core.py`, `tier_runner/adapters/claude_code.py`,
`tier_runner/manifest.py`, `tier_runner/events.py`. Built and ran executable
witnesses against the **real** `claude` CLI (not the fixture backend the test
suite uses) from this exact container, using the adapter's actual flag set,
to check the isolation and session-freshness claims empirically rather than
by reading code alone.

## Residual finding — P1 (verified live on merged main, not silently unsafe)

**The session-freshness root cause is still present in
`tier_runner/adapters/claude_code.py`; the merged registry in `core.py`
catches the resulting reuse and fails closed, but only starting on the
*second* `tier run` invocation in the natural deployment shape, with a
misleading error message.**

- `claude_code.py::_subscription_env` filters `ANTHROPIC_*`, cloud-credential,
  and `TIER_*` env keys before invoking `claude`, but does not strip
  `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_REMOTE_SESSION_ID`,
  `CLAUDE_CODE_CHILD_SESSION`, or `CLAUDECODE`. Confirmed by running the
  actual filter function against this container's real environment: all four
  pass through unchanged.
- The real `claude` binary, even invoked with `--no-session-persistence` and
  every other isolation flag the adapter sets, honors an ambient
  `CLAUDE_CODE_SESSION_ID` and reports *that* value as the call's own
  `session_id` in `--output-format json`, rather than minting a fresh UUID.
  Executable witness (this container, three runs): with the var present,
  `claude --print --safe-mode --no-session-persistence ...` returned
  `session_id` equal to the parent session's ID, verbatim, twice; with the
  var explicitly unset, it returned a genuinely random, different UUID.
- The natural way to drive `tier run` for this pilot is an operator (or a
  coordinating Claude Code session — exactly the shape this whole program
  has used all session) issuing shell commands from within an active Claude
  Code session, which always has `CLAUDE_CODE_SESSION_ID` set in its own
  process environment. `core.py::run_task` builds the adapter's env as
  `env = dict(os.environ)` and passes it straight through; nothing upstream
  of the adapter strips it either.
- The merged `_register_session`/`tier-session-registry.jsonl` mechanism
  (locked, persistent, per-repo, keyed on `sha256(session_id)`) is real and
  correctly rejects a second call reporting an already-seen session hash —
  this is a good, verified backstop against silent evidence contamination.
  But because the root cause reproduces the *same* session_id on every call
  from the same shell, the practical effect is: **the very first `tier run`
  task in a pilot session succeeds (if otherwise accepted); every subsequent
  task from the same shell hard-fails** with `"backend reused a session_id
  from an earlier tier run"` — an error that reads as a backend bug, not as
  "your invoking shell leaked its own session id downward." As shipped, the
  runner cannot complete the ten-task pilot when driven the way this session
  has always been driven, unless the operator manually unsets
  `CLAUDE_CODE_SESSION_ID` (and siblings) before every single invocation —
  which is undocumented in `docs/tier-runner.md`.

**Recommended fix:** have `claude_code.py` (or a shared adapter helper)
explicitly delete `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_REMOTE_SESSION_ID`,
`CLAUDE_CODE_CHILD_SESSION`, `CLAUDECODE`, and any other ambient
session-identity vars from the child environment before invoking `claude`,
so a genuinely fresh session mints every call regardless of the invoking
shell. This turns the existing registry from "detects reuse and blocks the
pilot after task 1" into "prevents reuse, so the registry stays a true
backstop instead of the normal-case outcome." Low-risk, additive change to
`_subscription_env`'s exclusion set; the registry itself needs no change.

## Verified sound (re-confirmed against the merged head)

- **CLAUDE.md/AGENTS.md instruction-file isolation is now doubly defended.**
  `9f779d9` moved the model packet to a fresh `tempfile.mkdtemp` directory
  (`core.py` line ~491) instead of nesting it under the target repo's
  `.git/`, so the packet's ancestor-directory chain no longer passes through
  any repo that has a root `CLAUDE.md`/`AGENTS.md` at all. Independently,
  live-tested `--safe-mode` against a real repo root `CLAUDE.md` containing a
  planted secret token: without `--safe-mode`, the token leaked directly into
  model context on the first turn (no tool use); with `--safe-mode` (the flag
  the adapter actually sets), the model correctly reported no such
  instruction. Both defenses are independently sufficient; together this
  vector is closed.
- Frozen-manifest/template authority (`_committed_blob`, git-blob-only
  reads) genuinely prevents mutable-checkout substitution.
- Scope enforcement (`_normalize_scope`, `_in_scope`, `_sync_packet`
  violation detection, `.git` exclusion, symlink rejection) is real and
  fail-closed.
- `verify_run`'s tamper detection independently re-hashes every artifact and
  the dispatch→prompt→ledger→receipt binding chain; confirmed via the
  existing patch-tamper test and by re-reading the verification logic.
- The acceptance command is genuinely operator-only; nothing in the model
  packet or backend result can author or alter it.
- `_validate_call`'s per-field binding checks against the frozen manifest
  (model/effort/account/tier/phase/every `extra.*` key, non-negative-number
  and ISO-8601-with-timezone checks added in this round) are real.

## Disposition

Not a merge blocker (already merged) and not a silent-corruption risk (the
registry fails loud). It is a real, reproducible gap between the isolation
contract the manifest schema requires (`fresh_session_per_call: true`) and
what the shipped adapter delivers, with a concrete, low-effort fix. Flagging
as a fast-follow rather than reopening the closed TIER-RUNNER queue row.
