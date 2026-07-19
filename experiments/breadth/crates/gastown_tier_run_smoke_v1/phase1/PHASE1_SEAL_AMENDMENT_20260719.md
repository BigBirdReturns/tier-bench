# Phase-1 seal AMENDMENT — 2026-07-19, after cross-engine audit (SOL-SEAL-AUDIT-1)

Sol's adversarial audit ([sol_gastown_phase1_seal_audit_20260719.md](../../../../../docs/agents/reviews/sol_gastown_phase1_seal_audit_20260719.md))
returned **SEAL-REFUTED** on the categorical claim. The desk accepts the refutation.
The original seal is preserved unedited except for a pointer to this amendment;
defects stay as provenance.

## Verdict reclassified

**Was:** DAEMON-REQUIRED (categorical — no daemon-free native launch path exists).
**Is:** **ORDINARY-RIG-ADD-DAEMON-BLOCKED; ADOPT-PATH-UNTESTED.**

The bytes prove: `gt rig add <name> <url>` (clone mode) hard-fails without the Dolt
server, and `gt dolt start` is a background server by its own help text. The bytes
do NOT prove the universal claim: the hand never ran the CLI's own suggested
`gt rig add --adopt` route (after `gt init`, which publicly creates the rig layout),
never probed `GT_TOWN_ROOT`/`GT_RIG` env resolution, never examined `gt dolt
init`/`init-rig`, and its only sling probe failed on an invalid bead (`self`)
BEFORE target/rig resolution — so "sling needs a rig" was never demonstrated.
Rejecting `--adopt` as internal-structure coupling was wrong: composing documented
public CLI verbs is not coupling to internal Go structures.

## Operative outcome — UNCHANGED

Phase 1 still did NOT pass (no capture invocation was ever reached); phase 2 was
never dispatched; the one-dispatch budget is unspent; the smoke stays sealed
PARTIAL; **no retry is authorized by this amendment** — the untested routes above
are RECORDED as candidates for a future operator-authorized protocol version only.

## Desk corrections (accepted from the audit)

1. Command count: **34** gt invocations, not 32 (desk recount confirms 34).
2. "Every built-in preset carries a yolo flag" is FALSE. Desk recount from the
   captured inventory: **7 of 12** built-ins carry permission-bypass-class args
   (amp `--dangerously-allow-all`, claude `--dangerously-skip-permissions`,
   codex `--dangerously-bypass-approvals-and-sandbox`, copilot `--yolo`,
   gemini `--approval-mode yolo`, groq-compound `--dangerously-skip-permissions`,
   vibe `--agent auto-approve`); `opencode` has no args; `omp`/`pi` carry hook
   paths; `auggie --allow-indexing` and `cursor -f` are not clearly bypass flags.
   PHASE0's narrow frozen finding (the *claude* preset is yolo-flagged) stands.
3. Desk-verification claims in the seal (no process running, no capture JSON, no
   stray `settings/`, clean tree) were real checks run at the desk on 2026-07-19
   but their command outputs were not preserved in the seal — they are hereby
   labeled ATTESTATIONS, not log-backed evidence.
4. The hand receipt is now vendored: [hand_receipt.json](hand_receipt.json)
   (sonnet, 62 turns, $2.64, structured result). This closes the audit's P2-5.
5. Seam drift recorded: the frozen card names `settings/agents.json`; the observed
   gt v1.2.1 public write path is `settings/config.json` (via `gt config agent
   set`). Within the CLI boundary, but the frozen external belief was stale.
6. The daemon-STOP rule lived in the dispatch prompt/transport log, not the frozen
   card's no-go classes; that authority distinction is acknowledged.
