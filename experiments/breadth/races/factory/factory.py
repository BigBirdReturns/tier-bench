"""Sediment factory: Spark authors -> hardened referee gates -> Luna blind-fair -> ledger.

Usage: python factory.py <batch_name> <n_packages>
Fully autonomous; appends one JSON line per package to ledger.jsonl.
"""
import ast
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

F = Path(__file__).resolve().parent
CLI = r"C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"
LEDGER = F / "ledger.jsonl"

SEED_FORBIDDEN = [
    "billing/anchor dates", "calendar arithmetic", "SQL NULL logic", "interest accrual",
    "discount stacking", "fee/overdraft processing", "backup retention", "interval merging",
    "remainder splitting", "deduplication", "partitioning order", "overlapping substrings",
    "competition ranking", "negative-base representation", "string rotation",
    "sandwich/adjacency counting", "circular extrema", "nearest-higher distance",
    "prefix routing", "relay propagation", "digital roots", "collatz", "LRU caches",
    "keyboard/capslock simulation", "pipelines with error policies", "double-entry ledgers",
    "access-level policies with amendments",
]

AUTHOR_BRIEF = """You are authoring ONE hidden-graded programming task package in the current directory.

Create exactly one directory <task_name>/ with exactly 4 files:
1. input.py - module docstring as COMPLETE contract (signature + numbered rules that alone determine every output for every input); stub `def <name>(...): raise NotImplementedError`; `def main():` with 3 visible asserts that ANY plausible implementation (correct or naively wrong) passes, ending print("OK"); __main__ guard.
2. reference.py - correct implementation (same function name).
3. foils.py - at least 2 functions foil_<desc>, same signature, each a PLAUSIBLE naive misreading that runs cleanly AND TERMINATES on every valid input.
4. build_vectors.py - uses random.Random(20260718) only; generates 25-40 JSON-safe [args,expected] vectors from reference (knot-edge + random); verifies and exits nonzero on failure: reference passes visible, EVERY foil passes visible, EVERY foil fails >=1 vector; writes vectors.json; prints counts.

The knot must fight an intuitive prior (the priors are what the foils encode).
FORBIDDEN domains (already in the corpus - pick something genuinely different):
{forbidden}

Pure stdlib, deterministic, no floats in outputs, all args JSON-serializable (no callables in signatures).
CRITICAL: RUN `python build_vectors.py` until exit 0, then re-verify the PERSISTED artifacts: reload vectors.json fresh from disk, confirm reference reproduces every vector via JSON round-trip, confirm every foil terminates on every persisted vector. Report only what you actually executed.
Reply with one line: <task_name>: <domain in 3-5 words>
"""

SOLVE_BRIEF = """Implement the function specified in the docstring of input.py exactly, by editing input.py in place.
- Edit ONLY input.py. Make `python input.py` print OK and exit 0 (run it to verify).
- The docstring rules are the contract: every rule is graded by hidden deterministic tests, including cases the visible checks do not exercise. Implement the rules as written even where they fight your intuition.
Reply DONE when finished.
"""


