# Local coding flight on the RTX 3090 and RTX 4060

The local coding flight is the physical qualification path for using local coding models as bounded Tier Bench implementation workers. It reuses the existing `tier run` referee contract. The model receives a Git-free packet containing only the declared files. Tier Bench retains the hidden acceptance command, disposable worktree, patch custody, receipt verification, and promotion decision.

The first flight compares three Ollama cartridges through the same Claude Code tool surface:

| Arm | Model | Initial role hypothesis |
|---|---|---|
| `arm_a` | `gpt-oss:20b` | low-latency bounded repair baseline |
| `arm_b` | `qwen3-coder:30b` | implementation challenger |
| `arm_c` | `devstral-small-2:24b` | repository navigation and multi-file challenger |

These roles are unmeasured hypotheses. The flight cannot promote a model or alter the router.

## Execution boundary

The Windows launcher starts a dedicated Ollama server on `127.0.0.1:11439`. It selects the RTX 3090 by NVIDIA GPU UUID and starts the server with one loaded model, one parallel request, flash attention, and a `q8_0` KV cache. The RTX 4060 remains outside the server and is monitored for unexpected memory growth. The launcher refuses to reuse a process already listening on the flight port because it cannot establish how that process was started.

The Claude Code adapter exposes only `Read`, `Edit`, `Write`, `Glob`, and `Grep`. It removes cloud credentials, subscription credentials, inherited Claude session identifiers, proxies, Git control variables, and Tier Bench runner variables before launching Claude Code. Bash, MCP servers, browser integration, slash commands, web search, hidden tests, and the operator checkout are absent from the model surface.

Each call is bound to the exact Claude Code version and help surface, Ollama version and endpoint, installed model digest, adapter source hash, prompt hash, backend manifest hash, server-attestation hash, context allocation, and minimum GPU-residency ratio. Calls have a hard wall-clock limit. A timeout kills the Claude Code process tree and produces an error receipt.

## Prerequisites

The host needs Windows PowerShell or PowerShell 7, Python 3.10 or newer, Git, `nvidia-smi`, Ollama 0.13.3 or newer, and Claude Code. The script requires the RTX 3090 to appear in `nvidia-smi`. It will detect one RTX 4060 automatically when present.

Install the checked-out Tier Bench branch in editable mode:

```powershell
cd D:\TierDesk\Projects\tier-bench
python -m pip install -e .
```

Confirm the local tools resolve:

```powershell
python --version
git --version
nvidia-smi -L
ollama --version
claude --version
```

## First physical test

Run the smoke profile from the Tier Bench repository:

```powershell
.\scripts\run-local-coding-flight.ps1 -Profile smoke -PullMissing
```

`-PullMissing` downloads any missing model. Omit it after the model inventory is complete. The launcher stops the dedicated Ollama server after the flight unless `-KeepServer` is supplied.

The smoke profile performs three real model calls. Every model receives the same bounded port-parser defect and is judged by a hidden unit test through `tier run`.

The default context is 32,768 tokens. This is an intentionally conservative first allocation for the 24 GiB worker because the largest cartridge must leave room for KV cache and runtime buffers. After the 32K flight establishes full GPU residency, test the recommended agent context separately:

```powershell
.\scripts\run-local-coding-flight.ps1 `
  -Profile smoke `
  -ContextLength 65536
```

A 64K failure caused by CPU spill is evidence about the physical cartridge envelope. It is not a reason to weaken the residency check.

## Profiles

| Profile | Calls | Tasks | Purpose |
|---|---:|---:|---|
| `smoke` | 3 | 1 per model | establish the complete executable path and physical GPU placement |
| `core` | 9 | 3 per model | compare boundary repair, quoted CSV parsing, and canonical cache identity |
| `adversarial` | 12 | 4 per model | add the escaped character-class residue that previously separated model behavior |

After a clean smoke flight, run:

```powershell
.\scripts\run-local-coding-flight.ps1 -Profile core
.\scripts\run-local-coding-flight.ps1 -Profile adversarial
```

## Pass condition

A flight has `physical_qualification: true` only when every model call produces an `ACCEPTED` receipt, every run passes `tier verify`, every accepted call reports at least the requested context and 95 percent GPU residency, the RTX 3090 gains at least 4096 MiB over its pre-call baseline, the RTX 4060 gains no more than 1536 MiB, and the GPU sampler records no errors.

The pass condition qualifies the local execution path only. It does not establish that all three models are equally useful, that 32K is sufficient for production repositories, or that any model should receive merge authority.

## Evidence output

The default root is:

```text
D:\TierRuns\LocalCoding\
```

The launcher creates a `bootstrap-<timestamp>` directory containing the dedicated-server logs, server attestation, captured command output, and launcher closeout. The Python flight creates a separate `local-coding-<profile>-<timestamp>-<id>` directory containing:

```text
flight-report.json
fixture repository with frozen corpus and backend manifest
gpu-samples.jsonl
runs/<model>/<task>/receipt.json
runs/<model>/<task>/change.patch
runs/<model>/<task>/ledger.jsonl
runs/<model>/<task>/ollama-preflight.json
runs/<model>/<task>/ollama-postflight.json
provider raw output and stderr
```

The printed JSON includes `report_path` and `report_sha256`. The report itself includes its path but cannot contain its own hash without becoming self-referential. The launcher independently hashes the report in `launcher-closeout.json`.

## Failure interpretation

| Evidence | Meaning | Correct response |
|---|---|---|
| missing model | cartridge is not installed on the dedicated server | rerun once with `-PullMissing` |
| Ollama below 0.13.3 | the three-model suite is unsupported | update Ollama before pulling or running |
| existing listener on port 11439 | server launch provenance is unknown | stop that process or choose another `-Port` |
| model digest drift | installed cartridge changed after the manifest was frozen | rerun the flight so the new digest is measured explicitly |
| context below request | Ollama allocated a smaller context | inspect server settings and VRAM pressure |
| residency below 0.95 | material CPU offload occurred | lower context, change cartridge, or reject the route |
| worker memory delta below 4096 MiB | the RTX 3090 was not materially used | inspect UUID selection and server stderr |
| RTX 4060 delta above 1536 MiB | the utility/display GPU was unexpectedly recruited or heavily disturbed | inspect concurrent workloads and server placement |
| telemetry incomplete | Claude Code did not preserve model, session, or usage evidence | treat the call as an infrastructure error |
| `REJECTED` | the model produced a patch that failed hidden acceptance | preserve the patch as capability evidence |
| `ERROR` | transport, attestation, scope, timeout, or receipt integrity failed | repair the execution path before judging model quality |

## Target-repository canary

`tiercode freeze` can write a committed local backend cartridge into another repository while the attested server session remains alive:

```powershell
tiercode freeze `
  --repo D:\Projects\Cloud\BigBirdReturns\some-repo `
  --server-attestation D:\TierRuns\LocalCoding\bootstrap-<timestamp>\ollama-server-attestation.json
```

The generated manifest binds the current server-attestation hash and is therefore session-bound. It is suitable for a controlled target-repository canary while the same dedicated server remains alive. A server restart requires a new freeze. Persistent Monster Wrangler service custody should use a later runtime-attestation indirection rather than committing a new process identity on every restart.

The model remains a candidate implementation worker. Deterministic acceptance, `tier verify`, human review, and existing accepted-action custody remain authoritative.
