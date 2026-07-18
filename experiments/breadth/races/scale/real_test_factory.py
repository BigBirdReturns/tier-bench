"""Real-repo verified-test factory. Spark writes characterization tests for a
real module; referee gates: (1) test passes against REAL code, (2) test KILLS
>=1 source mutation (has teeth). Banks only tests that do real work.
Usage: factory.py <module_path> <out_tests_dir>
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLI = r"C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"
REPO = Path(r"D:/Projects/Tier-Bench/worktrees/luna-sol-anchor-replication-v2")

MUTATIONS = [
    (r"(?<![<>=!])<=", "<"), (r"(?<![<>=!])>=", ">"),
    (r"(?<![<>=!])<(?!=)", "<="), (r"(?<![<>=!])>(?!=)", ">="),
    (r"==", "!="), (r"!=", "=="),
    (r"\band\b", "or"), (r"\bor\b", "and"),
    (r"\bTrue\b", "False"), (r"\bFalse\b", "True"),
    (r"\+ 1\b", "+ 2"), (r"\* 2\b", "* 3"),
    (r"\bmax\(", "min("), (r"\bmin\(", "max("),
]


def codex(cwd, prompt, timeout=600):
    cmd = [CLI, "exec", "--model", "gpt-5.3-codex-spark", "--sandbox", "danger-full-access", "--ephemeral",
           "--json", "--output-last-message", str(cwd / "_f.txt"),
           "--config", 'model_reasoning_effort="medium"', "--config", 'web_search="disabled"',
           "--config", "features.multi_agent=false", "--config", 'history.persistence="none"',
           "--config", 'approval_policy="never"', "-C", str(cwd), "-"]
    try:
        return subprocess.run(cmd, input=prompt.encode(), capture_output=True, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 124


def run_test(workdir, test_name):
    try:
        p = subprocess.run([sys.executable, "-B", test_name], cwd=workdir, capture_output=True, text=True, timeout=90)
        return p.returncode == 0 and "OK" in p.stdout, (p.stdout + p.stderr)[-300:]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


def mutation_kills(workdir, module_name, test_name, orig_src):
    """Return (killed, total_applicable): how many single mutants the test catches."""
    modpath = workdir / module_name
    killed = total = 0
    for pat, repl in MUTATIONS:
        matches = list(re.finditer(pat, orig_src))
        if not matches:
            continue
        # mutate FIRST occurrence only (one mutant per pattern)
        m = matches[0]
        mutant = orig_src[:m.start()] + repl + orig_src[m.end():]
        try:
            compile(mutant, module_name, "exec")
        except SyntaxError:
            continue
        total += 1
        modpath.write_text(mutant, encoding="utf-8")
        ok, _ = run_test(workdir, test_name)
        if not ok:
            killed += 1  # test failed on the mutant => it caught the change
    modpath.write_text(orig_src, encoding="utf-8")  # restore
    return killed, total


def main():
    module_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]); out_dir.mkdir(parents=True, exist_ok=True)
    module_name = module_path.name
    stem = module_path.stem
    src = (REPO / module_path).read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / module_name).write_text(src, encoding="utf-8")
        # copy sibling deps the module might import (best-effort: same-dir .py files)
        for sib in (REPO / module_path).parent.glob("*.py"):
            if sib.name != module_name:
                shutil.copy(sib, work / sib.name)
        test_name = f"test_{stem}_gen.py"
        for a in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@l", "-c", "user.name=t", "commit", "-qm", "b"]):
            subprocess.run(["git", "-C", str(work)] + a, capture_output=True)
        prompt = (
            f"You are writing a CHARACTERIZATION TEST for the existing module {module_name} in this directory.\n"
            f"Read {module_name} carefully. Write a file named {test_name} that:\n"
            f"- imports the public functions from {stem} and asserts their ACTUAL current behavior on concrete inputs\n"
            f"- covers each public function, including edge cases (empty inputs, boundaries, error paths)\n"
            f"- uses plain `assert` and a `def main():` that calls every test function then prints 'OK'; ends with\n"
            f"  `if __name__ == \"__main__\": main()`  (NO pytest — must run via `python {test_name}`)\n"
            f"- must pass against the current code (characterize what IS, not what SHOULD be). RUN it and iterate\n"
            f"  until `python {test_name}` prints OK and exits 0. Make assertions SPECIFIC (exact expected values),\n"
            f"  not just 'is not None' - specific assertions catch regressions.\n"
            f"Reply DONE when {test_name} passes."
        )
        rc = codex(work, prompt)
        test_file = work / test_name
        if not test_file.exists():
            print(f"{module_name}: NO TEST FILE (rc={rc})"); return
        passes, detail = run_test(work, test_name)
        if not passes:
            print(f"{module_name}: test does NOT pass real code -> REJECT. {detail[:120]}"); return
        killed, total = mutation_kills(work, module_name, test_name, src)
        verdict = "BANKED" if killed >= 1 else "TOOTHLESS-REJECT"
        print(f"{module_name}: passes=REAL, mutation_score={killed}/{total} -> {verdict}")
        if killed >= 1:
            banked = out_dir / test_name
            banked.write_text(test_file.read_text(encoding="utf-8"), encoding="utf-8")
            (out_dir / f"{stem}_meta.txt").write_text(f"module={module_path}\nmutation_score={killed}/{total}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
