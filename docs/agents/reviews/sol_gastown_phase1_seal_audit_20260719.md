<!-- Authored by gpt-5.6-sol via codex exec (read-only sandbox, --output-last-message file transport, no truncation). Bytes committed verbatim below by the Claude desk with attribution. Dispatch: SOL-SEAL-AUDIT-1, 2026-07-19. -->

# GASTOWN-SMOKE-1 Phase-1 Seal Audit — 2026-07-19

## 1. Missed public-boundary paths

### Finding: the search was not exhaustive

The log does not prove a working daemon-free route, but it exposes multiple legitimate public-boundary routes that the executing hand did not try. Therefore the categorical `DAEMON-REQUIRED` conclusion is not established.

Most importantly, the CLI explicitly documents adoption:

> “Use `--adopt` to register an existing directory instead of creating new”  
> “Adds entry to mayor/rigs.json”  
> `gt rig add existing_rig --adopt`  
> `--force ... register even if git remote cannot be detected`  
> — `transport_log.md:590–614`

The failed ordinary add then recommends that exact route:

> “To register an already-assembled rig directory, use:  
> `gt rig add myrig --adopt`”  
> — `transport_log.md:774–795`

The hand never invoked it. It also missed the documented public command that prepares an existing repository as a rig:

> “Initialize the current directory for use as a Gas Town rig.”  
> “This creates the standard agent directories...”  
> — `transport_log.md:326–340`

Thus `gt init` followed by `gt rig add ... --adopt` was an obvious public-CLI sequence to test before inferring that adoption required manually fabricating internal structures.

Two further public-boundary routes remained untested:

- `gt install --shell` explicitly configures `GT_TOWN_ROOT` and `GT_RIG` (`transport_log.md:305–324`), but neither environment-variable resolution path was probed.
- `gt dolt --help` exposes `init` and `init-rig` as public verbs (`transport_log.md:836–855`), but neither was examined for a serverless initialization route.

### `gt sling` was not shown to require a rig in every mode

The help surface says sling handles existing town agents, including the mayor:

> “Existing agents (mayor, crew, witness, refinery)”  
> `gt sling gt-abc mayor`  
> `gt sling mol-release mayor/`  
> — `transport_log.md:14–18, 41, 68–70`

It also exposes `--agent tiercap` and `--no-boot` (`transport_log.md:99–115`). Yet the only attempted sling used `self` as the bead/formula:

> `gt sling --dry-run --agent tiercap self`  
> `Error: 'self' is not a valid bead or formula`  
> — `transport_log.md:900–939`

That failure occurs during bead/formula validation, before target or rig resolution. It cannot support the later assertion that sling “needs a rig.”

`gt assign` genuinely requires a crew member inside a rig (`transport_log.md:128–160`), and `gt formula run` explicitly resolves a target rig (`transport_log.md:380–423, 884–898`). Those two paths were reasonably characterized. Sling was not.

**Answer:** yes, relevant public-boundary routes were left untried. Their success remains unmeasured, but that alone defeats the seal’s exhaustive claim.

## 2. Rejection of `gt rig add --adopt`

### Finding: rejection was incorrect

`--adopt` is a documented flag on the public `gt` CLI. Exercising it does not couple the experiment to internal Go structures.

The hand’s rationale was:

> “it would require hand-building the internal rig directory layout ... which is exactly the ‘No coupling to Gas Town internal Go structures’ ... forbids.”  
> — `transport_log.md:1059–1062`

That rationale conflicts with the captured CLI surface:

- `gt init` publicly creates the standard rig directories (`transport_log.md:326–340`).
- `gt rig add --adopt` publicly reads an existing configuration and registers it (`transport_log.md:590–614`).
- The ordinary add error itself directs the operator to `--adopt` (`transport_log.md:774–795`).

The seam prohibits direct dependence on internal implementation structures. It does not prohibit composing documented CLI commands that create and consume those structures.

Whether adoption would ultimately contact Dolt is unknown because it was never run. The correct static disposition was therefore `ADOPT-PATH-UNTESTED`, not `DAEMON-REQUIRED`.

## 3. Is `gt dolt start` a forbidden daemon?

### Strongest case that it is not the prohibited kind of daemon

`gt dolt start` is narrower than `gt up`: it starts only the local SQL data service, without bringing up tmux, witness, refinery, or agent hosting. It has an explicit matching stop command and could be treated as a session-owned fixture with start/status/stop receipts. The frozen public seam permits `gt` CLI operations, and “never run `gt up`” does not literally prohibit `gt dolt start`.

Moreover, the frozen task card itself does not name a daemon requirement as a predetermined no-go class. The explicit rule appears in the transport log:

> “never run `gt up`. Any tmux/daemon prompt = record DAEMON-REQUIRED and stop.”  
> — `transport_log.md:3–7`

That authority distinction should have been preserved.

### Judgment

The process nevertheless is a daemon under the ordinary and operational meaning:

> “Start the Dolt SQL server in the background.”  
> “The server will run until stopped with `gt dolt stop`.”  
> — `transport_log.md:864–873`

The parent help further describes a multi-client server on port 3307 (`transport_log.md:819–830`). Under the explicit transport-log rule that any daemon prompt terminates the attempt, refusing to start it was sound.

What is unsound is using that refusal to prove that no allowed daemon-free public path exists when adoption, environment resolution, HQ-target sling, and initialization verbs remained untested.

## 4. Sentence-level audit of `PHASE1_TRANSPORT_VERDICT.md`

