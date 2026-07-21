# The chat bridge

Tier Desk has two bounded chat lanes. The preferred **GitHub Chair lane** lets
a GitHub-capable ChatGPT conversation return an open pull request that the Desk
discovers. The original **text-only fallback** remains for chat surfaces with
no tools or filesystem. Neither lane gives the chat model authority to merge,
push from the Desk, widen path scope, or decide acceptance.

## GitHub Chair lane (v1)

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

`POST /api/chair/requests` returns the stored request and a deterministic Chair
prompt. The prompt binds the request id, exact repository, base SHA, allowed
paths, acceptance command, and auto-validation choice. The PR body must contain
this exact marker once:

```text
<!-- tier-desk-chair:v1 request_id=<id> base_sha=<40-hex-sha> -->
```

The inbox checks registered repositories every 300 seconds. An operator can
request the same read-only pass with `POST /api/chair/refresh`. A new return is
bound to `(repo, PR number, head SHA, base SHA)` and deduplicated by
`(repo, PR number, head SHA)`, so a changed head is a new return. Exact matches
append a Desk event and create a visible task. The default is `DRAFT` and does
not wake scheduling. An explicitly preregistered `auto_validate` request enters
the queue only after the inbox verifies a single safe acceptance command and a
complete changed-file list within the registered paths.

The inbox rejects missing, duplicate, or malformed markers; unknown requests;
wrong repositories or bases; forks unless explicitly allowed; incomplete file
lists; and paths outside the contract. It does not merge, push, checkout, or
execute PR code. There is no public webhook or tunnel in v1.

### Credential surfaces are separate

The interactive operator `gh`, ChatGPT GitHub app, Codex GitHub connector,
sandbox child `gh`, and anonymous public REST are separate credential domains.
A sandbox-child `gh auth status` failure is not evidence that the operator or
an app is logged out. The v1 transport tries process-local `gh api`, then falls
back to anonymous public REST for public repositories. Private/authenticated
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
