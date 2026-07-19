# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=harness\rig.py  mutation_score=4/9
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "harness"))

import builtins
import io
from contextlib import contextmanager

from rig import (
    RIG_LADDER,
    Rig,
    amd_gpus,
    current_rung,
    detect_rig,
    fits,
    gb_needed,
    is_apple_silicon,
    max_params_b,
    nvidia_gpus,
    next_rungs,
    system_ram_gb,
)
import rig


_MISSING = object()


@contextmanager


def _with_patches(*entries):
    old = []
    for obj, name, value in entries:
        had = hasattr(obj, name)
        old_value = getattr(obj, name, _MISSING)
        old.append((obj, name, had, old_value))
        setattr(obj, name, value)
    try:
        yield
    finally:
        for obj, name, had, old_value in reversed(old):
            if had:
                setattr(obj, name, old_value)
            else:
                delattr(obj, name)


def _patches(*entries):
    return _with_patches(*entries)


def test_system_ram_gb_reads_proc():
    meminfo = "MemTotal:       16777216 kB\n"
    fake_file = io.StringIO(meminfo)

    with _patches((builtins, "open", lambda *_args, **_kwargs: fake_file)):
        assert system_ram_gb() == 16.0


def test_system_ram_gb_sysctl_fallback():
    def _fake_open(*_args, **_kwargs):
        raise OSError("no proc")

    with _patches(
        (builtins, "open", _fake_open),
        (rig, "_run", lambda *_args, **_kwargs: "8589934592\n"),
    ):
        assert system_ram_gb() == 8.0


def test_system_ram_gb_sysconf_fallback():
    def _fake_open(*_args, **_kwargs):
        raise OSError("no proc")

    def _fake_sysconf(name):
        if name == "SC_PHYS_PAGES":
            return 10_000_000
        if name == "SC_PAGE_SIZE":
            return 4096
        raise ValueError("unexpected sysconf name")

    with _patches(
        (builtins, "open", _fake_open),
        (rig, "_run", lambda *_args, **_kwargs: None),
        (rig.os, "sysconf", _fake_sysconf),
    ):
        assert system_ram_gb() == 38.1


def test_system_ram_gb_all_fail_returns_none():
    def _fake_open(*_args, **_kwargs):
        raise OSError("no proc")

    def _fake_sysconf(_name):
        raise AttributeError("no sysconf")

    with _patches(
        (builtins, "open", _fake_open),
        (rig, "_run", lambda *_args, **_kwargs: None),
        (rig.os, "sysconf", _fake_sysconf),
    ):
        assert system_ram_gb() is None


def test_nvidia_gpus_parses_csv_lines():
    with _patches(
        (rig, "_run", lambda *_args, **_kwargs: "A100 SXM4, 24576\nfoo, bad\n"),
    ):
        assert nvidia_gpus() == [{"name": "A100 SXM4", "vram_gb": 24.0}]


def test_nvidia_gpus_empty_when_blank():
    with _patches((rig, "_run", lambda *_args, **_kwargs: "")):
        assert nvidia_gpus() == []


def test_amd_gpus_parses_csv_rows():
    with _patches(
        (
            rig,
            "_run",
            lambda *_args, **_kwargs: "card0, 4294967296, 100\nignored, 1, 2\n",
        )
    ):
        assert amd_gpus() == [{"name": "card0", "vram_gb": 4.0}]


def test_is_apple_silicon_true():
    with _patches(
        (rig.platform, "system", lambda: "Darwin"),
        (rig.platform, "machine", lambda: "arm64"),
    ):
        assert is_apple_silicon() is True


def test_is_apple_silicon_false():
    with _patches(
        (rig.platform, "system", lambda: "Linux"),
        (rig.platform, "machine", lambda: "x86_64"),
    ):
        assert is_apple_silicon() is False


def test_rig_properties_without_gpu_cpu_path():
    rig_obj = Rig(ram_gb=16.0, cpu_cores=4, gpus=[])
    assert rig_obj.vram_gb == 0.0
    assert rig_obj.usable_gb == 10.4
    assert rig_obj.compute_class == "CPU laptop/desktop"


