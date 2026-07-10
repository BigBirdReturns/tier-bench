# SOL-2 adversarial review — ARC-A capture ledger + ARC-B almanac corpus

Date: 2026-07-10
Reviewer: Codex/OpenAI lineage, repo-aware driver lane
Scope: PR #57 (ARC-A) and PR #59 (ARC-B), as merged on `main`
Disposition: review complete; remediation open; no gated grader or pass rule changed

## Executive result

The committed worked examples remain non-closed and the almanac corpus still has
real grader bite. Clean GitHub CI passes, 40 frozen vectors match the reference
derivation, and the current ARC-A row reports `amortizing, 1 of 4`.

The adversarial pass found two P1 closure holes and four P2 durability defects.
The most important result is executable: ARC-A's validator accepts an
`amortized`/`closed` row after only one of four projected replays, and it also
accepts the same receipt duplicated under two replay rows. Those paths can mint
a false closure even though the prose and ROI calculator say they must not.

## Findings

### P1 — capture closure is not tied to the projected break-even threshold

`scripts/validate_capture_ledger.py:135-158` rejects `amortized` and `closed`
only when `validated_replays == 0`. It never compares the replay count with the
projection computed by `scripts/capture_roi.py`, and it permits any non-null
`break_even_reuse_count` as soon as one replay exists.

Counterexample (run against the committed worked row): set `status` to
`amortized`, `burden.closure_decision` to `closed`, and
`break_even_reuse_count` to 4 while retaining its single replay. Result:

```text
validate_capture(...) -> []
```

This contradicts the schema description and `docs/frontier-capture.md`, both of
which require validated replays to reach the break-even threshold before
closure. A one-replay row can therefore claim that a four-replay projection has
amortized.

Recommended gated fix: share one projection function between validator and ROI;
require `validated_replays >= projected_break_even_replays` for both closed
states; require `break_even_reuse_count` to remain null before that point and to
equal the evidenced threshold when closed.

### P1 — duplicate receipts can manufacture distinct replay count

`scripts/validate_capture_ledger.py:120-132` checks that receipt paths exist and
that list length equals `validated_replays`, but it does not require unique paths,
work-item identities, candidates, or hashes. Duplicating the worked receipt,
setting `validated_replays` to 2, and leaving the row non-closed returns:

```text
validate_capture(...) -> []
```

Repeating that entry four times would satisfy the current structural checks and,
combined with the first finding, can buy closure without four distinct work
items. This directly violates the replay protocol's same-instance prohibition.

Recommended gated fix: make every replay receipt carry a stable `work_item_id`,
candidate hash, grader-output hash, and artifact/packet hash; enforce uniqueness
of work-item and evidence identity across the capture; validate every referenced
hash rather than path existence alone.

### P2 — the capture schema contradicts the committed ledger

`schemas/capture_ledger.schema.json:64-65` declares every `replay_evidence` item
to be a string. The validator and committed row use objects with `path` and
`description`.

```text
schema item type: string
committed ledger item type: dict
```

Thus a standards-based schema validator rejects the committed row, while a
schema-conforming string is rejected by the Python validator. The supposed
portable contract has two mutually exclusive shapes.

Recommended fix: define the object shape in the schema, including the stronger
identity/hash fields required by the preceding finding, and add a real schema
validation test over every committed ledger row.

### P2 — breadth admission trusts declarations instead of proving isolation

`experiments/breadth/breadth_tasks.py:48-63` calls a manifest non-gameable when
both `hidden_files` and `hidden_run_command` are merely truthy. It does not prove
that the declared file exists, that it is absent from the solver packet, or that
the deciding command actually invokes it.

An adversarial manifest declaring `hidden_files=["hidden_tests.py"]` while its
`hidden_run_command` is `python input.py` returns:

```text
is_gameable -> False
```

The three current almanac manifests are correctly wired, so this does not erase
their existing results. It does mean the general breadth-valid admission gate can
admit answer-key theatre under the label "hidden graded."

Recommended gated fix: resolve every hidden path inside the fixture, require it
to exist and stay outside target/visible context, require the hidden command to
consume a declared hidden grader, then export a packet and assert the grader's
name and bytes are absent before admitting the task.

### P2 — all three ARC-B manifests fail the repository contribution gate

`scripts/validate_task.py:57-59` requires task IDs to start with the lowercase
tier prefix. The landed manifests use `almanac_*` IDs. Direct calls return:

```text
almanac_exception_class_001: should start with t2_
almanac_record_binding_001: should start with t3_
almanac_rule_boundary_001: should start with t3_
```

The runtime schema loads them, but the repository's advertised boundary gate
rejects them. CI currently tests the runtime loader and therefore misses the
contract split. On a Windows non-UTF-8 console the gate also crashes while
trying to print its Unicode failure mark, masking the actual diagnostic.

Recommended fix: decide and document one stable ID convention without renaming
already-receipted task IDs; make the gate accept that convention, run it in CI,
and make console output encoding-safe.

### P2 — ARC-B's grader test is not repeatable in a used checkout

`tests/test_almanac_vectors.py:29-31` iterates every fixture entry and calls
`shutil.copy` as though each were a file. Running the graders creates fixture
`__pycache__` directories. A later run then fails with `PermissionError` or
`IsADirectoryError` while copying that directory. Clean CI passes, but the same
test is not idempotent in a normal developer checkout.

Recommended fix: copy only files (or use `copytree` with an explicit
`__pycache__` ignore) and run graders with bytecode generation disabled. Also
add a timeout to the hidden-grader subprocess in `harness/attempt.py:131-136`;
an import-time loop in a candidate currently can park the harness indefinitely.

## Checks and counterexamples

- capture ledger tests: 21/21 pass
- capture ROI tests: 8/8 pass
- committed capture validator: pass, 1 capture + 1 delta
- current ROI: amortizing, 1/4, three remaining
- almanac drift guard: 40/40 vectors match fresh reference derivation
- clean rebased GitHub durability job: pass
- premature one-of-four closure probe: accepted (`[]`) — finding
- duplicate receipt probe: accepted (`[]`) — finding
- false hidden-admission probe: accepted as non-gameable — finding
- task contribution gate: rejects all three almanac IDs — finding
- repeated local almanac suite: fails on generated `__pycache__` directory — finding

## Review burden packet

- requested outcome: independent cross-lineage audit of the landed ARC-A/ARC-B
  machinery and corpus, without modifying gated evidence rules
- claimant: SOL-2 Codex driver review
- authority: merged source, committed receipts, clean CI, and executable
  adversarial counterexamples above
- burden holder: whoever promotes ARC-A amortization or a new task into the
  breadth-valid set
- evidence: the cited files, commands, outputs, and PR #63 review commit
- verifier: rerun the four counterexamples plus the existing capture/almanac tests
- gap: remediation is not applied; ARC-A remains 1/4 and mixed-basis; the
  operator-held 34/35 reference corroboration remains external evidence
- closure_decision: review complete, remediation open
- failure_default: no amortization claim, no duplicated replay credit, and no
  new breadth admission based only on declared hidden fields
