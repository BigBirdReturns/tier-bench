# Machine-generated, mutation-verified characterization tests

Authored by gpt-5.3-codex-spark, gated by an external referee that banks a
test only if it (1) passes the real module and (2) kills >=1 deliberate source
mutation (proves teeth). Each pins CURRENT behavior of a previously-untested
module - review before trusting any assertion as intended spec.

Run all: `for f in experiments/breadth/generated_tests/test_*_gen.py; do ( d=$(mktemp -d) && cd "$d" && python "$OLDPWD/$f" ); done`
(each file writes fixtures to bare relative `tmp_*` paths — run from a throwaway
dir, not the repo root, or they'll litter it; `pytest experiments/breadth/generated_tests/`
is chdir-clean via the directory's `conftest.py`.)

| test | module | mutation score |
|---|---|---|
| test_adapt_gen.py | ? | ? |
| test_aggregate_control_gen.py | scripts\aggregate_control.py | 2/6 |
| test_build_buffalo_packets_gen.py | scripts\build_buffalo_packets.py | 4/7 |
| test_diff_report_gen.py | scripts\diff_report.py | 4/8 |
| test_distill_gen.py | scripts\distill.py | 3/7 |
| test_escalate_gen.py | ? | ? |
| test_events_gen.py | tier_runner\events.py | 5/6 |
| test_export_blind_control_packet_gen.py | scripts\export_blind_control_packet.py | 2/6 |
| test_ledger_gen.py | experiments\breadth\ledger.py | 2/6 |
| test_limit_gen.py | ? | ? |
| test_manifest_gen.py | tier_runner\manifest.py | 3/5 |
| test_rig_gen.py | harness\rig.py | 4/9 |
| test_validate_arc_d_b2_packet_gen.py | scripts\validate_arc_d_b2_packet.py | 5/6 |
| test_validate_lens_gen.py | scripts\validate_lens.py | 2/5 |
| test_validators_gen.py | harness\validators.py | 5/6 |

Total: 15 modules covered. Method: races/scale/real_test_factory.py.
