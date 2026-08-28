"""Control-path tests for the speculative executor contracts.

Synthetic only. Passing these proves the contracts, not K3 integration.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from k3_dspark_speculative import contracts as C
from k3_dspark_speculative.synthetic_target import (
    DriftingTarget,
    ExplodingDrafter,
    ExplodingTarget,
    ScriptedDrafter,
    SyntheticTarget,
    make_aux_bundle,
)

LAYERS = [2, 23, 47, 71, 89]
PREFIX = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
IDS = {"target_identity": {"name": "synthetic"}, "drafter_identity": {"name": "scripted"}}


def step(target, drafter, bundle=None, receipts=None):
    return C.speculative_step(
        target=target,
        drafter=drafter,
        aux_bundle=bundle if bundle is not None else make_aux_bundle(LAYERS),
        expected_layers=LAYERS,
        existing_receipts=receipts,
        **IDS,
    )


class AcceptanceLengths(unittest.TestCase):
    def test_full_block_acceptance(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(7)
        r = step(t, ScriptedDrafter(truth))
        self.assertEqual(r["terminal_status"], "ok")
        self.assertEqual(r["accepted_length"], 7)
        self.assertEqual(t.export_state()["prefix"], PREFIX + truth)

    def test_partial_acceptance(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(7)
        wrong = list(truth)
        wrong[3] = (wrong[3] + 1) % 16
        r = step(t, ScriptedDrafter(wrong))
        self.assertEqual(r["accepted_length"], 3)
        self.assertEqual(t.export_state()["prefix"], PREFIX + truth[:3])

    def test_single_acceptance(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(7)
        wrong = [truth[0]] + [(x + 1) % 16 for x in truth[1:]]
        r = step(t, ScriptedDrafter(wrong))
        self.assertEqual(r["accepted_length"], 1)

    def test_zero_acceptance_rolls_back_exactly(self):
        t = SyntheticTarget(PREFIX)
        before = C.state_hash(t.export_state())
        truth = t.greedy_continuation(1)
        r = step(t, ScriptedDrafter([(truth[0] + 1) % 16] * 7))
        self.assertEqual(r["accepted_length"], 0)
        self.assertEqual(C.state_hash(t.export_state()), before)
        self.assertEqual(r["state_hash_after"], before)

    def test_speculative_equivalence_with_sequential(self):
        """Committed tokens must equal sequential decoding regardless of proposal."""
        for bad_at in (0, 2, 6, None):
            t_spec = SyntheticTarget(PREFIX)
            t_seq = SyntheticTarget(PREFIX)
            truth = t_seq.greedy_continuation(7)
            proposal = list(truth)
            if bad_at is not None:
                proposal[bad_at] = (proposal[bad_at] + 1) % 16
            step(t_spec, ScriptedDrafter(proposal))
            n = t_spec.export_state()["position"] - len(PREFIX)
            t_seq.advance(truth[:n])
            self.assertEqual(t_spec.export_state(), t_seq.export_state())


class FailurePaths(unittest.TestCase):
    def test_verifier_exception_rolls_back(self):
        t = ExplodingTarget(PREFIX)
        before = C.state_hash(t.export_state())
        r = step(t, ScriptedDrafter([1, 2, 3]))
        self.assertEqual(r["terminal_status"], "exception:RuntimeError")
        self.assertEqual(C.state_hash(t.export_state()), before)

    def test_drafter_exception_rolls_back(self):
        t = SyntheticTarget(PREFIX)
        before = C.state_hash(t.export_state())
        r = step(t, ExplodingDrafter())
        self.assertEqual(r["terminal_status"], "exception:RuntimeError")
        self.assertEqual(C.state_hash(t.export_state()), before)

    def test_malformed_bundle_rejected(self):
        t = SyntheticTarget(PREFIX)
        bad = make_aux_bundle(LAYERS)
        del bad["captures"][0]["sha256"]
        r = step(t, ScriptedDrafter([1]), bundle=bad)
        self.assertEqual(r["terminal_status"], "failed:aux_bundle")
        self.assertEqual(r["accepted_length"], 0)

    def test_wrong_layer_identity_rejected(self):
        t = SyntheticTarget(PREFIX)
        r = step(t, ScriptedDrafter([1]), bundle=make_aux_bundle([2, 23, 47, 71, 90]))
        self.assertEqual(r["terminal_status"], "failed:aux_bundle")

    def test_state_hash_drift_detected(self):
        t = DriftingTarget(PREFIX)
        truth = SyntheticTarget(PREFIX).greedy_continuation(3)
        r = step(t, ScriptedDrafter(truth[:3]))
        self.assertEqual(r["terminal_status"], "failed:commit")
        # rollback restored the snapshot despite the drift
        self.assertEqual(r["state_hash_after"], r["state_hash_before"])

    def test_oversize_and_empty_proposals_rejected(self):
        t = SyntheticTarget(PREFIX)
        for bad in ([], list(range(8))):
            r = step(t, ScriptedDrafter(bad))
            self.assertEqual(r["terminal_status"], "failed:draft")


class Receipts(unittest.TestCase):
    def test_replay_of_existing_receipt_detected(self):
        t1 = SyntheticTarget(PREFIX)
        truth = t1.greedy_continuation(2)
        r1 = step(t1, ScriptedDrafter(truth[:2]))
        t2 = SyntheticTarget(PREFIX)
        r2 = step(t2, ScriptedDrafter(truth[:2]), receipts=[r1])
        self.assertTrue(r2.get("replay_of_existing_receipt"))
        r3 = step(SyntheticTarget(PREFIX), ScriptedDrafter([truth[0]]), receipts=[r1])
        self.assertFalse(r3.get("replay_of_existing_receipt", False))

    def test_receipt_fields_present(self):
        t = SyntheticTarget(PREFIX)
        r = step(t, ScriptedDrafter(t.greedy_continuation(4)[:4]))
        for key in ("schema", "target_identity", "drafter_identity", "proposal",
                    "per_position_decisions", "accepted_length", "state_hash_before",
                    "state_hash_after", "wall_seconds", "terminal_status", "receipt_sha256"):
            self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
