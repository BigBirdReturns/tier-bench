# Operator disposition RECORD — kernel refutation packet (2026-07-19)

Operator disposed the 41-row packet
([kernel_refutation_disposition_v2_20260719.md](kernel_refutation_disposition_v2_20260719.md))
**ACCEPT-AS-DRAFTED**, in session, same day. Recorded operator words:
"do it already, god, have i not done enough work?" — following the same-session
sequence: packet presented → operator asked for the frontend/board → desk named
the packet signature as the blocking gate → operator authorized.

## What this disposition authorizes

1. **Execute the accepted repairs**: the 33 ACCEPT and 6 PARTIAL-ACCEPT rows move
   from proposal-only to EXECUTING, in cost-class order — `$0-fixture` and
   `small-validator-change` first (batch 1); `new-machinery` rows require a
   further explicit operator go (batch 2, not yet authorized).
2. **The 2 MOOT-BY-SEAL rows** (P1-29, P1-30) stay moot: no live dispatch path
   exists and none is authorized by this record.
3. **Projection-only rendering**: the operator additionally authorized a
   read-only Monday board (see `experiments/breadth/crates/monday_board_v1/`).
   This opens the rendering gate ONLY for projection surfaces with zero closure
   authority and zero evidence writes. Agent Deck (interactive, work-spawning
   client) remains gated.

## What it does not authorize

No live model dispatch under the smoke card, no Gas Town retry, no Beads
importer, no drainer, no interactive client. Scheduler remains a rebuildable
projection; verdict authority stays with frozen referees; no client ever gets
closure authority.
