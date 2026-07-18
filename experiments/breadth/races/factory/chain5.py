"""W7 chain runner: 5 sequential codex calls; stage k+1 gets the model's own
stage-k state. Grades each stage vs the reference chain (first-divergence).
Usage: chain_runner.py <arm_name> <model> <effort>"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

W = Path(__file__).resolve().parent
A = W / "_authoring"
CLI = r"C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"


def codex(cwd, model, effort, prompt, timeout=420):
    command = [CLI, "exec", "--model", model, "--sandbox", "danger-full-access", "--ephemeral",
               "--json", "--output-last-message", str(cwd / "_final.txt"),
               "--config", f'model_reasoning_effort="{effort}"',
               "--config", 'web_search="disabled"', "--config", "features.multi_agent=false",
               "--config", "agents.max_depth=1", "--config", "agents.max_threads=1",
               "--config", 'history.persistence="none"', "--config", 'approval_policy="never"',
               "-C", str(cwd), "-"]
    try:
        return subprocess.run(command, input=prompt.encode(), capture_output=True, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 124


def git_init(d):
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=c@l", "-c", "user.name=c", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(d)] + args, capture_output=True)


def main():
    arm, model, effort = sys.argv[1], sys.argv[2], sys.argv[3]
    expected = json.loads((A / "expected.json").read_text(encoding="utf-8-sig"))
    task_template = (A / "TASK_TEMPLATE.md").read_text(encoding="utf-8")
    current = json.loads((A / "state0.json").read_text(encoding="utf-8-sig"))
    report = {"arm": arm, "model": model, "effort": effort, "stages": {}}
    first_divergence = None
    for k in range(1, 6):
        stage = W / arm / f"stage_{k}"
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "state.json").write_text(json.dumps(current, indent=1), encoding="utf-8")
        (stage / "MEMO.md").write_text((A / f"MEMO_{k}.md").read_text(encoding="utf-8"), encoding="utf-8")
        git_init(stage)
        start = time.time()
        rc = codex(stage, model, effort, task_template.format(k=k) + "\n" + (stage / "MEMO.md").read_text(encoding="utf-8-sig"))
        secs = round(time.time() - start, 1)
        try:
            produced = json.loads((stage / "state.json").read_text(encoding="utf-8-sig"))
        except Exception as exc:
            report["stages"][k] = {"rc": rc, "secs": secs, "match": False, "error": f"BAD-JSON:{type(exc).__name__}"}
            first_divergence = first_divergence or k
            print(f"{arm} stage {k}: BAD JSON rc={rc}", flush=True)
            break
        match = produced == expected[str(k)]
        report["stages"][k] = {"rc": rc, "secs": secs, "match": match}
        if not match and first_divergence is None:
            first_divergence = k
        print(f"{arm} stage {k}: match={match} rc={rc} {secs}s", flush=True)
        current = produced  # THEIR output feeds THEIR next stage
    report["first_divergence"] = first_divergence
    report["final_match"] = report["stages"].get(5, {}).get("match", False)
    (W / f"report_{arm}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"CHAIN COMPLETE {arm}: first_divergence={first_divergence} final_match={report['final_match']}", flush=True)


if __name__ == "__main__":
    main()
