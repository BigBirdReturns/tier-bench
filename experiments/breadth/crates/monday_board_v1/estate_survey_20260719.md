# Estate survey — front-page audit, 2026-07-19 (adjudicated)

*Three survey hands (1 sonnet $2.24, 2 haiku $0.48) over the active repos; desk ran the
authoritative git sweep (hands' sandboxes blocked git — their commit DATES were wrong and
are corrected here from real `git log`; two structural claims desk-REFUTED, noted below).
Lens: the front page is what a reader hits first; the record is git log + committed bytes.*

| repo | last commit | front page verdict | cheapest fix |
|---|---|---|---|
| Program-of-Record | 2026-07-19 | **MISSING/misdirects** — no root README; nearest README documents the FROZEN legacy build; real status (`rebuild/docs/STATUS.md`, R6 PASS) is 3 dirs deep; 438 dirty lines = documented CRLF churn, not work | 12-line root README pointing at rebuild/STATUS.md |
| Clifford-Number/repo | 2026-07-18 | **STALE ×2** — README:11-14 describes `app.js` views that no longer ship; deployed 3-plane page is already condemned by `test/ui-contract.test.js` (12 intentional reds; redesign in flight per handoff docs) | rewrite README:9-16 or flag "mid-redesign, contract in tests" |
| Civilization-Kernel-STC | 2026-07-17 | **OVERCLAIMS** — README lists 27 accepted source packs but ~15+ pack dirs/docs are untracked, never committed; log has 12 commits total | commit the packs so the log matches the claim |
| UnderCast/main | 2026-07-16 | **CURRENT** — README matches structure and image-provenance policy; note unmerged branch `codex/enforce-real-image-policy` | none |
| Almanac/main | 2026-07-14 | **CURRENT, unlabeled branch** — accurate README + sealed Phase 0, but the code lives on `codex/bootstrap`, not main, and the README doesn't say so | one branch-label line in README |
| EarCrate/main | 2026-07-14 | **CURRENT for main** (v0.8.30 at tip; v0.9 on branch `earcrate-v0.9.0-complete`). Hand's "broken HEAD/no main" claim **desk-REFUTED**: `* main` checked out, HEAD ref clean | note in README which branch carries v0.9 |
| GhostBox/main | 2026-07-09 | **UNVERIFIED claim** — README's "108/108 CI" not confirmed; hand's "zero-commit clone, no tests/CI" **desk-REFUTED** (merged PRs #12/#13, `tests/` and `.github/workflows` exist) | run the suite once and pin the true count |
| AXM constellation (axm, axm-core, axm-genesis, Axiom-KG, Axiom-Knowledge-Core) | 2026-07-10..15 clones | **CURRENT** READMEs across the stack; core/genesis live under `recovery/` snapshots (custody deliberate) | none urgent |
| Spectra-Genesis (×2 copies) | 2026-07-15 | **STALE** — one-line README on a substantial codebase | real README |
| **axm-production-v5** | — | **ABSENT FROM LOCAL DISK** — the Genesis/Forge/Clarion/GraphKDF/Spectra production stack referenced by NODAL-FLOW-SYSTEM-TRUTH.md exists only in a claude.ai session upload folder. Custody hole under the Nodal Flow foundation | pull it local into a repo before any client work |

## Desk lessons recorded

1. Survey hands without git access misread `.git` internals — two false structural claims
   (EarCrate, GhostBox) died at desk verification. Future survey hands get the desk's git
   sweep as input, or git access.
2. The estate-wide pattern is real: 5 of 10 front pages are stale-to-lying, and the two
   most active repos (Program-of-Record, Clifford) are the worst offenders — front pages
   rot fastest exactly where the record moves fastest. The Monday board's traceable-bytes
   rule is the antidote, repo by repo.
