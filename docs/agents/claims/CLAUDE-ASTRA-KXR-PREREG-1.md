# CLAUDE-ASTRA-KXR-PREREG-1

```yaml
id: CLAUDE-ASTRA-KXR-PREREG-1
owner: claude
lane: driver
state: prereg_stage1_superseded_in_campaign_design
superseded_by: CLAUDE-FRR-ASTRA-PREREG-1 (campaign-design scope only; all other
  frozen content incorporated by reference and still standing)
authorized_by: operator
authorized_at: 2026-09-02
branch: claude/astra-kxr-prereg-20260902
base_head: 8013709c6aaedc129905bf622df7a9a759891f42
stacked_on: codex/frontier-fingerprint-20260901 (SOL-FRONTIER-FINGERPRINT-1)
surface:
  - experiments/astra_kxr/PREREGISTRATION.md
  - experiments/astra_kxr/DECISION_RULES.json
  - experiments/astra_kxr/KNOWN-LIMITATIONS.md
implementation: none_yet
stage_2_required_before_any_subject_call: true
live_provider_dispatch: prohibited
subject_model_binding: none
benchmark_verdict_authority: none
manual_closure_ledger: prohibited
```

Stage-1 freeze of ASTRA-KXR-1: hypotheses, campaign design, admission gates,
analysis structure, terminal states (including
`HIDDEN_SERIAL_OR_RECURRENT_INDISTINGUISHABLE`), and amendment rules for the
black-box compute-geometry fingerprint of the OpenAI model publicly named
Astra. This claim adds three frozen documents and no executable surface: no
generators, no adapters, no manifests, no workflow changes, no grader or
pass-criteria edits. The frontier-fingerprint observatory it stacks on is
Sol-lane custody under SOL-FRONTIER-FINGERPRINT-1 and is not modified.

Prediction standing attaches to remote-custody timestamps of this branch's
commits, and only if they precede the subject's public callability. Stage 2
(numeric thresholds from the local calibration atlas, expressed as
normalized shape invariants, plus frozen generator implementations) is
mandatory before any subject call. Amendments beyond the stage-2 allowance
require a new preregistration id.

Namespace note: earlier session drafts proposed `codex/astra-kxr-*` naming;
this claim is carried in the `claude/*` namespace per the two-lane law, and
the Sol lane may register its own implementation claim against the same
preregistration surface.

This document carries no test counts, run IDs, artifact IDs, or current-head
assertions; those belong to machine-derived receipts at exact source heads.
Per the constitution's conflicted-party clause, no Claude-lineage session
narrative about this campaign carries evidentiary standing.
