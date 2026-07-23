# Phase-0 native probe receipt — 2026-07-19, desk-supervised

Binaries: gt v1.2.1 / bd v1.1.0 (8e4e59d39), hash-verified against pins and
publishers' checksum files before extraction (D:\Tools\downloads\, MATCH ×2,
checksums-file cross-check ×2). Sizes: gt zip 14,039,707 B; bd zip 49,888,251 B.

## Beads, native Windows — GREEN
Throwaway dir S:\Temp\claude\bd-probe: `bd init` OK → `bd create "smoke probe
issue" -p 0` → id bd-probe-50n → `bd ready --json` lists it → `bd update
bd-probe-50n --claim` → status IN_PROGRESS, ready set now empty. Atomic claim
+ ready computation work with embedded Dolt, no daemon. Smoke facts 1 and 8
are provable natively.

## gt, native Windows — CLI surface alive, launch path untested
`gt --help` and `gt config agent list` answer without a daemon. FINDING,
frozen: gt's BUILT-IN claude preset is `claude --dangerously-skip-permissions`
— the smoke's custom preset must be authored explicitly and must NOT inherit
built-ins (custody fact 3 gains a concrete check: assert the launched command
line contains no --dangerously-skip-permissions).

## Open question → phase 1 proper
Whether agent LAUNCH (assign/hook/formula execution) requires `gt up`'s
daemon+tmux town on native Windows. Dispatched as a provider-free hand
attempt; either outcome is a valid transport finding per the card's no-go
classes.
