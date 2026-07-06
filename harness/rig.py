"""Rig detection and local-model sizing.

Answers "what can THIS machine run, and what's the next upgrade rung?"
without any third-party dependencies. Probes are best-effort subprocess /
procfs reads that degrade to None rather than crashing — the report must
work on a bare laptop, a headless server, and everything between.

Sizing heuristics follow what the local-inference projects publish rather
than inventing anything:
  - Q4_K_M quantization ≈ 4.7 bits/param ≈ 0.6 GB per B params for the
    weights alone (llama.cpp quantization tables).
  - Ollama's model-library guidance: ~8 GB RAM for 7B, 16 GB for 13B,
    32 GB for 33B, 64 GB for 70B — i.e. weights plus KV-cache/runtime
    overhead lands near params_B * 0.7 + 1.5 GB at Q4 with modest context.
  - Dedicated VRAM is nearly all usable (~95%); Apple-silicon unified
    memory allows roughly 3/4 for the GPU; CPU-only inference should leave
    ~35% of system RAM for the OS and the KV cache growing with context.

Model parameter counts live in models.json ("params_B" on local entries):
data, not code, so the registry keeps working as models churn.
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field


# ─── Probes (best-effort, dependency-free) ───────────────────────────

def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except Exception:
        return None


def system_ram_gb() -> float | None:
    """Total system RAM in GB (Linux /proc/meminfo, macOS sysctl, POSIX fallback)."""
    try:
        meminfo = open("/proc/meminfo", encoding="utf-8").read()
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    out = _run(["sysctl", "-n", "hw.memsize"])
    if out and out.strip().isdigit():
        return round(int(out.strip()) / 1024**3, 1)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page_size / 1024**3, 1)
    except (ValueError, OSError, AttributeError):
        return None


def nvidia_gpus() -> list[dict]:
    """[{name, vram_gb}] via nvidia-smi; empty list when absent."""
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits"])
    gpus = []
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                gpus.append({"name": parts[0], "vram_gb": round(float(parts[1]) / 1024, 1)})
            except ValueError:
                continue
    return gpus


def amd_gpus() -> list[dict]:
    """Best-effort ROCm probe; empty list when absent."""
    out = _run(["rocm-smi", "--showmeminfo", "vram", "--csv"])
    gpus = []
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        # rocm-smi CSV: device, VRAM Total Memory (B), VRAM Total Used Memory (B)
        if len(parts) >= 2 and parts[0].lower().startswith("card"):
            try:
                gpus.append({"name": parts[0], "vram_gb": round(float(parts[1]) / 1024**3, 1)})
            except ValueError:
                continue
    return gpus


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")


@dataclass
class Rig:
    ram_gb: float | None
    cpu_cores: int | None
    gpus: list[dict] = field(default_factory=list)
    unified_memory: bool = False

    @property
    def vram_gb(self) -> float:
        return round(sum(g.get("vram_gb", 0) for g in self.gpus), 1)

    @property
    def usable_gb(self) -> float:
        """Memory realistically available to model weights + KV cache."""
        if self.gpus:
            return round(self.vram_gb * 0.95, 1)
        if self.unified_memory and self.ram_gb:
            return round(self.ram_gb * 0.75, 1)
        if self.ram_gb:
            return round(self.ram_gb * 0.65, 1)
        return 0.0

    @property
    def compute_class(self) -> str:
        n = len(self.gpus)
        if n >= 4:
            return "server farm (multi-GPU node)"
        if n >= 2:
            return "multi-GPU server"
        if n == 1:
            return "GPU workstation"
        if self.unified_memory:
            return "unified-memory laptop/desktop (Apple silicon class)"
        if (self.ram_gb or 0) >= 48:
            return "CPU server / big workstation"
        return "CPU laptop/desktop"


def detect_rig() -> Rig:
    gpus = nvidia_gpus() or amd_gpus()
    return Rig(
        ram_gb=system_ram_gb(),
        cpu_cores=os.cpu_count(),
        gpus=gpus,
        unified_memory=is_apple_silicon(),
    )


# ─── Sizing ──────────────────────────────────────────────────────────

def gb_needed(params_b: float) -> float:
    """Approx. memory to run a params_b-billion model at Q4 with modest
    context: weights (~0.6 GB/B) + KV cache & runtime (~1.5 GB)."""
    return round(params_b * 0.7 + 1.5, 1)


def max_params_b(usable_gb: float) -> float:
    """Inverse of gb_needed: the largest Q4 model this memory can hold."""
    return max(round((usable_gb - 1.5) / 0.7, 1), 0.0)


def fits(params_b: float, rig: Rig) -> bool:
    return gb_needed(params_b) <= rig.usable_gb


# ─── The upgrade ladder ──────────────────────────────────────────────
# Rungs are MEMORY classes, deliberately free of vendor names and prices —
# hardware SKUs churn as fast as models, memory classes don't. Each rung is
# (usable_gb, label, how you typically get there).

RIG_LADDER: list[tuple[float, str, str]] = [
    (5.0,   "entry laptop",          "any machine with ~8 GB RAM, CPU-only"),
    (10.0,  "typical laptop",        "16 GB RAM, CPU-only — slow but real"),
    (11.5,  "small-GPU desktop",     "a single 12 GB-class GPU"),
    (22.5,  "enthusiast GPU",        "a single 24 GB-class GPU, or 32 GB unified memory"),
    (45.0,  "dual-GPU workstation",  "2 x 24 GB GPUs, or 64 GB unified memory"),
    (75.0,  "pro workstation",       "an 80 GB-class GPU, or 96-128 GB unified memory"),
    (150.0, "server node",           "2 x 80 GB-class GPUs"),
    (300.0, "server farm rung",      "4-8 x 80 GB-class GPUs (tensor parallel)"),
]


def current_rung(rig: Rig) -> int:
    """Index of the highest rung this rig has reached (-1 = below the ladder)."""
    idx = -1
    for i, (usable, _, _) in enumerate(RIG_LADDER):
        if rig.usable_gb >= usable:
            idx = i
    return idx


def next_rungs(rig: Rig, count: int = 2) -> list[tuple[float, str, str]]:
    return RIG_LADDER[current_rung(rig) + 1: current_rung(rig) + 1 + count]
