# `tier run` — daily patch runner

`tier run` turns one scoped repository change into a disposable-worktree run,
executes the operator's immutable acceptance command, and returns a patch plus
hash-bound receipts. The model sees a Git-free packet containing only the
declared `--files` scope; the runner syncs those edits into a hidden full
worktree for acceptance. It never merges and never edits the operator's checkout.
The live packet is created in a fresh OS temporary directory rather than beside
other run receipts, and it is removed before `ACCEPTED` can be emitted.

This is the implementation vehicle registered in
`docs/driver-boundary-pilot.md`. Building and testing it does **not** authorize
the ten-task pilot. The pilot still requires its separately committed backend
manifest, task list, arm schedule, and operator authorization.

## Install

From this repository:

```console
python -m pip install -e .
tier --help
```

The registered command works directly once the target repository contains a
committed `pilot_backends.json`:

```console
tier run --repo C:\path\to\repo \
  --task "Make parse_port reject values above 65535" \
  --files src/net.py \
  --acceptance "python -m pytest tests/test_net.py -q"
```

Optional `--task-id`, `--arm`, `--backend-manifest`, and `--output-dir` flags
support controlled experiments. Without `--task-id`, the runner derives a
stable ID from the task text. Receipts default to the target repository's
common Git directory under `.git/tier-runs/`; disposable worktrees live under
`.git/tier-worktrees/` and are removed before the command returns. An explicit
`--output-dir` may not point into the operator checkout or arbitrary Git internals.

`--acceptance` is an explicitly trusted operator-supplied shell command. Model
output never supplies or changes it.

## Freeze a backend

The manifest and every prompt template must already exist as Git blobs at the
target base commit. The runner reads those exact blobs—not mutable checkout
bytes—so CRLF conversion or an uncommitted edit cannot change the treatment.

Minimal manifest shape:

```json
{
  "schema": "tier-bench/pilot-backends@1",
  "protocol_commit": "<full commit containing protocol v1.3>",
  "isolation": {
    "fresh_session_per_call": true,
    "instruction_files": false,
    "auto_memory": false,
    "conversation_carryover": false
  },
  "tool_versions": {
    "claude_code": "<exact `claude --version` output>",
    "claude_help_sha256": "<sha256 from adapter `_help_surface('claude')`>",
    "tier_claude_adapter": "6"
  },
  "prompt_templates": {
    "hands": {
      "path": ".tier/hands.prompt.txt",
      "sha256": "<sha256 of the committed Git blob>"
    }
  },
  "arms": {
    "arm_b": {
      "model_id": "<exact runtime model id>",
      "effort": "low",
      "surface": "claude-code-subscription",
      "cost_basis": "subscription-derived",
      "account": "<subscription account label>",
      "tier": "cheap",
      "prompt_template": "hands",
      "adapter": {
        "command": [
          "python", "-m", "tier_runner.adapters.claude_code",
          "--arm", "{arm}",
          "--dispatch", "{dispatch_receipt}",
          "--prompt", "{prompt}",
          "--result", "{backend_result}",
          "--worktree", "{worktree}",
          "--model", "<same exact runtime model id>",
          "--effort", "low",
          "--account", "<same account label>",
          "--claude-version", "<same exact version>",
          "--claude-help-sha256", "<same frozen help-surface sha256>",
          "--adapter-version", "6",
          "--cost-basis", "subscription-derived"
        ]
      }
    }
  }
}
```

The template may use `{{TASK}}`, `{{FILES}}`, `{{ACCEPTANCE}}`, and
`{{BASE_COMMIT}}`. Commit the template first, calculate the SHA-256 of its Git
blob, then commit the manifest. `schemas/tier_run_backend_manifest.schema.json`
is the portable shape; runtime checks additionally bind exact Git bytes.

The help-surface digest binds the raw `claude --help` stdout bytes. It must not
be calculated by decoding and re-encoding the text: on Windows, Python's UTF-8
mode can otherwise change the digest without any CLI-byte drift.

The included Claude Code adapter starts one fresh safe-mode, non-persistent
session, explicitly allow-lists only the disposable packet directory for tool
access, pre-approves exact absolute-path `Read`/`Edit` only for the dispatch's declared files under
`dontAsk` (all other tool uses are denied), disables
customizations/MCP/browser integration and shell access, and
records the raw provider JSON, stderr, token usage, and session identity as
receipt artifacts. The runner keeps a local hash-only session registry under the
target repository's common Git directory and rejects reuse across calls. Other
backends implement the same adapter contract: edit only the disposable worktree and write one
`tier-bench/tier-backend-result@1` result containing exactly one complete
`ledger.Call` row.

For the subscription surface, the adapter strips API-key and alternate-provider
environment variables before launching Claude Code, pins the exact CLI version,
and hashes the `--help` surface after proving every required isolation flag is
present. If a process dies while holding `.git/tier-session-registry.lock`, first
confirm no `tier` process is active, then delete only that lock file; never delete
or rewrite `tier-session-registry.jsonl`.

The flag/version preflight establishes that the configured surface exists; it
does not prove the provider's implementation semantics. Before any pilot task is
disclosed, a separately authorized activation canary must confirm that safe mode
does not load user/project memory or instructions, and its receipt must bind the
same CLI version, help hash, adapter version, and manifest hash. Until then the
vehicle may merge, but pilot execution remains unauthorized.

## Receipts and failure behavior

Every run preserves:

- the rendered prompt and pre-call dispatch receipt;
- the backend's raw result and one-row call ledger;
- acceptance stdout/stderr;
- a binary, full-index Git patch;
- the final `ACCEPTED`, `REJECTED`, or `ERROR` receipt.

The acceptance command is a verifier, not an author: if it changes any tracked
or non-ignored candidate byte, the run becomes `ERROR`. The emitted patch is
therefore the exact candidate tree on which acceptance ran. Writes confined to
Git-ignored paths (for example bytecode or test caches) are intentionally outside
this mutation check because they cannot enter the emitted patch.

Recompute all artifact hashes and the dispatch→prompt→ledger→receipt bindings:

```console
tier verify --run-dir C:\path\to\run
```

Missing telemetry, reused sessions, manifest drift, runtime-model drift,
out-of-scope packet edits, instruction-file/symlink injection, mutable
acceptance, no changed files, or failed cleanup cannot produce `ACCEPTED`.
Failed acceptance produces `REJECTED` while preserving the patch and
diagnostics. The original checkout remains untouched.

Apply an accepted patch only after inspection:

```console
git apply --check C:\path\to\run\change.patch
git apply C:\path\to\run\change.patch
```

## Operator-time events

The pilot's primary metric uses a globally non-overlapping, hash-chained event
log:

```console
tier intervention start --log pilot/interventions.jsonl \
  --task-id real-01 --arm arm_c --category clarification
tier intervention stop --log pilot/interventions.jsonl --id <printed-uuid>
tier verify-interventions --log pilot/interventions.jsonl
```

A second start while any intervention is open, a mismatched stop, a reused ID,
an invalid/out-of-order timestamp, a broken hash-chain link, or an unclosed
interval fails validation. `verify-interventions` prints the final head hash;
commit or otherwise seal that head with the pilot evidence so later whole-log
replacement cannot masquerade as append-only history.

“Global” requires one canonical log path for the entire pilot, frozen before task
disclosure and used by every task and arm. Splitting events across multiple
`--log` files violates the protocol and voids every affected task; the CLI's path
option exists for non-pilot use, not for partitioning a pilot ledger.
