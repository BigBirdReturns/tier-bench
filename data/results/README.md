# data/results

Packaged benchmark contributions live here, one file per submitted run,
produced only by `python scripts/contribute.py --results ... --as yourhandle`.
Never hand-edit a file in this directory and never commit synthetic or
hand-crafted rows — the filename and the `_meta` line are the provenance
record, and both are meaningless if a human typed the numbers instead of the
harness.

Every file that touches this directory in a pull request is checked
mechanically by CI (`.github/workflows/validate.yml`): each is re-validated
with `scripts/contribute.py --validate`, and `scripts/aggregate.py` must be
able to digest the whole directory without error. No human judgment call
gates a merge — either the rows are structurally sound or they aren't.

**Evidence-class doctrine.** Every row here is self-reported: a contributor
ran the harness on their own machine, with their own keys, and packaged the
output. A `(model, tier)` cell backed by only one contributor is
`single-source` — a claim, not a fact. Only when **two or more distinct
contributors** report rows for the same cell does it become `corroborated`.
`scripts/aggregate.py` computes and labels this for every pooled number; the
label always travels with the number, never presented alone.