def test_rig_properties_gpu_and_multi_gpu_class():
    rig_obj = Rig(
        ram_gb=12.0,
        cpu_cores=8,
        gpus=[{"name": "x", "vram_gb": 10.0}, {"name": "y", "vram_gb": 8.0}],
    )
    assert rig_obj.vram_gb == 18.0
    assert rig_obj.usable_gb == 17.1
    assert rig_obj.compute_class == "multi-GPU server"


def test_rig_compute_class_large_cpu_and_unified():
    assert Rig(ram_gb=64.0, cpu_cores=4, gpus=[]).compute_class == "CPU server / big workstation"
    assert (
        Rig(ram_gb=32.0, cpu_cores=4, gpus=[], unified_memory=True).compute_class
        == "unified-memory laptop/desktop (Apple silicon class)"
    )


def test_detect_rig_prefers_nvidia_over_amd_and_uses_system_values():
    with _patches(
        (rig, "system_ram_gb", lambda: 64.0),
        (rig, "nvidia_gpus", lambda: [{"name": "A100", "vram_gb": 80.0}]),
        (rig, "amd_gpus", lambda: [{"name": "Vega", "vram_gb": 16.0}]),
        (rig.os, "cpu_count", lambda: 16),
        (rig, "is_apple_silicon", lambda: False),
    ):
        detected = detect_rig()
        assert detected.ram_gb == 64.0
        assert detected.cpu_cores == 16
        assert detected.gpus == [{"name": "A100", "vram_gb": 80.0}]
        assert detected.usable_gb == 76.0


def test_detect_rig_uses_amd_if_nvidia_empty():
    with _patches(
        (rig, "system_ram_gb", lambda: 16.0),
        (rig, "nvidia_gpus", lambda: []),
        (rig, "amd_gpus", lambda: [{"name": "card0", "vram_gb": 8.0}]),
        (rig.os, "cpu_count", lambda: 8),
        (rig, "is_apple_silicon", lambda: True),
    ):
        detected = detect_rig()
        assert detected.unified_memory is True
        assert detected.gpus == [{"name": "card0", "vram_gb": 8.0}]
        assert detected.compute_class == "GPU workstation"


def test_gb_needed_and_max_params_b_inverse_boundary():
    assert gb_needed(0) == 1.5
    assert gb_needed(10.0) == 8.5
    assert max_params_b(8.5) == 10.0
    assert max_params_b(0.0) == 0.0


def test_fits_true_false():
    rig_obj = Rig(ram_gb=20.0, cpu_cores=4, gpus=[])
    assert fits(10.0, rig_obj) is True
    assert fits(18.0, rig_obj) is False


def test_current_rung_and_next_rungs():
    low = Rig(ram_gb=4.9, cpu_cores=2, gpus=[])
    mid = Rig(ram_gb=24.0, cpu_cores=8, gpus=[])
    maxed = Rig(ram_gb=500.0, cpu_cores=64, gpus=[{"name": "x", "vram_gb": 1_000.0}])

    assert current_rung(low) == -1
    assert current_rung(mid) == 2
    assert current_rung(maxed) == len(RIG_LADDER) - 1

    assert next_rungs(low, count=2) == RIG_LADDER[:2]
    assert next_rungs(mid, count=2) == RIG_LADDER[3:5]
    assert next_rungs(maxed, count=3) == []


def main():
    test_system_ram_gb_reads_proc()
    test_system_ram_gb_sysctl_fallback()
    test_system_ram_gb_sysconf_fallback()
    test_system_ram_gb_all_fail_returns_none()
    test_nvidia_gpus_parses_csv_lines()
    test_nvidia_gpus_empty_when_blank()
    test_amd_gpus_parses_csv_rows()
    test_is_apple_silicon_true()
    test_is_apple_silicon_false()
    test_rig_properties_without_gpu_cpu_path()
    test_rig_properties_gpu_and_multi_gpu_class()
    test_rig_compute_class_large_cpu_and_unified()
    test_detect_rig_prefers_nvidia_over_amd_and_uses_system_values()
    test_detect_rig_uses_amd_if_nvidia_empty()
    test_gb_needed_and_max_params_b_inverse_boundary()
    test_fits_true_false()
    test_current_rung_and_next_rungs()
    print("OK")


if __name__ == "__main__":
    main()