| Seal claim | Audit disposition |
|---|---|
| Phase 1 did not pass; no capture invocation was reached. | Supported. The logged sling attempt failed before launch (`transport_log.md:900–939`). |
| Phase 2 was forbidden and the dispatch budget remained unspent. | Consistent with the command inventory, which contains no model invocation. The log alone cannot prove that nothing happened outside the inventory. |
| “gt v1.2.1 ... cannot reach its agent-launch surface without a persistent daemon.” | Overclaim. Only ordinary clone-mode `rig add` reached the Dolt error; adoption and other public routes were not tried. |
| The dependency is load-bearing beneath all rig registration. | Overclaim. The evidence establishes this only for `gt rig add <name> file:///...`, not `--adopt`. |
| Every named launch path requires a registered rig. | Partly supported for assign and formula; unsupported for sling, whose help documents HQ/mayor targets and whose only probe failed on an invalid bead/formula before target resolution. |
| “The only public-boundary way to register a rig, `gt rig add`, hard-fails” without Dolt. | Misleading and materially incomplete. The same public command exposes a distinct `--adopt` mode that was never executed. |
| The ordinary local-URL rig add failed because Dolt was not running. | Supported verbatim: “Dolt server is not running ... start it with `gt up` or `gt dolt start`” (`transport_log.md:797–817`). |
| Both suggested start commands involve persistent daemons. | Supported for `gt dolt start` by its help bytes; `gt up` was not invoked. |
| Beads operated with embedded Dolt. | Supported by the phase-0 receipt, not independently reproduced in the transport log. |
| This is an architecture choice rather than a platform limitation. | Plausible inference, presented too categorically. The evidence proves that `bd` can use embedded Dolt on this machine and ordinary `gt rig add` demands the server; it does not isolate every possible implementation or configuration cause. |
| `gt install --no-beads` bootstrapped HQ without starting a daemon. | Supported by the successful output (`transport_log.md:671–695`). |
| Custom agent `tiercap` was registered and read back without a dangerous-permissions flag. | Supported (`transport_log.md:723–752, 1019–1025`). |
| Every built-in agent preset carries a yolo/dangerous-permissions flag. | False. The captured inventory shows bare `opencode`, plus `omp --hook ...` and `pi -e ...`; those bytes are not yolo flags (`transport_log.md:999–1017`). |
| The command inventory contains 32 `gt` invocations. | False. The file contains 34 `## Command: gt ...` records, spanning `transport_log.md:11–941`. |
| `gt up` was never invoked; `gt dolt start` was only queried with `--help`. | Supported by the recorded command headings. |
| No Dolt/gt process was running at adjudication. | Not evidenced by captured command output. No process-list command or output appears in the log. |
| No capture JSON existed anywhere in the workspace. | Attested, not independently evidenced. The log says “grep-verified” (`transport_log.md:1071–1073`) but does not preserve the grep command or output. |
| The stray settings directory was removed and the worktree was clean. | Attested, not independently evidenced. No `git status`, filesystem listing, or removal output is preserved (`transport_log.md:1084–1089`). |
| Hand receipt: sonnet, 62 turns, 13.7 minutes, $2.64, matching verbatim. | Unsupported by the supplied log; no hand receipt or telemetry record appears in it. |
| `transport_log.md` is 48,370 bytes. | Correct. “Vendored verbatim” cannot be established without the source artifact against which to compare it. |
| No retry or compensating platform work is authorized. | Correct governance disposition under the frozen task card. |
| `--adopt` was correctly rejected as internal-structure coupling. | False for the reasons in Question 2. |
| Contract-crate promotion remains an operator decision. | A prudent governance interpretation, not a fact established by the transport log. |

## Additional defects

1. The frozen seam names `settings/agents.json`, while the observed CLI wrote `settings/config.json`:

   > “TRANSPORT FACT: this confirms `settings/config.json` ... is part of gt’s real public-boundary write path”  
   > — `transport_log.md:708–719`

   Because the write occurred through `gt config agent set`, it remains within the CLI boundary, but this path drift should have been recorded explicitly against the frozen external belief.

2. The claim that every built-in preset is unsafe conflates arbitrary runtime arguments with permission-bypass flags. The log supports that conclusion for several presets, but not all of them.

3. Several “desk-verified” assertions preserve conclusions without their commands or outputs. Under the repository’s evidence discipline, these are attestations rather than independently checkable static evidence.

FINAL VERDICT: **SEAL-REFUTED** — the overturned claim is that the captured bytes exhaustively prove every public launch route requires a registered rig and every public rig-registration route requires a running Dolt daemon. The documented `gt rig add --adopt` path was wrongly excluded without execution, and the sling probe never reached rig resolution.

## Severity-counted findings

- **P0: 0**
- **P1: 2**
  - P1-1: Public `gt init` → `gt rig add --adopt` registration path was wrongly rejected without testing.
  - P1-2: The universal sling/assign/formula rig-dependency claim is unsupported because sling exposes HQ/mayor targets and the actual sling probe failed earlier on invalid input.
- **P2: 6**
  - P2-1: The frozen card does not itself record the daemon stop rule; that rule appears only in the transport log.
  - P2-2: “Every built-in preset carries a yolo flag” is contradicted by the captured agent list.
  - P2-3: The reported invocation count is 32; the log contains 34 command records.
  - P2-4: Process absence, capture-file absence, cleanup, and clean-tree claims lack preserved command output.
  - P2-5: Hand telemetry and “verbatim” correspondence are not supported by an included hand receipt.
  - P2-6: The observed configuration path is `settings/config.json`, not the frozen `settings/agents.json`, without explicit seam-drift disposition.

END-SEAL-AUDIT