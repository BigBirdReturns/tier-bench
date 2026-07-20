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


def sidecar_path(shard_dir: str | Path) -> Path:
    return Path(shard_dir).parent / (Path(shard_dir).name + ".sha256")


def _rel_key(f: Path, shard: Path) -> str:
    """Canonical sidecar key: POSIX separators regardless of host OS, so a
    sidecar written on one platform verifies on another."""
    return f.relative_to(shard).as_posix()


def write_sidecar(shard_dir: str | Path) -> Path:
    """Record sha256 of every shard file. Generated only after a GOLD axm-verify
    PASS, so the sidecar is anchored to a cryptographically verified state."""
    import hashlib
    shard = Path(shard_dir)
    lines = []
    for f in sorted(shard.rglob("*")):
        if f.is_file():
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"{h}  {_rel_key(f, shard)}")
    out = sidecar_path(shard)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def check_sidecar(shard_dir: str | Path) -> bool:
    """Stdlib consistency check: every shard file matches the committed sidecar.
    WEAKER than axm-verify (relies on git for authenticity of the sidecar itself;
    no signature or Merkle proof) — but real: any in-place byte change to the
    shard that doesn't also rewrite the sidecar fails closed.

    Bytes are hashed raw — a CRLF rewrite IS a mismatch and stays one (the
    .gitattributes `-text` pin is what keeps checkouts byte-exact). When the
    mismatch is explainable purely by line endings, the error names that so a
    stale autocrlf checkout is diagnosable without weakening the check."""
    import hashlib
    shard = Path(shard_dir)
    sc = sidecar_path(shard)
    if not sc.exists():
        raise FileNotFoundError(f"sidecar missing: {sc}")
    want = {}
    for line in sc.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, _, rel = line.partition("  ")
            # legacy sidecars written on Windows before the key was canonicalized
            want[rel.replace("\\", "/")] = h
    files = {_rel_key(f, shard): f for f in sorted(shard.rglob("*")) if f.is_file()}
    have = {k: hashlib.sha256(f.read_bytes()).hexdigest() for k, f in files.items()}
    if have != want:
        diff = {k for k in set(want) | set(have) if want.get(k) != have.get(k)}
        crlf_only = all(
            k in files and k in want
            and hashlib.sha256(files[k].read_bytes().replace(b"\r\n", b"\n")).hexdigest() == want[k]
            for k in diff
        )
        hint = (" (every differing file matches after CRLF->LF: this is a git "
                "autocrlf checkout, not tampering — re-checkout the shard with "
                "the .gitattributes -text pin in place)") if crlf_only else ""
        raise ValueError(f"sidecar mismatch on: {sorted(diff)}{hint}")
    return True


def check(shard_dir: str | Path) -> tuple[str, bool]:
    """Tiered integrity check. Returns (level, ok):
      ('gold', True)    — axm-verify cryptographic PASS (Merkle + signature)
      ('sidecar', True) — toolchain absent; stdlib sha256 consistency PASS
    Raises on any actual mismatch at either level. The level is part of the
    result on purpose: 'verified' without saying HOW is an unnamed gap."""
    if shutil.which("axm-verify"):
        return ("gold", verify_shard(shard_dir))
    return ("sidecar", check_sidecar(shard_dir))


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


if __name__ == "__main__":
    import sys
    shard = sys.argv[1] if len(sys.argv) > 1 else "memory/lenses/shard"
    if "--write-sidecar" in sys.argv:
        # only regenerate after a gold PASS — enforced here, not by convention
        level, ok = ("gold", verify_shard(shard)) if __import__("shutil").which("axm-verify") else ("none", False)
        if level != "gold" or not ok:
            raise SystemExit("REFUSED: sidecar may only be written after a gold axm-verify PASS "
                             "(toolchain missing or verification failed)")
        p = write_sidecar(shard)
        print(f"gold PASS -> sidecar written: {p}")
        raise SystemExit(0)
    level, ok = check(shard)
    n = len(load_lenses(shard))
    print(f"lens shard integrity: {level.upper()} {'PASS' if ok else 'FAIL'} · {n} lenses loaded")
    if level == "sidecar":
        print("note: cryptographic (Merkle+signature) verification UNMEASURED in this "
              "environment — axm-verify not on PATH. Sidecar = sha256 consistency vs the "
              "committed record, anchored to a gold PASS at seal time. Gap named per "
              "docs/burden-discipline.md.")
    raise SystemExit(0 if ok else 1)
