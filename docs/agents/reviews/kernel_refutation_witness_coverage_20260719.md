# Witness coverage map — Sol's 21-item negative-witness inventory vs committed crate fixtures (2026-07-19)

*Authored by a claude-haiku hand ($0.16, 29 turns) under KERNEL-REFUTATION-DISPOSITION-1;
desk-verified: all 13 cited evidence paths exist in the worktree. Strict standard applied:
name-similarity is not coverage — the fixture must exercise the failure mode.*

| # | inventory item (short) | status | evidence |
|---|---|---|---|
| 1 | Unauthorized local commit as authority root | COVERED | experiments/breadth/crates/referee_kernel_contract_v1/witnesses/w3_base_commit_drift/witness.py |
| 2 | Evidence-index substitution under unchanged policy | MISSING | — |
| 3 | Self-graded, mismatched, partial, contaminated, stale, K-insufficient measurement | PARTIAL | experiments/breadth/crates/policy_kernel_contract_v1/fixtures/invalid_fake_measured.json, invalid_unlabeled_stale.json |
| 4 | Unmeasured fallback execution and unsatisfied operator gate | MISSING | — |
| 5 | In-process network/model/environment/file access by policy kernel | MISSING | — |
| 6 | Kernel-selected staleness window or observation time | COVERED | experiments/breadth/crates/policy_kernel_contract_v1/fixtures/invalid_unlabeled_stale.json |
| 7 | Post-authorization task/acceptance substitution | COVERED | experiments/breadth/crates/referee_kernel_contract_v1/witnesses/w1_acceptance_command_mutated_post_freeze/witness.py |
| 8 | Candidate modification of verifier dependencies | MISSING | — |
| 9 | Verifier network, model, scheduler, or out-of-evidence writes | PARTIAL | experiments/breadth/crates/referee_kernel_contract_v1/witnesses/w6_verifier_mutated_candidate/witness.py |
| 10 | Acceptance depending on ignored file omitted from patch | PARTIAL | experiments/breadth/crates/referee_kernel_contract_v1/witnesses/w4_empty_patch_not_accepted/witness.py |
| 11 | Contradictory terminal receipts validated in separate subsets | COVERED | experiments/breadth/crates/work_receipt_contract_v1/fixtures/rejection_contradictory_terminal_states.json |
| 12 | Terminal authority or scheduler effects with UNVERIFIED_PREDECESSOR | COVERED | experiments/breadth/crates/work_receipt_contract_v1/fixtures/rejection_unverified_predecessor.json |
| 13 | Unrelated unlock/block injection and effects from rejected/error receipts | COVERED | experiments/breadth/crates/work_receipt_contract_v1/fixtures/rejection_malformed_scheduler_effects.json |
| 14 | Self-reported runtime/referee success without underlying receipts | PARTIAL | experiments/breadth/crates/work_receipt_contract_v1/fixtures/rejection_missing_content_binding.json, experiments/breadth/crates/referee_kernel_contract_v1/witnesses/w7_corrupted_receipt_binding/witness.py |
| 15 | Same displayed external version with substituted executable/preset bytes | MISSING | — |
| 16 | Adapter failure incorrectly satisfying provider-free negative gate | PARTIAL | experiments/breadth/crates/referee_kernel_contract_v1/witnesses/w5_acceptance_failed_rejected/witness.py |
| 17 | Close/reopen/reclose and post-hoc receipt attachment | MISSING | — |
| 18 | Credential canaries reaching child environment, argv, logs, receipt, prompt | PARTIAL | experiments/breadth/crates/policy_kernel_contract_v1/fixtures/invalid_credential_in_field.json |
| 19 | Hidden retry, double launch, or session resume under one-dispatch budget | MISSING | — |
| 20 | Shell/argv transport metacharacter and encoding cases | MISSING | — |
| 21 | Multi-fault referee failures with deterministic reason precedence | MISSING | — |

Tally: 7 COVERED / 7 PARTIAL / 7 MISSING

## Desk note (adjudication context, not part of the hand's output)

Of the 7 MISSING, items 15, 19, and 20 target the smoke's live-dispatch machinery
(phase 2), which is mooted for now by the phase-1 DAEMON-REQUIRED seal — no live
path exists to guard. Items 2, 4, 5, 8, 17, 21 target the three contract crates
and remain real gaps for the disposition draft to weigh. Per-finding disposition
(and whether any MISSING witness gets built) stays proposal-only pending operator
disposition of the refutation.
