"""
Load lenses from a sealed AXM Genesis lens shard — deterministically, zero-dep.

The shard (built by `memory/lenses/build_lens_shard.py`) is the sovereign,
signed, tamper-evident form of the lens registry. This reads the lenses back at
query time with **stdlib only** — no model, no axm import on the hot path. The
kernel's job was to *seal and verify*; reading the sealed content back is plain
deterministic parsing. That's the AXM shape: LLM (or a validator) at compile
time, deterministic query at read time.

    from capability_harness.lens_shard import load_lenses
    from capability_harness import review
    lenses = load_lenses("memory/lenses/shard")          # reconstructs the registry
    review(code, call, lenses=lenses)

Integrity is a separate, stronger guarantee — run it whenever you want proof the
shard is untampered (needs the axm toolchain):

    axm-verify shard memory/lenses/shard --trusted-key memory/lenses/shard/sig/publisher.pub

`load_lenses(..., verify=True)` will shell out to `axm-verify` first if it is on
PATH and refuse to load a shard that does not PASS.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .uplift import Lens

_INSTR = "instruction: "
_HEAD = "[lens "


def verify_shard(shard_dir: str | Path) -> bool:
    """Run `axm-verify` if available; True on PASS. Raises if axm present but FAIL."""
    if not shutil.which("axm-verify"):
        return False  # toolchain absent — caller decides whether that's acceptable
    shard = Path(shard_dir)
    pub = shard / "sig" / "publisher.pub"
    cmd = ["axm-verify", "shard", str(shard)]
    if pub.exists():
        cmd += ["--trusted-key", str(pub)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"shard failed verification: {r.stdout.strip() or r.stderr.strip()}")
    return True


def load_lenses(shard_dir: str | Path, verify: bool = False) -> list[Lens]:
    """Reconstruct the lens list from a sealed shard's committed source.

    With verify=True and axm-verify on PATH, the shard must PASS first — a
    tampered shard raises instead of loading."""
    shard = Path(shard_dir)
    if verify:
        verify_shard(shard)
    text = (shard / "content" / "source.txt").read_text(encoding="utf-8")
    lenses: list[Lens] = []
    key: str | None = None
    for line in text.splitlines():
        if line.startswith(_HEAD):
            key = line[len(_HEAD):].split("]", 1)[0].split()[0]
        elif key and line.startswith(_INSTR):
            lenses.append(Lens(key, line[len(_INSTR):]))
            key = None
    return lenses
