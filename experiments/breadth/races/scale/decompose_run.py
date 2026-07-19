"""Crate-rescue test: same N-rule spec, solved in C sequential passes of N/C rules
each, model editing the same input.py with its own prior work visible. Measures
whether scoping context to a subset per pass rescues dropped rules.
Usage: decompose_run.py <N> <chunks> <model> <effort>"""
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

F = Path(__file__).resolve().parent
CLI = r"C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"


def codex(cwd, model, effort, prompt, timeout=600):
    cmd = [CLI, "exec", "--model", model, "--sandbox", "danger-full-access", "--ephemeral", "--json",
           "--output-last-message", str(cwd / "_final.txt"),
           "--config", f'model_reasoning_effort="{effort}"', "--config", 'web_search="disabled"',
           "--config", "features.multi_agent=false", "--config", 'history.persistence="none"',
           "--config", 'approval_policy="never"', "-C", str(cwd), "-"]
    try:
        return subprocess.run(cmd, input=prompt.encode(), capture_output=True, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 124


def main():
    n, chunks, model, effort = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    d = F / f"decomp_{model.split('-')[-1]}_{n}x{chunks}"
    subprocess.run([sys.executable, "-B", str(F / "build_scale.py"), "make", str(d), str(n)], capture_output=True)
    for a in (["init", "-q"], ["add", "-A"], ["-c", "user.email=s@l", "-c", "user.name=s", "commit", "-qm", "b"]):
        subprocess.run(["git", "-C", str(d)] + a, capture_output=True)
    per = n // chunks
    start = time.time()
    for c in range(chunks):
        lo, hi = c * per + 1, (c + 1) * per if c < chunks - 1 else n
        prompt = (
            f"input.py has a docstring specifying {n} numbered normalization rules for normalize(record).\n"
            f"THIS PASS: implement rules {lo} through {hi} ONLY. If normalize already implements earlier\n"
            f"rules, PRESERVE them exactly and ADD the rules {lo}-{hi}. Do not remove or alter code for\n"
            f"other rules. Edit input.py in place. `python input.py` must still print OK. Reply DONE."
        )
        rc = codex(d, model, effort, prompt)
        print(f"  pass {c+1}/{chunks} (rules {lo}-{hi}) rc={rc}", flush=True)
    secs = round(time.time() - start, 1)
    print(f"decomp N={n} chunks={chunks} total {secs}s", flush=True)
    subprocess.run([sys.executable, "-B", str(F / "build_scale.py"), "grade", str(d), str(n)])


if __name__ == "__main__":
    main()
