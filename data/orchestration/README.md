# ARC-C orchestration runs

Validated run plans and sealed trial receipts live here. The Codex and Claude
ARC-C runs are independently sealed at K=3 for all three almanac knots against
source commit `3d3837165ac9e046acf2cecc27e01f9c41c302e5`. The cross-engine
comparison is preserved in `comparisons/arc_c_almanac_cross_engine_v1.json`: the pair is
comparable and agrees on 3/3 task decisions. Codex desktop administration
receipts bind the complete local provider rollouts by SHA-256 while committed
event snapshots omit host-injected policy and workstation context. See
`docs/residue-broker.md` and validate with
`python scripts/validate_orchestration_run.py`.
