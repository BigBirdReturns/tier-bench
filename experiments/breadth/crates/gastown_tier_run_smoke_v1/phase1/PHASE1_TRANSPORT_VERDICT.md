# Phase-1 transport verdict — SEALED 2026-07-19, desk-adjudicated

> **AMENDED same day after cross-engine audit (SEAL-REFUTED on the categorical
> claim): see [PHASE1_SEAL_AMENDMENT_20260719.md](PHASE1_SEAL_AMENDMENT_20260719.md).
> Verdict reclassified ORDINARY-RIG-ADD-DAEMON-BLOCKED / ADOPT-PATH-UNTESTED;
> operative outcome (phase 1 not passed, PARTIAL, no retry) unchanged. This
> original is preserved with its defects as provenance.**

**VERDICT: DAEMON-REQUIRED. Phase 1 did not pass. Phase 2 is therefore
forbidden by the frozen card and was never dispatched — the one-dispatch
budget is unspent. Smoke sealed PARTIAL per the card's frozen expectation
("PARTIAL is a complete night").**

## Finding

gt v1.2.1 on native Windows cannot reach its agent-launch surface without a
persistent daemon — and the dependency is not where the card guessed it
would be. It is not the tmux/agent-hosting layer; it is load-bearing at the
data layer *beneath rig registration*:

- Every launch path the card names (`gt sling`, `gt assign`,
  `gt formula run`) requires a registered rig.
- The only public-boundary way to register a rig, `gt rig add`, hard-fails
  without a running Dolt SQL server; the CLI's own error says to start it
  with `gt up` or `gt dolt start` — both persistent background daemons.
- Contrast: bd v1.1.0 runs the same Dolt embedded and in-process
  (phase-0 receipt, GREEN) — this is a Gas Town architecture choice, not a
  platform limitation.

This is a command-transport no-go under the card's predetermined classes,
and per the frozen seam text it is a USEFUL TRANSPORT FAILURE — sealed, not
permission to build a custom worker framework.

## What DID work (partial credit, preserved for any future protocol)

- `gt install --no-beads` bootstraps an HQ natively, no daemon.
- `gt config agent set/get/list` — the public-boundary custom-agent seam —
  registered `tiercap` → `python capture_fixture.py` cleanly, with no
  `--dangerously-skip-permissions` in its command line.
- FINDING (extends phase-0's frozen finding): every BUILT-IN gt agent preset
  carries a yolo/dangerous-permissions flag (`claude
  --dangerously-skip-permissions`, `gemini --approval-mode yolo`, `vibe
  --agent auto-approve`, …). Custody fact 3's concrete check — assert the
  launched command line is flag-free — remains mandatory in any retry.

## Desk verification (independent, at adjudication)

- Command inventory grep of the vendored log: 32 gt invocations, all
  probe/config verbs; `gt up` never invoked; `gt dolt start` appears only as
  `--help`.
- No dolt/gt process running at adjudication time.
- No capture JSON anywhere in the workspace — the configured agent command
  was provably never reached.
- Side effect honestly reported by the hand (stray `settings/config.json`
  written to the repo root by a cwd-less `gt config agent set`, caught via
  `git status`, removed): desk re-verified `settings/` absent from the
  worktree and the tree clean.
- Hand receipt: sonnet, 62 turns, ~13.7 min, $2.64, structured result
  matches the vendored log verbatim.

Raw evidence: [transport_log.md](transport_log.md) (vendored verbatim,
48,370 bytes). Phase-0 receipt: [PHASE0_NATIVE_PROBE.md](PHASE0_NATIVE_PROBE.md).

## Disposition (fail-closed)

1. **No retry is authorized by this seal.** Per the card and the
   ARC-D-PILOT precedent, a retry is a new protocol version with new
   operator authority. The obvious candidate designs (accept `gt dolt
   start` as an owned, session-scoped service with a stop receipt; or
   `gt rig add --adopt`, rejected this run as internal-structure coupling)
   are RECORDED here as candidates only — neither is opened.
2. **No compensating platform development** follows from this outcome (card
   header, verbatim). No Agent Deck card, no general Beads importer, no
   drainer card.
3. **Contract-crate promotion is an operator decision, not a desk one.**
   The card blocks the three contract crates "until this receipt exists."
   A receipt now exists — but it is a PARTIAL, not the nine-fact closure
   packet, and Sol's 21-finding refutation of the kernel cards is still
   pending per-finding disposition. The desk does not read a PARTIAL as an
   unblock; both gates sit with the operator.
