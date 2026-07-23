# The chat bridge

Tier Desk has two bounded chat lanes. The preferred **GitHub Chair lane** lets
a GitHub-capable ChatGPT conversation return an open pull request that the Desk
discovers. The original **text-only fallback** remains for chat surfaces with
no tools or filesystem. Neither lane gives the chat model authority to merge,
push from the Desk, widen path scope, decide acceptance, queue work, or execute
validation.

Under the newsroom constitution in `docs/newsroom.md`, both lanes are external
submission intake. A return is evidence. It is not an action task and it cannot
grant itself authority through a marker or plausible repository identity.

## GitHub Chair lane (v1, intake only)

Preregister the exact return contract through the loopback Desk API. The
request requires the normal `X-Tier-Desk-Token` header:

```json
{
  "request_id": "chair-example-1",
  "repo": "BigBirdReturns/tier-bench",
  "base_sha": "<exact 40-character commit SHA>",
  "allowed_paths": ["tier_runner/", "tests/test_desk_chair.py"],
  "acceptance": "python -m pytest -q tests/test_desk_chair.py",
  "auto_validate": false,
  "allow_forks": false
}
```

`auto_validate` must be `false`. Registration rejects `true` until a separate
immutable-head executor exists. The acceptance command is retained as the
preregistered burden for human review; Chair intake does not run it.

`POST /api/chair/requests` returns the stored request and a deterministic Chair
prompt. The prompt binds the request id, exact repository, base SHA, allowed
paths, acceptance command, and Draft-only boundary. The PR body must contain
this exact marker once:

```text
<!-- tier-desk-chair:v1 request_id=<id> base_sha=<40-hex-sha> -->
```

The inbox checks registered repositories every 300 seconds. An operator can
request the same read-only pass with `POST /api/chair/refresh`. Open pull
requests and changed files are paginated to explicit bounds. The inbox records
the exact repository, PR number, base SHA, head repository, head SHA, complete
changed-file set, marker, and return URL.

The first qualifying return consumes the registered request atomically with the
return record and task creation. It creates one approval-gated `DRAFT` and does
not wake the scheduler. Replaying the request in another PR or changing the
accepted PR head does not create a second task. A transient GitHub access or
file-list failure remains retryable instead of being persisted as a terminal
return.

The Draft is a review record for the submission. It is not validation of the
pull request and should not be armed as if it were. Tier Desk has not fetched,
checked out, hashed, or executed the PR head. A future validation flow must
acquire the immutable head into an isolated workspace and create a new trusted
local action task after the operator reviews that custody transition.

The inbox rejects missing, duplicate, or malformed markers; unknown or consumed
requests; wrong repositories or bases; missing head repositories; forks unless
explicitly allowed; empty or incomplete file enumeration; and paths outside the
contract. It does not merge, push, checkout, invoke a model, execute acceptance,
queue work, or wake the scheduler. There is no public webhook or tunnel in v1.

### Credential surfaces are separate

The interactive operator `gh`, ChatGPT GitHub app, Codex GitHub connector,
sandbox child `gh`, and anonymous public REST are separate credential domains.
A sandbox-child `gh auth status` failure is not evidence that the operator or
an app is logged out. The v1 transport tries process-local `gh api`, then falls
back to anonymous public REST for public repositories. Private or authenticated
reads fail closed unless the live Desk process's own transport proves access.
Polling continues for other registered public repositories, and tokens are
never put in arguments, events, or logs.

## Text-only fallback

Any chat surface can still drive the Desk by emitting text. The model never
touches the repository. It asks the mechanical questions that decide whether a
job contract can be written, then either refuses or emits one JSON object for a
human to carry across:

```text
1. ASK -> 2. EMIT -> 3. VALIDATE -> 4. RUN
```

Before emitting a contract, ask:

1. Is there one deterministic command that decides completion and is not a
   model call? Name the exact command.
2. Does it fail on the baseline and pass after the requested change?
3. Can the change be confined to an explicit, bounded set of repository paths?

If any answer is missing, refuse rather than inventing acceptance. Otherwise
emit only this engine-neutral shape:

```json
{
  "schema": "tier-bench/job-contract@1",
  "id": "<optional-slug>",
  "objective": "<bounded outcome>",
  "files": ["<repo-relative path>"],
  "acceptance": "<single deterministic command>",
  "limits": {"max_files_changed": 3, "max_rounds": 2},
  "depends_on": ["<optional task id>"]
}
```

Omit optional fields instead of guessing. Never add `model`, `arm`, `tier`,
`vendor`, or `provider`; the bridge names work, not who performs it.

The operator validates the carried JSON with the stdlib-only checker:

```console
python -B scripts/validate_contract.py contract.json
```

Validated contracts feed `route.py plan --job contract.json --json` and then
`scripts/desk_driver_loop.py`. The downstream discriminative pre-check remains
the final guard that acceptance really fails before work and passes after it;
the chat model's qualifying answers are not trusted as proof.
