"""make packet -> Spark solves -> grade per-rule recall. Usage: scale_run.py <N> <model> <effort>"""
import subprocess
import sys
import time
from pathlib import Path

F = Path(__file__).resolve().parent
CLI = r"C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"
PROMPT = """Implement the function specified in the docstring of input.py exactly, editing input.py in place.
- Edit ONLY input.py. Make `python input.py` print OK and exit 0 (run it).
- EVERY numbered rule in the docstring is graded by hidden tests. Implement ALL of them, precisely.
Reply DONE."""


def main():
    n, model, effort = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    d = F / f"run_{model.split('-')[-1]}_{n}"
    subprocess.run([sys.executable, "-B", str(F / "build_scale.py"), "make", str(d), str(n)], capture_output=True)
    for a in (["init", "-q"], ["add", "-A"], ["-c", "user.email=s@l", "-c", "user.name=s", "commit", "-qm", "b"]):
        subprocess.run(["git", "-C", str(d)] + a, capture_output=True)
    cmd = [CLI, "exec", "--model", model, "--sandbox", "danger-full-access", "--ephemeral", "--json",
           "--output-last-message", str(d / "_final.txt"),
           "--config", f'model_reasoning_effort="{effort}"', "--config", 'web_search="disabled"',
           "--config", "features.multi_agent=false", "--config", 'history.persistence="none"',
           "--config", 'approval_policy="never"', "-C", str(d), "-"]
    start = time.time()
    try:
        rc = subprocess.run(cmd, input=PROMPT.encode(), capture_output=True, timeout=900).returncode
    except subprocess.TimeoutExpired:
        rc = 124
    secs = round(time.time() - start, 1)
    print(f"N={n} solved rc={rc} {secs}s", flush=True)
    subprocess.run([sys.executable, "-B", str(F / "build_scale.py"), "grade", str(d), str(n)])


if __name__ == "__main__":
    main()
