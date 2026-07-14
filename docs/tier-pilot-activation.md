# Tier pilot production activation — pre-canary contract

This layer makes production adapter identity verifiable without authorizing a
pilot run. An official `tier-bench/tier-pilot-activation@1` object must be read
from an exact Git commit that is an ancestor of the authenticated tier-bench
`refs/heads/main` returned by `git ls-remote`; checkout files and a mutable local
tracking ref are not evidence fallbacks. The loader fetches that exact remote
head without updating a local ref, then performs the ancestry check. Network or
TLS failure is a refusal. Maintainer merge of separately operator-ratified bytes
is the adoption act.

The activation object binds all of the following at one commit:

- the exact `pilot-backends@2` composition and canonical digest of every backend
  entry;
- every prompt-template path and byte hash opened by the composition loader;
- the complete transitive execution closure: activation validator, production
  adapter and bridge, every executed package initializer, Claude
  command/environment adapter, composition state and manifest runtimes,
  packet/session core, and backend-manifest runtime;
- the code-owned byte-preserving adapter identity, CLI version, and raw help
  surface;
- distinct production dispatch, provider, acceptance, and bridge schemas; and
- the control repository's exact `origin`, remote default ref, and evidence root.

The loader rejects an unlanded commit even if a local `origin/main` tracking ref
is forged, remote substitution, checkout/source drift, unknown or missing
fields, backend or prompt drift, schema substitution, and any activation that
claims task-disclosure or verdict authority. All custody source paths are pinned
`eol=lf` and compared byte-for-byte; there is no newline-normalization exception
that could hide a changed string literal.

Host-local Git configuration remains part of the activation trust boundary.
In particular, a hostile `url.*.insteadOf` rule can redirect Git network
operations even while `remote get-url origin` reports the canonical URL. The
operator must ratify and run an activation only on a host whose system, global,
and repository Git configuration is under operator control; the loader cannot
independently authenticate the Git client configuration executing its own
network calls.

`pilot_adapter.run_activated_adapter` deliberately ignores manifest command
argv. It constructs the provider command from code, verifies the activated CLI
version/help surface, sends the exact rendered prompt bytes, preserves stdout
and stderr as raw bytes, requires complete provider telemetry, and writes one
standard backend result with an activation-bound ledger row. It hashes the same
dispatch byte buffer it validated before the call, and an escalation dispatch is
bound to one exact ladder position rather than any configured rung. A
deterministic runner seam tests this path without invoking a model.

`PilotActivation` is a Python dataclass, not an in-process security boundary.
The future production bridge must be the sole caller of the real adapter and
must invoke `load_official_activation` itself for every resumed or fresh
session. It must never accept a caller-supplied `PilotActivation` object. Until
that bridge enforcement point is reviewed and merged, no activation instance
can authorize a call.

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
