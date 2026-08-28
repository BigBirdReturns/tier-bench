"""Hostile witnesses for execution-bound resumable checkpoints.

A checkpoint may only be resumed inside the exact execution that created it.
Each witness reuses a valid checkpoint under one changed binding and requires
IncompatibleCheckpoint naming that binding as the first mismatch. Torch-only;
no runtime-slice or transformers import.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch  # noqa: E402

from k3_dspark_speculative import strict_checkpoint as SC  # noqa: E402

BASE = dict(
    runner_sha256="a" * 64,
    mode="SEQUENTIAL_WITHIN_LAYER_STRICT",
    model_index_sha256="b" * 64,
    parent_checkpoint_sha256="c" * 64,
    baseline_root_sha256="d" * 64,
    prefix_length=139,
    prefix_sha256="e" * 64,
    proposal_tokens=[12200, 636, 347],
    output_root_id=r"D:\runs\strict-d7",
)


def bindings(**overrides):
    kwargs = dict(BASE)
    kwargs.update(overrides)
    return SC.make_bindings(**kwargs)


def payload(binds, layer_done=5):
    return SC.make_checkpoint_payload(
        bindings=binds,
        layer_done=layer_done,
        hidden=[torch.ones(1, 1, 8), torch.zeros(1, 1, 8), torch.full((1, 1, 8), 2.0)],
        bank=[torch.ones(1, 2, 8), torch.zeros(1, 2, 8), torch.full((1, 2, 8), 3.0)],
        telemetry={"per_layer_wall_s": [1.0]},
        position_state_roots={"position-01/layer-005.pt": "f" * 64},
    )


class CheckpointBindingWitnesses(unittest.TestCase):
    def assert_refuses(self, saved_binds, expected_binds, binding_name):
        p = payload(saved_binds)
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, expected_binds)
        self.assertEqual(ctx.exception.binding, binding_name)

    def test_matching_execution_resumes(self):
        b = bindings()
        SC.validate_resume(payload(b), bindings())  # no exception

    def test_same_proposal_different_parent(self):
        self.assert_refuses(bindings(), bindings(parent_checkpoint_sha256="9" * 64),
                            "parent_checkpoint_sha256")

    def test_same_proposal_different_model(self):
        self.assert_refuses(bindings(), bindings(model_index_sha256="9" * 64),
                            "model_index_sha256")

    def test_same_tokens_different_prefix(self):
        self.assert_refuses(bindings(), bindings(prefix_sha256="9" * 64),
                            "prefix_sha256")

    def test_same_tokens_different_prefix_length(self):
        self.assert_refuses(bindings(), bindings(prefix_length=140), "prefix_length")

    def test_different_mode(self):
        self.assert_refuses(bindings(), bindings(mode="FAST_CHUNK_EXPERIMENTAL"),
                            "mode")

    def test_different_baseline(self):
        self.assert_refuses(bindings(), bindings(baseline_root_sha256="9" * 64),
                            "baseline_root_sha256")

    def test_changed_runner(self):
        self.assert_refuses(bindings(), bindings(runner_sha256="9" * 64),
                            "runner_sha256")

    def test_different_proposal_tokens(self):
        self.assert_refuses(bindings(), bindings(proposal_tokens=[12200, 636, 999]),
                            "proposal_sha256")

    def test_different_proposal_length(self):
        self.assert_refuses(bindings(), bindings(proposal_tokens=[12200, 636]),
                            "proposal_length")

    def test_different_output_root(self):
        self.assert_refuses(bindings(), bindings(output_root_id=r"D:\runs\other"),
                            "output_root_id")

    def test_tampered_hidden_carrier(self):
        b = bindings()
        p = payload(b)
        p["hidden"][1] = torch.full((1, 1, 8), 7.0)  # bytes changed, roots stale
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "carrier_roots.hidden")

    def test_tampered_bank_carrier(self):
        b = bindings()
        p = payload(b)
        p["bank"][0] = torch.full((1, 2, 8), 9.0)
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "carrier_roots.bank")

    def test_tampered_completed_layer_value(self):
        b = bindings()
        p = payload(b)
        p["layer_done"] = 42  # aggregate root no longer covers this value
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "aggregate_root_sha256")

    def test_tampered_position_state_roots(self):
        b = bindings()
        p = payload(b)
        p["position_state_roots"]["position-01/layer-005.pt"] = "0" * 64
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "aggregate_root_sha256")

    def test_negative_layer_done_refused(self):
        b = bindings()
        p = payload(b, layer_done=-1)
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "layer_done")

    def test_missing_bindings_object_refused(self):
        p = payload(bindings())
        del p["bindings"]
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "bindings")

    def test_schema_change_refused(self):
        b = bindings()
        p = payload(b)
        p["bindings"]["schema"] = "octopodes/k3-strict-traversal-checkpoint@1"
        with self.assertRaises(SC.IncompatibleCheckpoint) as ctx:
            SC.validate_resume(p, bindings())
        self.assertEqual(ctx.exception.binding, "schema")


if __name__ == "__main__":
    unittest.main(verbosity=2)
