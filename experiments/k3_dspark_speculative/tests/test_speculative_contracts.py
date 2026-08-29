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

    @staticmethod
    def _decisions(flags):
        return [{"position": i, "proposed": 1, "target_pick": 1 if f else 2,
                 "accepted": f} for i, f in enumerate(flags)]

    def _mint(self, **overrides):
        kwargs = dict(
            target_identity={}, drafter_identity={}, proposal={"tokens": [1, 2, 3]},
            verification={"accepted_length": 3,
                          "decisions": self._decisions([True, True, True])},
            snapshot_hash="a" * 64, final_state_hash="b" * 64,
            proposed_length=3, target_verified_prefix_length=3,
            committed_length=3, rollback_performed=False,
            state_transition="committed", bytes_read=None,
            wall_seconds=0.0, thermal=None, terminal_status="ok",
        )
        kwargs.update(overrides)
        return C.receipt_speculative_step(**kwargs)

    def test_the_v1_contradiction_is_impossible(self):
        """failed:commit + committed_length > 0 must be unconstructable."""
        with self.assertRaises(C.SpecStepError):
            self._mint(final_state_hash="a" * 64, rollback_performed=True,
                       state_transition="rolled_back",
                       terminal_status="failed:commit")

    def test_committed_cannot_exceed_verified(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(
                proposal={"tokens": [1, 2]}, proposed_length=2,
                verification={"accepted_length": 1,
                              "decisions": self._decisions([True, False])},
                target_verified_prefix_length=1, committed_length=2)

    def test_rolled_back_requires_hash_restoration(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(
                proposal={"tokens": [1]}, proposed_length=1,
                verification={"accepted_length": 0,
                              "decisions": self._decisions([False])},
                target_verified_prefix_length=0, committed_length=0,
                rollback_performed=True, state_transition="rolled_back")

    def test_external_receipt_verified_beyond_proposal_refused(self):
        """The exact review example: proposed 1, verified 2, rolled back."""
        with self.assertRaises(C.SpecStepError) as ctx:
            self._mint(
                proposal={"tokens": [1]}, proposed_length=1,
                verification={"accepted_length": 2,
                              "decisions": self._decisions([True])},
                target_verified_prefix_length=2, committed_length=0,
                rollback_performed=True, state_transition="rolled_back",
                final_state_hash="a" * 64, terminal_status="failed:commit")
        self.assertIn("target_verified_prefix_length", str(ctx.exception))

    def test_decision_count_must_equal_proposed_length(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(verification={"accepted_length": 3,
                                     "decisions": self._decisions([True, True])})

    def test_accepted_decisions_must_be_contiguous_prefix(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(verification={
                "accepted_length": 3,
                "decisions": self._decisions([True, False, True])})

    def test_prefix_length_must_equal_verified(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(verification={
                "accepted_length": 3,
                "decisions": self._decisions([True, True, False])})

    def test_verified_without_decisions_refused(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(verification=None)

    def test_rollback_performed_conflicts_with_committed_transition(self):
        with self.assertRaises(C.SpecStepError):
            self._mint(rollback_performed=True)

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


class StateDenominatorWitnesses(unittest.TestCase):
    """2.1 witnesses: the exported-state key set is EXACTLY the five
    components. Every mutation refuses before a receipt is minted."""

    def base_state(self):
        return SyntheticTarget(PREFIX).export_state()

    def assert_state_refused(self, state):
        with self.assertRaises(C.SpecStepError) as ctx:
            C.state_root_sha256(state)
        self.assertEqual(ctx.exception.stage, "state_manifest")

    def test_unknown_sixth_state_key(self):
        s = self.base_state()
        s["aux"] = {"anything": 1}
        self.assert_state_refused(s)

    def test_extra_rng_state(self):
        s = self.base_state()
        s["rng"] = b"\x00" * 16
        self.assert_state_refused(s)

    def test_extra_cache_object(self):
        s = self.base_state()
        s["expert_cache"] = {"layer0": [1, 2, 3]}
        self.assert_state_refused(s)

    def test_missing_known_key(self):
        s = self.base_state()
        del s["mla"]
        self.assert_state_refused(s)

    def test_renamed_known_key(self):
        s = self.base_state()
        s["kda_v2"] = s.pop("kda")
        self.assert_state_refused(s)

    def test_additional_key_with_unsupported_object(self):
        s = self.base_state()
        s["extra"] = object()
        self.assert_state_refused(s)

    @unittest.skipUnless(torch is not None, "torch required")
    def test_additional_key_with_valid_tensor(self):
        s = self.base_state()
        s["extra"] = torch.ones(4)
        self.assert_state_refused(s)

    def test_refusal_happens_before_receipt_minting(self):
        """A target exporting a sixth key fails closed inside the step - no
        receipt object is ever returned."""
        class ExtraStateTarget(SyntheticTarget):
            def export_state(self):
                s = super().export_state()
                s["adapter_scratch"] = [0.0]
                return s
        with self.assertRaises(C.SpecStepError):
            step(ExtraStateTarget(PREFIX), ScriptedDrafter([1]))

    @unittest.skipUnless(torch is not None, "torch required")
    def test_extra_valid_tensor_no_longer_shares_the_root(self):
        """Fresh review evidence rebutted: an added component can no longer
        produce the same state_hash - it refuses outright."""
        s = self.base_state()
        baseline = C.state_root_sha256(dict(s))
        s["extra"] = torch.ones(4)
        with self.assertRaises(C.SpecStepError):
            C.state_root_sha256(s)
        self.assertEqual(baseline, C.state_root_sha256(self.base_state()))


class FixedRowsTarget(SyntheticTarget):
    def __init__(self, prefix, rows):
        super().__init__(prefix)
        self._rows = rows

    def block_logits(self, proposed_tokens):
        return self._rows


class LogitValidityWitnesses(unittest.TestCase):
    """2.2 witnesses: non-finite / malformed target logits must fail
    verification, never silently pick a different finite token."""

    NAN = float("nan")
    INF = float("inf")

    def assert_row_refused(self, rows, proposed, fragment=""):
        t = FixedRowsTarget(PREFIX, rows)
        before = C.state_hash(t.export_state())
        r = step(t, ScriptedDrafter(proposed))
        self.assertEqual(r["terminal_status"], "failed:verify")
        self.assertEqual(r["committed_length"], 0)
        self.assertEqual(r["target_verified_prefix_length"], 0)
        self.assertEqual(C.state_hash(t.export_state()), before)
        return r

    def test_nan_row_review_example(self):
        # [1.0, NaN, 0.0] previously selected token 0 and committed it
        self.assert_row_refused([[1.0, self.NAN, 0.0]], [0])

    def test_positive_infinity_refused(self):
        self.assert_row_refused([[self.INF, 0.0, 0.0]], [0])

    def test_negative_infinity_refused(self):
        self.assert_row_refused([[0.0, -self.INF, 0.0]], [0])

    def test_empty_row_refused(self):
        self.assert_row_refused([[]], [0])

    def test_ragged_rows_refused(self):
        rows = [[1.0] * 16, [1.0] * 15]
        self.assert_row_refused(rows, [0, 1])

    def test_nonnumeric_entry_refused(self):
        self.assert_row_refused([[1.0, "x", 0.0]], [0])

    def test_bool_entry_refused(self):
        self.assert_row_refused([[1.0, True, 0.0]], [0])

    def test_vocab_dimension_enforced_when_declared(self):
        t = FixedRowsTarget(PREFIX, [[1.0] * 15])
        with self.assertRaises(C.SpecStepError) as ctx:
            C.verify_proposed_block(t, [0], vocab_size=16)
        self.assertIn("vocabulary dimension", str(ctx.exception))

    def test_decisions_retain_row_evidence(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(2)
        v = C.verify_proposed_block(t, truth[:2])
        for d in v["decisions"]:
            for key in ("target_pick", "proposed", "accepted", "top_logit",
                        "runner_up_logit", "margin", "logit_row_sha256",
                        "finite_valid"):
                self.assertIn(key, d)
            self.assertTrue(d["finite_valid"])
            self.assertEqual(len(d["logit_row_sha256"]), 64)
            self.assertGreaterEqual(d["margin"], 0.0)


class TelemetryDrafter:
    """A drafter whose proposal telemetry is malformed in exactly one way."""

    def __init__(self, tokens, **overrides):
        self.tokens = list(tokens)
        self.overrides = overrides

    def propose(self, aux_bundle, prefix):
        out = {"tokens": list(self.tokens),
               "scores": [0.0] * len(self.tokens),
               "confidence": 0.5}
        out.update(self.overrides)
        return out


class ProposalTelemetryWitnesses(unittest.TestCase):
    """Non-finite or malformed proposal telemetry must refuse BEFORE the target
    is verified or advanced - never after the state has already moved."""

    def _truth(self, n):
        return SyntheticTarget(PREFIX).greedy_continuation(n)

    def assert_refused_without_mutation(self, drafter, fragment):
        t = SyntheticTarget(PREFIX)
        before = C.state_hash(t.export_state())
        r = step(t, drafter)
        self.assertEqual(r["terminal_status"], "failed:draft")
        self.assertEqual(r["committed_length"], 0)
        self.assertEqual(r["target_verified_prefix_length"], 0)
        self.assertEqual(C.state_hash(t.export_state()), before)
        self.assertEqual(r["state_hash_after"], before)
        with self.assertRaises(C.SpecStepError) as ctx:
            C.draft_block(drafter, make_aux_bundle(LAYERS), PREFIX, LAYERS)
        self.assertIn(fragment, str(ctx.exception))

    def test_nan_score_refuses_before_verification(self):
        truth = self._truth(2)
        self.assert_refused_without_mutation(
            TelemetryDrafter(truth[:2], scores=[float("nan"), 0.0]), "non-finite")

    def test_inf_score_refuses(self):
        truth = self._truth(2)
        self.assert_refused_without_mutation(
            TelemetryDrafter(truth[:2], scores=[0.0, float("inf")]), "non-finite")

    def test_nan_confidence_refuses(self):
        truth = self._truth(1)
        self.assert_refused_without_mutation(
            TelemetryDrafter(truth[:1], confidence=float("nan")), "non-finite")

    def test_score_length_must_equal_token_length(self):
        truth = self._truth(3)
        self.assert_refused_without_mutation(
            TelemetryDrafter(truth[:3], scores=[0.0, 0.0]),
            "score length must equal proposal-token length")

    def test_float_token_id_refuses(self):
        truth = self._truth(1)
        self.assert_refused_without_mutation(
            TelemetryDrafter([float(truth[0])]), "not an integer token id")

    def test_bool_token_id_refuses(self):
        self.assert_refused_without_mutation(
            TelemetryDrafter([True]), "is a bool")

    def test_nonnumeric_confidence_refuses(self):
        truth = self._truth(1)
        self.assert_refused_without_mutation(
            TelemetryDrafter(truth[:1], confidence="high"), "not a real number")


class HostileIdentity(dict):
    """An identity block that canonicalises only the first time it is hashed."""

    def __init__(self):
        super().__init__(name="hostile")
        self.armed = False


class ReceiptConstructionCustodyWitnesses(unittest.TestCase):
    """The custody boundary must cover receipt construction itself: a step may
    never end with advanced target state and no receipt."""

    def test_receipt_failure_after_commit_restores_snapshot(self):
        t = SyntheticTarget(PREFIX)
        before = C.state_hash(t.export_state())
        truth = t.greedy_continuation(2)

        real = C.receipt_speculative_step
        calls = {"n": 0}

        def exploding(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("receipt serialization exploded")
            return real(**kwargs)

        C.receipt_speculative_step = exploding
        try:
            r = step(t, ScriptedDrafter(truth[:2]))
        finally:
            C.receipt_speculative_step = real

        # a receipt WAS emitted, the commit was undone, and nothing is claimed
        self.assertIsNotNone(r)
        self.assertIn("failed:receipt:RuntimeError", r["terminal_status"])
        self.assertEqual(r["committed_length"], 0)
        self.assertEqual(r["target_verified_prefix_length"], 0)
        self.assertEqual(r["state_transition"], "rolled_back")
        self.assertTrue(r["rollback_performed"])
        self.assertEqual(r["state_hash_after"], before)
        self.assertEqual(C.state_hash(t.export_state()), before)
        # the bounded receipt keeps the proposal tokens but drops telemetry
        self.assertTrue(r["proposal"]["bounded_failure_receipt"])
        self.assertEqual(r["proposal"]["tokens"], truth[:2])
        self.assertNotIn("scores", r["proposal"])
        self.assertEqual(r["proposed_length"], 2)
        self.assertEqual(len(r["receipt_sha256"]), 64)
        C.validate_speculative_receipt(r)

    def test_bounded_receipt_survives_noncanonical_identity(self):
        t = SyntheticTarget(PREFIX)
        truth = t.greedy_continuation(1)
        real = C.receipt_speculative_step
        calls = {"n": 0}

        def exploding(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(**kwargs)

        C.receipt_speculative_step = exploding
        try:
            r = C.speculative_step(
                target=t, drafter=ScriptedDrafter(truth[:1]),
                aux_bundle=make_aux_bundle(LAYERS), expected_layers=LAYERS,
                target_identity={"obj": object()},   # not canonical
                drafter_identity={"name": "scripted"},
            )
        finally:
            C.receipt_speculative_step = real
        self.assertTrue(r["target_identity"]["bounded"])
        C.validate_speculative_receipt(r)


class ExternalReceiptBindingWitnesses(unittest.TestCase):
    """Externally constructed receipts must bind proposed_length and every
    decision to the proposal's own tokens."""

    def base(self):
        return {
            "schema": C.RECEIPT_SCHEMA_V2,
            "proposal": {"tokens": [11, 12]},
            "per_position_decisions": [
                {"position": 0, "proposed": 11, "accepted": True},
                {"position": 1, "proposed": 12, "accepted": False},
            ],
            "proposed_length": 2,
            "target_verified_prefix_length": 1,
            "committed_length": 1,
            "rollback_performed": False,
            "state_transition": "committed",
            "state_hash_before": "a" * 64,
            "state_hash_after": "b" * 64,
            "terminal_status": "ok",
        }

    def refuse(self, mutate, fragment):
        r = self.base()
        mutate(r)
        with self.assertRaises(C.SpecStepError) as ctx:
            C.validate_speculative_receipt(r)
        self.assertIn(fragment, str(ctx.exception))

    def test_consistent_external_receipt_validates(self):
        C.validate_speculative_receipt(self.base())

    def test_proposed_length_must_equal_proposal_tokens(self):
        # the exact review witness: an EMPTY proposal claiming one committed token
        self.refuse(lambda r: r.update(proposal={"tokens": []}),
                    "must be derived from the proposal itself")

    def test_missing_proposal_refuses(self):
        self.refuse(lambda r: r.pop("proposal"), "not a mapping")

    def test_decision_naming_an_unproposed_token_refuses(self):
        self.refuse(
            lambda r: r["per_position_decisions"][1].update(proposed=999),
            "but the proposal carries")

    def test_reordered_decisions_refuse(self):
        def swap(r):
            r["per_position_decisions"] = list(reversed(r["per_position_decisions"]))
        self.refuse(swap, "decisions must be in proposal order")

    def test_duplicated_decision_refuses(self):
        def dup(r):
            r["per_position_decisions"] = [r["per_position_decisions"][0]] * 2
        self.refuse(dup, "decisions must be in proposal order")

    def test_decision_count_below_proposal_refuses(self):
        def drop(r):
            r["per_position_decisions"] = r["per_position_decisions"][:1]
        self.refuse(drop, "!= proposal-token count")

    def test_noninteger_proposal_token_refuses(self):
        self.refuse(lambda r: r.update(proposal={"tokens": [11, 12.0]}),
                    "not an int")


class AuxBundleAdmissionWitnesses(unittest.TestCase):
    """A bundle whose target run failed - or whose outcome is unbound - is not
    drafter input."""

    def refuse(self, bundle, fragment):
        with self.assertRaises(C.SpecStepError) as ctx:
            C.validate_aux_bundle(bundle, LAYERS)
        self.assertIn(fragment, str(ctx.exception))

    def test_successful_bundle_admits(self):
        C.validate_aux_bundle(make_aux_bundle(LAYERS), LAYERS)

    def test_unbound_outcome_refuses(self):
        b = make_aux_bundle(LAYERS)
        b.pop("target_run_return_code")
        self.refuse(b, "binds no target-run outcome")

    def test_nonzero_target_return_code_refuses(self):
        b = make_aux_bundle(LAYERS)
        b["target_run_return_code"] = 1
        self.refuse(b, "target run returned 1")

    def test_failed_terminal_status_refuses(self):
        b = make_aux_bundle(LAYERS)
        b["terminal_status"] = "failed:target_run_rc=1"
        self.refuse(b, "is not ok")

    def test_preserved_failure_artifact_refuses(self):
        b = make_aux_bundle(LAYERS)
        b["schema"] = C.FAILED_TAP_BUNDLE_SCHEMA
        b["terminal_status"] = "failed:target_run_rc=3"
        self.refuse(b, "preserved failure artifact")

    def test_failed_bundle_never_reaches_the_target(self):
        b = make_aux_bundle(LAYERS)
        b["target_run_return_code"] = 2
        t = SyntheticTarget(PREFIX)
        before = C.state_hash(t.export_state())
        r = step(t, ScriptedDrafter(t.greedy_continuation(1)), bundle=b)
        self.assertEqual(r["terminal_status"], "failed:aux_bundle")
        self.assertEqual(r["committed_length"], 0)
        self.assertEqual(C.state_hash(t.export_state()), before)


class SharedAdjudicationGateWitnesses(unittest.TestCase):
    """One gate, one greedy rule - the production ARM C path imports these."""

    def test_nan_row_refuses_instead_of_picking_a_finite_token(self):
        with self.assertRaises(C.SpecStepError) as ctx:
            C.adjudicate_logit_row([1.0, float("nan"), 0.0], 0, 0, vocab_size=3)
        self.assertIn("non-finite", str(ctx.exception))

    def test_dimension_mismatch_refuses(self):
        with self.assertRaises(C.SpecStepError) as ctx:
            C.adjudicate_logit_row([1.0, 0.0], 0, 0, vocab_size=3)
        self.assertIn("vocabulary dimension", str(ctx.exception))

    def test_decision_preserves_the_full_position_record(self):
        d, values = C.adjudicate_logit_row([0.5, 3.0, 1.0], 2, 1, vocab_size=3,
                                           accepted_so_far=2)
        self.assertEqual(d["target_pick"], 1)
        self.assertTrue(d["accepted"])
        self.assertEqual(d["proposed"], 1)
        self.assertEqual(d["vocab_dimension"], 3)
        self.assertEqual(d["top_logit"], 3.0)
        self.assertEqual(d["runner_up_logit"], 1.0)
        self.assertEqual(d["margin"], 2.0)
        self.assertTrue(d["finite_valid"])
        self.assertEqual(d["logit_row_sha256"],
                         C.logit_row_digest(values, 2))

    def test_greedy_pick_breaks_ties_on_the_lowest_index(self):
        self.assertEqual(C.greedy_pick([2.0, 2.0, 1.0]), 0)

    def test_row_digest_covers_every_element(self):
        a = C.logit_row_digest([1.0] * 64, 0)
        tail = [1.0] * 63 + [1.0000001]
        self.assertNotEqual(a, C.logit_row_digest(tail, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
