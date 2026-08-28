"""Control-path tests + custody witnesses for the speculative executor.

Synthetic only. Passing these proves the contracts, not K3 integration.

Two witness families beyond the original control paths:
  - StateCustodyWitnesses: the recursive type-tagged state manifest binds
    tensor CONTENT (raw bytes), not representation; unsupported types refuse.
  - ReceiptSemanticsWitnesses: schema @2 separates proposed / verified /
    committed lengths; the @1 contradiction (failed:commit with a positive
    accepted length) is structurally impossible.
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

try:
    import torch
except ImportError:
    torch = None

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


def tensor_state(base: float = 0.0):
    """A five-component state carrying real dense tensors."""
    return {
        "kda": {"recurrent": torch.arange(4096, dtype=torch.float32).reshape(64, 64) + base,
                "conv": torch.ones(8, dtype=torch.float32)},
        "mla": {"kv": torch.zeros(16, 32, dtype=torch.float16), "rows": 16},
        "attn_res": torch.linspace(0.0, 1.0, steps=2048, dtype=torch.float32),
        "position": 16,
        "prefix": list(range(16)),
    }


class AcceptanceLengths(unittest.TestCase):
    def test_full_block_acceptance(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(7)
        r = step(t, ScriptedDrafter(truth))
        self.assertEqual(r["terminal_status"], "ok")
        self.assertEqual(r["proposed_length"], 7)
        self.assertEqual(r["target_verified_prefix_length"], 7)
        self.assertEqual(r["committed_length"], 7)
        self.assertEqual(r["state_transition"], "committed")
        self.assertEqual(t.export_state()["prefix"], PREFIX + truth)

    def test_partial_acceptance(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(7)
        wrong = list(truth)
        wrong[3] = (wrong[3] + 1) % 16
        r = step(t, ScriptedDrafter(wrong))
        self.assertEqual(r["target_verified_prefix_length"], 3)
        self.assertEqual(r["committed_length"], 3)
        self.assertEqual(t.export_state()["prefix"], PREFIX + truth[:3])

    def test_single_acceptance(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(7)
        wrong = [truth[0]] + [(x + 1) % 16 for x in truth[1:]]
        r = step(t, ScriptedDrafter(wrong))
        self.assertEqual(r["committed_length"], 1)
        self.assertEqual(r["state_transition"], "committed")

    def test_zero_acceptance_rolls_back_exactly(self):
        t = SyntheticTarget(PREFIX)
        before = C.state_hash(t.export_state())
        truth = t.greedy_continuation(1)
        r = step(t, ScriptedDrafter([(truth[0] + 1) % 16] * 7))
        self.assertEqual(r["committed_length"], 0)
        self.assertEqual(r["target_verified_prefix_length"], 0)
        self.assertTrue(r["rollback_performed"])
        self.assertEqual(r["state_transition"], "rolled_back")
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
        self.assertEqual(r["committed_length"], 0)
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
        self.assertEqual(r["committed_length"], 0)

    def test_wrong_layer_identity_rejected(self):
        t = SyntheticTarget(PREFIX)
        r = step(t, ScriptedDrafter([1]), bundle=make_aux_bundle([2, 23, 47, 71, 90]))
        self.assertEqual(r["terminal_status"], "failed:aux_bundle")

    def test_oversize_and_empty_proposals_rejected(self):
        t = SyntheticTarget(PREFIX)
        for bad in ([], list(range(8))):
            r = step(t, ScriptedDrafter(bad))
            self.assertEqual(r["terminal_status"], "failed:draft")


@unittest.skipUnless(torch is not None, "torch required for tensor custody witnesses")
class StateCustodyWitnesses(unittest.TestCase):
    """The seven Phase-4 witnesses for content-bound state hashing."""

    def test_mutation_outside_displayed_repr_changes_root(self):
        a = tensor_state()
        b = tensor_state()
        # PyTorch abbreviates a 64x64 print; element (31, 31) is inside the
        # elided '...' region. Under the old repr-based hash this mutation was
        # invisible; the content-bound root must change.
        b["kda"]["recurrent"][31, 31] += 1.0
        self.assertEqual(repr(a["kda"]["recurrent"]), repr(b["kda"]["recurrent"]))
        self.assertNotEqual(C.state_root_sha256(a), C.state_root_sha256(b))

    def test_dtype_change_changes_root(self):
        a = tensor_state()
        b = tensor_state()
        b["attn_res"] = b["attn_res"].to(torch.float64)
        self.assertNotEqual(C.state_root_sha256(a), C.state_root_sha256(b))

    def test_shape_change_changes_root(self):
        a = tensor_state()
        b = tensor_state()
        b["kda"]["recurrent"] = b["kda"]["recurrent"].reshape(32, 128)
        self.assertNotEqual(C.state_root_sha256(a), C.state_root_sha256(b))

    def test_root_independent_of_print_options(self):
        a = tensor_state()
        root1 = C.state_root_sha256(a)
        saved = torch._tensor_str.PRINT_OPTS.edgeitems
        try:
            torch.set_printoptions(edgeitems=1, precision=2, threshold=5)
            root2 = C.state_root_sha256(tensor_state())
        finally:
            torch.set_printoptions(edgeitems=saved, precision=4, threshold=1000)
        self.assertEqual(root1, root2)

    def test_unsupported_layout_refuses(self):
        state = tensor_state()
        idx = torch.tensor([[0, 1], [0, 1]])
        state["mla"]["kv"] = torch.sparse_coo_tensor(idx, torch.tensor([1.0, 2.0]), (4, 4))
        with self.assertRaises(C.SpecStepError) as ctx:
            C.state_root_sha256(state)
        self.assertEqual(ctx.exception.stage, "state_manifest")

    def test_unsupported_python_type_refuses_not_repr(self):
        state = tensor_state()
        state["kda"]["recurrent"] = {1, 2, 3}  # a set has no canonical encoding
        with self.assertRaises(C.SpecStepError):
            C.state_root_sha256(state)

    def test_single_component_drift_identifies_component(self):
        a = C.state_component_manifest(tensor_state())
        drifted = tensor_state()
        drifted["mla"]["kv"][7, 19] = 3.0
        b = C.state_component_manifest(drifted)
        differing = [k for k in C.STATE_KEYS
                     if a["components"][k]["root_sha256"] != b["components"][k]["root_sha256"]]
        self.assertEqual(differing, ["mla"])
        # and the tensor binding inside the manifest names the exact field
        self.assertEqual(b["components"]["mla"]["manifest"]["entries"]["kv"]["field"], "mla.kv")

    def test_snapshot_restore_reproduces_every_component_root(self):
        state = tensor_state()
        before = C.state_component_manifest(state)
        snapshot = {k: (v.clone() if isinstance(v, torch.Tensor)
                        else {kk: (vv.clone() if isinstance(vv, torch.Tensor) else vv)
                              for kk, vv in v.items()} if isinstance(v, dict)
                        else list(v) if isinstance(v, list) else v)
                    for k, v in state.items()}
        state["kda"]["recurrent"][0, 0] = -99.0  # mutate, then restore
        restored = snapshot
        after = C.state_component_manifest(restored)
        for k in C.STATE_KEYS:
            self.assertEqual(before["components"][k]["root_sha256"],
                             after["components"][k]["root_sha256"], k)

    def test_hashing_does_not_mutate_source_tensor(self):
        state = tensor_state()
        t = state["kda"]["recurrent"]
        ptr = t.data_ptr()
        C.state_root_sha256(state)
        self.assertEqual(t.data_ptr(), ptr)
        self.assertTrue(bool((t == tensor_state()["kda"]["recurrent"]).all()))

    def test_bfloat16_binds_content(self):
        a = tensor_state()
        b = tensor_state()
        a["attn_res"] = torch.linspace(0, 1, 999, dtype=torch.bfloat16)
        b["attn_res"] = torch.linspace(0, 1, 999, dtype=torch.bfloat16)
        self.assertEqual(C.state_root_sha256(a), C.state_root_sha256(b))
        b["attn_res"][500] += 1.0
        self.assertNotEqual(C.state_root_sha256(a), C.state_root_sha256(b))


class CommitFailsAfterPartialMutation(SyntheticTarget):
    """advance() mutates part of the state, then dies mid-transition."""

    def advance(self, tokens):
        self._state["kda"] = {"recurrent": "partially", "conv": "mutated"}
        raise RuntimeError("commit died after partial state mutation")


class RollbackFails(SyntheticTarget):
    """load_state silently loses custody, so restore verification fails."""

    def load_state(self, state):
        broken = dict(state)
        broken["attn_res"] = "wrong-after-restore"
        super().load_state(broken)


class ReceiptSemanticsWitnesses(unittest.TestCase):
    """Phase-5 witnesses: @2 semantics and the impossibility of the @1 bug."""

    def _truth(self, n):
        return SyntheticTarget(PREFIX).greedy_continuation(n)

    def test_drift_before_commit_preserves_verified_but_commits_zero(self):
        t = DriftingTarget(PREFIX)
        truth = self._truth(3)
        r = step(t, ScriptedDrafter(truth[:3]))
        self.assertEqual(r["terminal_status"], "failed:commit")
        self.assertEqual(r["target_verified_prefix_length"], 3)  # preserved for diagnosis
        self.assertEqual(r["committed_length"], 0)               # nothing entered state
        self.assertTrue(r["rollback_performed"])
        self.assertEqual(r["state_transition"], "rolled_back")
        self.assertEqual(r["state_hash_after"], r["state_hash_before"])

    def test_failure_during_commit_after_partial_mutation_rolls_back(self):
        t = CommitFailsAfterPartialMutation(PREFIX)
        before = C.state_hash(t.export_state())
        truth = self._truth(2)
        r = step(t, ScriptedDrafter(truth[:2]))
        self.assertEqual(r["terminal_status"], "exception:RuntimeError")
        self.assertEqual(r["target_verified_prefix_length"], 2)
        self.assertEqual(r["committed_length"], 0)
        self.assertEqual(r["state_transition"], "rolled_back")
        self.assertEqual(C.state_hash(t.export_state()), before)
        self.assertEqual(r["state_hash_after"], before)

    def test_rollback_failure_is_recorded_not_masked(self):
        t = RollbackFails(PREFIX)
        truth = self._truth(1)
        r = step(t, ScriptedDrafter([(truth[0] + 1) % 16]))  # zero acceptance -> rollback
        self.assertEqual(r["state_transition"], "rollback_failed")
        self.assertFalse(r["rollback_performed"])
        self.assertIn("rollback_failed", r["terminal_status"])
        self.assertEqual(r["committed_length"], 0)

    def test_malformed_state_fails_closed(self):
        t = SyntheticTarget(PREFIX)
        t._state["mla"] = {"kv_rows": object()}  # no canonical encoding
        with self.assertRaises(C.SpecStepError):
            step(t, ScriptedDrafter([1]))

    def test_the_v1_contradiction_is_impossible(self):
        """failed:commit + committed_length > 0 must be unconstructable."""
        with self.assertRaises(C.SpecStepError):
            C.receipt_speculative_step(
                target_identity={}, drafter_identity={}, proposal={"tokens": [1, 2, 3]},
                verification={"accepted_length": 3, "decisions": []},
                snapshot_hash="a" * 64, final_state_hash="a" * 64,
                proposed_length=3, target_verified_prefix_length=3,
                committed_length=3, rollback_performed=True,
                state_transition="rolled_back", bytes_read=None,
                wall_seconds=0.0, thermal=None, terminal_status="failed:commit",
            )

    def test_committed_cannot_exceed_verified(self):
        with self.assertRaises(C.SpecStepError):
            C.receipt_speculative_step(
                target_identity={}, drafter_identity={}, proposal={"tokens": [1, 2]},
                verification={"accepted_length": 1, "decisions": []},
                snapshot_hash="a" * 64, final_state_hash="b" * 64,
                proposed_length=2, target_verified_prefix_length=1,
                committed_length=2, rollback_performed=False,
                state_transition="committed", bytes_read=None,
                wall_seconds=0.0, thermal=None, terminal_status="ok",
            )

    def test_rolled_back_requires_hash_restoration(self):
        with self.assertRaises(C.SpecStepError):
            C.receipt_speculative_step(
                target_identity={}, drafter_identity={}, proposal={"tokens": [1]},
                verification={"accepted_length": 0, "decisions": []},
                snapshot_hash="a" * 64, final_state_hash="b" * 64,
                proposed_length=1, target_verified_prefix_length=0,
                committed_length=0, rollback_performed=True,
                state_transition="rolled_back", bytes_read=None,
                wall_seconds=0.0, thermal=None, terminal_status="ok",
            )

    def test_replay_detection_per_terminal_outcome(self):
        """Replaying an identical step reproduces the identity hash for each
        terminal outcome family; a different step does not."""
        truth = self._truth(2)

        def committed():
            return step(SyntheticTarget(PREFIX), ScriptedDrafter(truth[:2]))

        def zero_rolled_back():
            return step(SyntheticTarget(PREFIX), ScriptedDrafter([(truth[0] + 1) % 16]))

        def failed_commit():
            return step(DriftingTarget(PREFIX), ScriptedDrafter(truth[:2]))

        def failed_bundle():
            bad = make_aux_bundle(LAYERS)
            del bad["captures"][0]["sha256"]
            return step(SyntheticTarget(PREFIX), ScriptedDrafter([1]), bundle=bad)

        def failed_bundle_with(receipts):
            bad = make_aux_bundle(LAYERS)
            del bad["captures"][0]["sha256"]
            return step(SyntheticTarget(PREFIX), ScriptedDrafter([1]), bundle=bad, receipts=receipts)

        replays = {
            committed: lambda first: step(SyntheticTarget(PREFIX), ScriptedDrafter(truth[:2]), receipts=[first]),
            zero_rolled_back: lambda first: step(SyntheticTarget(PREFIX), ScriptedDrafter([(truth[0] + 1) % 16]), receipts=[first]),
            failed_commit: lambda first: step(DriftingTarget(PREFIX), ScriptedDrafter(truth[:2]), receipts=[first]),
            failed_bundle: lambda first: failed_bundle_with([first]),
        }
        for make, rerun in replays.items():
            first = make()
            second = make()
            third = rerun(first)
            self.assertEqual(first["receipt_sha256"], second["receipt_sha256"], make.__name__)
            self.assertTrue(third.get("replay_of_existing_receipt"), make.__name__)
        # a different proposal is not a replay
        r = step(SyntheticTarget(PREFIX), ScriptedDrafter([truth[0]]),
                 receipts=[committed()])
        self.assertFalse(r.get("replay_of_existing_receipt", False))

    def test_receipt_fields_present(self):
        t = SyntheticTarget(PREFIX)
        r = step(t, ScriptedDrafter(t.greedy_continuation(4)[:4]))
        for key in ("schema", "target_identity", "drafter_identity", "proposal",
                    "per_position_decisions", "proposed_length",
                    "target_verified_prefix_length", "committed_length",
                    "rollback_performed", "state_transition", "state_hash_before",
                    "state_hash_after", "wall_seconds", "terminal_status",
                    "receipt_sha256"):
            self.assertIn(key, r)
        self.assertEqual(r["schema"], C.RECEIPT_SCHEMA_V2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
