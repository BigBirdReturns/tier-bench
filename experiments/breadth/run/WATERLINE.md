# THE WATERLINE — generated from waterline.json (regenerate: `python experiments/breadth/waterline.py --explain > run/WATERLINE.md`... then re-add this header)

```
THE WATERLINE — cheapest measured execution path per task
(anything not listed is unmeasured; evidence layers in known_corner.jsonl)

task01_parse_duration
  class: settled
  cheapest measured: claude-haiku-4-5 @ harness
  score: hidden 38/38 x3 (K=3)
  cost: ~$0.038/trial (shadow-estimated)
  evidence: k3-floor-20260708
  next allowed spend: none — sealed; do not re-derive

task06_select
  class: settled
  cheapest measured: claude-haiku-4-5 @ framed-search
  score: 3/3 verified counterexamples
  cost: ~$0.045/trial (shadow-estimated)
  evidence: k3-floor-20260708
  next allowed spend: none — sealed; do not re-derive
  caveat: search framing did part of the lifting — solver was told to hunt a counterexample, not to judge the code

t3_parse_duration_004
  class: settled
  cheapest measured: claude-haiku-4-5 @ hidden-grade
  score: 3/3 incl. hidden edge tests
  cost: ~$0.04/trial (shadow-estimated)
  evidence: k3-floor-20260708
  next allowed spend: none — sealed; do not re-derive

t4_plan_decomposition_001
  class: settled
  cheapest measured: claude-haiku-4-5 @ hidden-semantic-judge
  score: 3/3 incl. hidden judge
  cost: ~$0.037/trial (shadow-estimated)
  evidence: k3-floor-20260708
  next allowed spend: none — sealed; do not re-derive

task02_wildcard
  class: judgment_residue
  residue: escape-inside-class malformed-vs-non-match boundary (in-class backslash is a literal, not an escape prefix)
  floor status: claude-haiku-4-5 3/5; both failures the same rule commitment (edge_family/RESULTS.md)
  cheapest measured: claude-sonnet-5 @ low
  score: hidden 10681/10681 x3 (K=3)
  cost: ~$0.227/trial (real-billed)
  evidence: model-ladder-task02-20260708
  next allowed spend: cheap edge-family probes only; frontier escalation blocked by DO NOT ESCALATE
  caveat: GPT-5.5 derived repairs also 10681/10681 x3 — derived class, not receipts (pr44_trial2_adjudication.md)

adjudications (evidence-class corrections, not capability rows):
  pr44_trial2_gpt55_task02: transport_error_not_model_failure (run/pr44_trial2_adjudication.md)
```

Schema + evidence enforcement: `python experiments/breadth/waterline.py --check`.
Machine-readable: `run/waterline.json`. Declared (unmeasured) model claims stay in models.json's tier_ceiling and are labeled there.