def codex(cwd, model, effort, prompt, timeout):
    command = [CLI, "exec", "--model", model, "--sandbox", "danger-full-access", "--ephemeral",
               "--json", "--output-last-message", str(cwd / "_final.txt"),
               "--config", f'model_reasoning_effort="{effort}"',
               "--config", 'web_search="disabled"', "--config", "features.multi_agent=false",
               "--config", "agents.max_depth=1", "--config", "agents.max_threads=1",
               "--config", 'history.persistence="none"', "--config", 'approval_policy="never"',
               "-C", str(cwd), "-"]
    try:
        proc = subprocess.run(command, input=prompt.encode(), capture_output=True, timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        return 124


def git_init(d):
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=f@l", "-c", "user.name=f", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(d)] + args, capture_output=True)


def timed_call(fn, args, seconds=3):
    box = {"v": "TIMEOUT"}
    def run():
        try:
            box["v"] = fn(*args)
        except Exception as exc:
            box["v"] = f"EXC:{type(exc).__name__}"
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    return box["v"]


def norm(v):
    if isinstance(v, str) and v.startswith(("EXC", "TIMEOUT")):
        return v
    try:
        return json.loads(json.dumps(v))
    except Exception:
        return f"UNSERIALIZABLE:{type(v).__name__}"


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def stub_name(input_path):
    for node in ast.parse(input_path.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.FunctionDef) and node.name != "main":
            return node.name
    raise ValueError("no stub")


def referee(task_dir, tag):
    """Hardened check: returns (valid, detail dict)."""
    detail = {}
    try:
        f = stub_name(task_dir / "input.py")
        ref = getattr(load_mod(task_dir / "reference.py", f"fr_{tag}"), f)
        fm = load_mod(task_dir / "foils.py", f"ff_{tag}")
        foils = {n: getattr(fm, n) for n in dir(fm) if n.startswith("foil_")}
        vectors = json.loads((task_dir / "vectors.json").read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return False, {"broken": f"{type(exc).__name__}: {exc}"}
    detail["vectors"] = len(vectors)
    ok = 25 <= len(vectors) <= 40 and len(foils) >= 2
    ref_miss = sum(1 for a, e in vectors if norm(timed_call(ref, a)) != e)
    detail["ref_misses"] = ref_miss
    ok = ok and ref_miss == 0

    def visible_ok(impl, key):
        try:
            m = load_mod(task_dir / "input.py", f"fi_{tag}_{key}")
            setattr(m, f, impl)
            m.main()
            return True
        except Exception:
            return False

    ok = ok and visible_ok(ref, "ref")
    detail["foils"] = {}
    for n, foil in foils.items():
        outs = [norm(timed_call(foil, a)) for a, _ in vectors]
        hangs = sum(1 for o in outs if o == "TIMEOUT")
        miss = sum(1 for o, (a, e) in zip(outs, vectors) if o != e)
        fv = visible_ok(foil, n)
        detail["foils"][n] = {"visible": fv, "misses": miss, "hangs": hangs}
        ok = ok and fv and miss > 0 and hangs == 0
    return ok, detail


def fairness(task_dir, tag):
    """Luna blind-solves a stripped packet; grade vs vectors."""
    packet = task_dir.parent / f"_fair_{task_dir.name}"
    packet.mkdir(exist_ok=True)
    (packet / "input.py").write_text((task_dir / "input.py").read_text(encoding="utf-8"), encoding="utf-8")
    git_init(packet)
    rc = codex(packet, "gpt-5.6-luna", "low", SOLVE_BRIEF, 420)
    if rc != 0:
        return "SOLVER-RC-" + str(rc), None
    try:
        f = stub_name(task_dir / "input.py")
        solved = getattr(load_mod(packet / "input.py", f"fs_{tag}"), f)
        vectors = json.loads((task_dir / "vectors.json").read_text(encoding="utf-8-sig"))
        misses = [(a, e, norm(timed_call(solved, a))) for a, e in vectors]
        misses = [(a, e, g) for a, e, g in misses if g != e]
        return ("FAIR" if not misses else "ADJUDICATE"), misses[:3]
    except Exception as exc:
        return f"GRADE-ERROR:{type(exc).__name__}", None


def used_domains():
    domains = list(SEED_FORBIDDEN)
    for shard in F.glob("ledger*.jsonl"):
        for line in shard.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                domains.append(row.get("domain") or row.get("task", ""))
            except Exception:
                pass
    return domains


def main():
    batch, count = sys.argv[1], int(sys.argv[2])
    theme = sys.argv[3] if len(sys.argv) > 3 else ""
    ledger = F / f"ledger_{batch}.jsonl"
    for i in range(count):
        work = F / batch / f"pkg_{i:02d}"
        work.mkdir(parents=True, exist_ok=True)
        git_init(work)
        forbidden = ", ".join(d for d in used_domains() if d)
        start = time.time()
        brief = AUTHOR_BRIEF.format(forbidden=forbidden)
        if theme:
            brief += "\nPreferred domain territory for this package: " + theme + "\n"
        rc = codex(work, "gpt-5.3-codex-spark", "medium", brief, 900)
        author_secs = round(time.time() - start, 1)
        task_dirs = [d for d in work.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]
        row = {"batch": batch, "pkg": i, "author_rc": rc, "author_secs": author_secs}
        if rc != 0 or not task_dirs:
            row.update({"valid": False, "reason": "author-failed-or-empty"})
        else:
            task_dir = task_dirs[0]
            final = work / "_final.txt"
            row["task"] = task_dir.name
            row["domain"] = final.read_text(encoding="utf-8", errors="replace").strip()[:80] if final.exists() else task_dir.name
            valid, detail = referee(task_dir, f"{batch}{i}")
            row["valid"] = valid
            row["referee"] = detail
            if valid:
                verdict, misses = fairness(task_dir, f"{batch}{i}")
                row["fairness"] = verdict
                if misses:
                    row["fairness_misses"] = [[a, e, g] for a, e, g in misses]
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        print(f"pkg_{i:02d}: valid={row.get('valid')} fairness={row.get('fairness', '-')} ({author_secs}s)", flush=True)
    print("FACTORY BATCH COMPLETE", flush=True)


if __name__ == "__main__":
    main()
