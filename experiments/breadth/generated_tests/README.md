# Machine-generated, mutation-verified characterization tests

These pin the CURRENT behavior of previously-untested breadth-harness safety
rails (`adapt.py`, `escalate.py`, `limit.py` — the "rails that make an
unattended run safe" per CLAUDE.md). Authored by gpt-5.3-codex-spark, gated by
an external referee that admits a test only if it (1) passes the real module
and (2) kills >=1 deliberate source mutation (proving teeth). Mutation scores:
adapt 1/6, limit 3/6, escalate 7/8.

They characterize what the code DOES, not what it SHOULD do — review before
trusting any assertion as intended spec. Run: `python generated_tests/test_*_gen.py`.
Provenance/method: experiments/breadth/races/scale/ (real-test factory).
