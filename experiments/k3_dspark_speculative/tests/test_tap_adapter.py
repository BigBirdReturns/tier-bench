"""Tap-adapter inertness proofs.

Proves, against a stand-in runner module with the same layer-function surface
as run_cached_continuation (and real torch tensors), that:
  1. never-installed  -> module untouched;
  2. installed but disabled -> outputs and state hashes bit-identical;
  3. installed and ENABLED  -> outputs and state hashes STILL bit-identical
     (observation must not perturb the compute path);
  4. uninstall restores the exact original function objects;
  5. captures carry hash/shape/dtype/layer/token/location coordinates.

Requires torch (run under the gpu-venv interpreter). No K3 weights are read.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch

from k3_dspark_speculative.tap_adapter import TapSession, TapSpec, tensor_sha256

TAPS = tuple(TapSpec(layer=l, location="post", declared_as=f"tap {l}") for l in (2, 23, 47, 71, 89))


def make_runner_module() -> types.ModuleType:
    """Deterministic stand-in with run_cached_continuation's layer signature."""
    mod = types.ModuleType("fake_runner")

    def run_dense_layer(*, hidden_states, block_residual, **kwargs):
        out = hidden_states * 1.5 + 0.25
        return out, block_residual + 1.0, hidden_states.mean(), {"cache": 0}, {"kind": "dense"}

    def run_moe_layer(*, layer, hidden_states, block_residual, **kwargs):
        out = hidden_states * (1.0 + 0.01 * layer) + block_residual.mean()
        return out, block_residual * 0.9, hidden_states.mean(), [layer], [1.0], {"cache": layer}, {"kind": "moe"}

    mod.run_dense_layer = run_dense_layer
    mod.run_moe_layer = run_moe_layer
    return mod


def traverse(mod, layers=93):
    torch.manual_seed(7)
    hidden = torch.randn(1, 4, 8, dtype=torch.float32).to(torch.bfloat16)
    block = torch.zeros(1, 4, 8, dtype=torch.bfloat16)
    outputs = []
    for layer in range(layers):
        if layer == 0:
            out, block, *_ = mod.run_dense_layer(hidden_states=hidden, block_residual=block)
        else:
            out, block, *_ = mod.run_moe_layer(layer=layer, hidden_states=hidden, block_residual=block)
        hidden = out
        outputs.append(tensor_sha256(out))
    return outputs, tensor_sha256(hidden), tensor_sha256(block)


class TapAdapterInertness(unittest.TestCase):
    def test_baseline_deterministic(self):
        self.assertEqual(traverse(make_runner_module()), traverse(make_runner_module()))

    def test_disabled_session_is_inert(self):
        baseline = traverse(make_runner_module())
        mod = make_runner_module()
        session = TapSession(specs=TAPS, enabled=False).install(mod)
        result = traverse(mod)
        session.uninstall()
        self.assertEqual(result, baseline)
        self.assertEqual(session.captures, [])

    def test_enabled_session_does_not_change_outputs(self):
        baseline = traverse(make_runner_module())
        mod = make_runner_module()
        with TapSession(specs=TAPS, enabled=True).install(mod) as session:
            result = traverse(mod)
        self.assertEqual(result, baseline)
        self.assertEqual(len(session.captures), 5)

    def test_uninstall_restores_original_function_objects(self):
        mod = make_runner_module()
        dense, moe = mod.run_dense_layer, mod.run_moe_layer
        session = TapSession(specs=TAPS).install(mod)
        self.assertNotEqual(mod.run_moe_layer, moe)
        session.uninstall()
        self.assertIs(mod.run_dense_layer, dense)
        self.assertIs(mod.run_moe_layer, moe)

    def test_never_installed_module_untouched(self):
        mod = make_runner_module()
        dense, moe = mod.run_dense_layer, mod.run_moe_layer
        TapSession(specs=TAPS)  # constructed but never installed
        self.assertIs(mod.run_dense_layer, dense)
        self.assertIs(mod.run_moe_layer, moe)

    def test_capture_coordinates_and_hashes(self):
        mod = make_runner_module()
        with TapSession(specs=TAPS, enabled=True).install(mod) as session:
            traverse(mod)
        layers = [c["layer"] for c in session.captures]
        self.assertEqual(layers, [2, 23, 47, 71, 89])
        for c in session.captures:
            self.assertEqual(c["location"], "post")
            self.assertEqual(c["shape"], [1, 4, 8])
            self.assertEqual(c["dtype"], "torch.bfloat16")
            self.assertEqual(c["token_axis"], 1)
            self.assertEqual(c["token_count"], 4)
            self.assertEqual(len(c["sha256"]), 64)
        receipt = session.receipt()
        self.assertEqual(receipt["schema"], "octopodes/k3-dspark-tap-capture@1")
        self.assertEqual(len(receipt["captures"]), 5)

    def test_pre_location_capture(self):
        mod = make_runner_module()
        spec = (TapSpec(layer=2, location="pre"), TapSpec(layer=2, location="post"))
        with TapSession(specs=spec, enabled=True).install(mod) as session:
            traverse(mod, layers=4)
        self.assertEqual([(c["layer"], c["location"]) for c in session.captures],
                         [(2, "pre"), (2, "post")])
        self.assertNotEqual(session.captures[0]["sha256"], session.captures[1]["sha256"])

    def test_double_install_refused(self):
        mod = make_runner_module()
        session = TapSession(specs=TAPS).install(mod)
        with self.assertRaises(RuntimeError):
            session.install(mod)
        session.uninstall()


class MixtureTaps(unittest.TestCase):
    MIX = (TapSpec(layer=23, location="mixture", declared_as="tap 23 mixture"),)

    def test_mixture_requires_fn(self):
        with self.assertRaises(RuntimeError):
            TapSession(specs=self.MIX).install(make_runner_module())

    def test_mixture_computed_and_recorded_without_changing_outputs(self):
        baseline = traverse(make_runner_module())
        calls = []

        def fake_mixture(layer, prefix, kwargs):
            calls.append((layer, sorted(kwargs)))
            return prefix.detach() * 2.0  # derived value; live tensors untouched

        mod = make_runner_module()
        with TapSession(specs=self.MIX, enabled=True, mixture_fn=fake_mixture).install(mod) as s:
            result = traverse(mod)
        self.assertEqual(result, baseline)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 23)
        self.assertIn("block_residual", calls[0][1])
        self.assertEqual([c["location"] for c in s.captures], ["mixture"])
        # derived tensor hashes differently from the raw prefix
        mod2 = make_runner_module()
        with TapSession(specs=(TapSpec(layer=23, location="pre"),), enabled=True).install(mod2) as s2:
            traverse(mod2)
        self.assertNotEqual(s.captures[0]["sha256"], s2.captures[0]["sha256"])

    def test_disabled_mixture_never_calls_fn(self):
        calls = []
        mod = make_runner_module()
        with TapSession(specs=self.MIX, enabled=False,
                        mixture_fn=lambda *a: calls.append(a)).install(mod):
            traverse(mod)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
