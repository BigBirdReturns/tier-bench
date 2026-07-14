# Tier pilot production activation — pre-canary contract

This layer makes production adapter identity verifiable without authorizing a
pilot run. An official `tier-bench/tier-pilot-activation@1` object must be read
from an exact Git commit on `refs/remotes/origin/main`; checkout files are not
an evidence fallback. Maintainer merge of separately operator-ratified bytes is
the adoption act.

The activation object binds all of the following at one commit:

- the exact `pilot-backends@2` composition and canonical digest of every backend
  entry;
- every prompt-template path and byte hash opened by the composition loader;
- the running activation validator, production adapter, and bridge source bytes;
- the code-owned byte-preserving adapter identity, CLI version, and raw help
  surface;
- distinct production dispatch, provider, acceptance, and bridge schemas; and
- the control repository's exact `origin`, remote default ref, and evidence root.

The loader rejects an unlanded commit, remote substitution, checkout/source
drift, unknown or missing fields, backend or prompt drift, schema substitution,
and any activation that claims task-disclosure or verdict authority.

`pilot_adapter.run_activated_adapter` deliberately ignores manifest command
argv. It constructs the provider command from code, verifies the activated CLI
version/help surface, sends the exact rendered prompt bytes, preserves stdout
and stderr as raw bytes, requires complete provider telemetry, and writes one
standard backend result with an activation-bound ledger row. A deterministic
runner seam tests this path without invoking a model.

## Still blocked

No activation instance or production bridge entrypoint is included here.
`start_pilot_arm()` still refuses unconditionally. A later PR must commit the
actual backend/prompt selection and activation object, obtain operator
ratification and cross-lineage review, then merge it. Even after that merge, the
synthetic canary requires separate operator authorization. Pilot-task selection,
disclosure, grading, comparison, and verdicts remain unauthorized.

Canonical Arm-C intervention continuation and crash recovery also remain launch
blockers unless a later reviewed change implements them explicitly. An
ambiguous call is never retried automatically.
