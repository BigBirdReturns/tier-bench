# Breadth-scaling: the first measured waterline (2026-07-18, overnight)

One spec, N independent field-normalization rules (12 primitive ops), per-rule
recall measured with isolating probes -> we see EXACTLY which rules drop.
Smoke: reference hits 1.0 at every N. All grading BOM-tolerant (lesson 15).

## Monolithic recall vs N (Spark 5.3, effort low)
| N  | recall | drops |
|----|--------|-------|
| 10 | 1.000  | 0 |
| 20 | 1.000  | 0 |
| 40 | 1.000  | 0 |
| 80 | 0.9875 | 1 (suffix_trim) |
| 120| 1.000  | 0 |
| 160| see K=3 below |
| 240| 1.000  | 0 (single run) |

## N=160, K=3 (Spark): {0.9688, 0.9812, 1.000}  mean ~0.983, drops {5,3,0}
Adjudicated REAL, not harness: e.g. rule "if f53 ends with '_old' remove it",
probe "name_old" -> Spark returned "name_old" UNCHANGED. Rule simply not
implemented. Drops are STOCHASTIC (120 and one 160-run were clean) and
concentrated in LOW-SALIENCE rules (suffix_trim, upper, strip, abs_cap,
bool_flip, mod, lower) - the boring one-liners easy to overlook in a long list.

## Cross-model: Luna 5.6 N=160 = 0.9812 (dropped strip, bool_flip, suffix_trim)
The breadth waterline is GENERAL, not Spark-specific. Both cheap tiers drop
~2-3 of 160 rules. This is the first place ANY model measurably degraded in the
whole program - and it is on BREADTH (many independent requirements), not DEPTH
(20-stage chains held) or DIFFICULTY (knots held).

## Rescue: decomposition (4 scoped passes of 40 rules) N=160 -> 1.000 (run 1)
K=3 rescue confirmation in progress. If it holds, scoping context per pass is
the first structural intervention with a measured QUALITY delta (not just the
~35% context-cost delta CART0 crates showed) - the payoff the crate thesis
predicted, now at scale.

## Cross-vendor refinement (corrects lesson 16's "general" claim)
Lesson 16 said the breadth waterline was "general, not Spark-specific" (Luna
also dropped). More data narrows that: it is general across GPT-cheap via the
CODEX CLI (Spark 5/10 imperfect runs, Luna dropped 3), but Claude-cheap via
the AGENT TOOL did NOT exhibit it - Haiku 3/3 clean across distinct ~160-rule
instances (0 drops / 483 rules), Sonnet 1/1 clean. If Haiku shared Spark's
~1% per-rule rate, P(0 drops in 483 rules) ~= 0.008 - so the divergence is
real, not luck. BUT it is confounded by execution surface: GPT ran through
Codex CLI's edit-apply loop (which may silently fail to apply some edits in a
very large file), Claude through the Agent tool's Edit/Write. Leading
alternative hypothesis: the drop is partly a CLI edit-loop artifact, not pure
model attention. Testable (have Spark EMIT the whole function as text instead
of editing in place) - not yet run. Honest status: breadth requirement-drop is
confirmed on the GPT+Codex-CLI path and absent on the Claude+Agent-tool path;
decomposition into <=40-rule passes fixes it on the path where it appears.

## RESOLVED: the breadth "waterline" was a Codex-CLI edit-loop artifact, not the model
Emit-mode test (Spark receives the spec in-prompt and OUTPUTS the whole
normalize() as text; no file edit-loop): N=160, 7/7 runs recall 1.0, ZERO
drops. Compare edit-mode (Spark edits input.py in place via the CLI apply
loop): ~55% of runs imperfect. Same model, same specs, same effort - the ONLY
difference is edit-in-place vs emit-as-text. Conclusion: the requirement
"dropping" was the Codex CLI silently failing to apply some edits in a large
file, NOT the model omitting rules. This also explains Claude-via-Agent-tool
being clean (Haiku 3/3): a different editing mechanism. It reframes the
decomposition rescue: splitting into 4x40 passes helped because smaller files
mean fewer edits for the lossy apply-loop to drop - a workaround for a TOOLING
bug, not a model-capability rescue. Net: the solving floor is universal, deep
(20-stage chains), AND broad (160-320 independent requirements) once the
model's output is not mangled by a lossy edit interface. Verify-the-verifier
(lesson 15) applied to the harness itself one more time.
