"""W8: 20-stage compounding chain, deterministic memos, each stage feeds forward.
Reference computed in-process; model runs sequentially; first-divergence reported.
Usage: build_and_run.py <arm> <model> <effort>"""
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

W = Path(__file__).resolve().parent
CLI = r"C:/Users/BAM-Desktop/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"

STATE0 = {
    "cells": [{"id": i, "v": (i * 7 + 3) % 20, "tag": "n"} for i in range(12)],
    "acc": 0,
    "log": [],
}

# 20 deterministic memos, each a small rule that depends on prior state.
MEMOS = [
    ("rotate_values", "Rotate the v field of every cell one position toward higher id (cell i takes cell i-1's OLD v; cell 0 takes the last cell's OLD v). Append to log the string 'rot'."),
    ("tag_even", "Set tag='e' for every cell whose v is even, tag='o' otherwise. Do not change v. Append 'tag' to log."),
    ("acc_evens", "Add to acc the sum of v over all cells tagged 'e'. Append 'acc:'+str(the amount added) to log."),
    ("drop_high", "Remove every cell with v >= 18 from cells (renumber nothing; keep ids). Append 'drop:'+str(count removed) to log."),
    ("double_odd_tag", "For every cell tagged 'o', set v = (v*2) % 23. Append 'dbl' to log."),
    ("retag_even", "Recompute tag: 'e' if v even else 'o'. Append 'tag' to log."),
    ("prefix_max", "Replace each cell's v with the running maximum of v in current cell order (cell k gets max of v over cells 0..k). Append 'pmax' to log."),
    ("acc_first_last", "Add to acc the value (first cell's v minus last cell's v). Append 'acc:'+str(amount) to log."),
    ("mod_acc", "Set acc = acc % 100. Append 'mod' to log."),
    ("insert_pivot", "Append a new cell {id: 100, v: acc % 20, tag: 'p'} to the end of cells. Append 'ins' to log."),
    ("reverse_cells", "Reverse the order of the cells list. Append 'rev' to log."),
    ("gc_pivot_tag", "For any cell tagged 'p', set v = (v + 5) % 20 and tag='n'. Append 'gc' to log."),
    ("sum_ids_even_v", "Add to acc the sum of id over cells whose v is even. Append 'acc:'+str(amount) to log."),
    ("clamp_v", "For every cell, set v = min(v, 15). Append 'clamp' to log."),
    ("tag_by_id_parity", "Set tag='e' if id is even else 'o' (overwrite prior tags). Append 'tag' to log."),
    ("delta_encode", "Replace cells' v in current order with delta encoding: first cell keeps its v; each later cell gets (its v - previous ORIGINAL v). Append 'delta' to log."),
    ("acc_negatives", "Add to acc the count of cells with v < 0. Append 'acc:'+str(amount) to log."),
    ("restore_cumsum", "Replace v with the cumulative sum of the current v list (inverse-ish of delta): cell k gets sum of v over 0..k. Append 'cumsum' to log."),
    ("keep_top3_by_v", "Keep only the 3 cells with the largest v (ties broken by smaller id); preserve their current relative order. Append 'top3' to log."),
    ("finalize", "Add key 'final' = {'acc': acc, 'ids': sorted(cell ids), 'vsum': sum of v, 'events': len(log)}. Append 'fin' to log."),
]


def apply(state, idx):
    s = copy.deepcopy(state)
    cells, log = s["cells"], s["log"]
    name = MEMOS[idx][0]
    if name == "rotate_values":
        old = [c["v"] for c in cells]
        for i, c in enumerate(cells):
            c["v"] = old[i - 1]
        log.append("rot")
    elif name == "tag_even":
        for c in cells:
            c["tag"] = "e" if c["v"] % 2 == 0 else "o"
        log.append("tag")
    elif name == "acc_evens":
        amt = sum(c["v"] for c in cells if c["tag"] == "e")
        s["acc"] += amt
        log.append("acc:" + str(amt))
    elif name == "drop_high":
        before = len(cells)
        s["cells"] = [c for c in cells if c["v"] < 18]
        log.append("drop:" + str(before - len(s["cells"])))
    elif name == "double_odd_tag":
        for c in s["cells"]:
            if c["tag"] == "o":
                c["v"] = (c["v"] * 2) % 23
        log.append("dbl")
    elif name == "retag_even":
        for c in s["cells"]:
            c["tag"] = "e" if c["v"] % 2 == 0 else "o"
        log.append("tag")
    elif name == "prefix_max":
        m = None
        for c in s["cells"]:
            m = c["v"] if m is None else max(m, c["v"])
            c["v"] = m
        log.append("pmax")
    elif name == "acc_first_last":
        amt = (s["cells"][0]["v"] - s["cells"][-1]["v"]) if s["cells"] else 0
        s["acc"] += amt
        log.append("acc:" + str(amt))
    elif name == "mod_acc":
        s["acc"] %= 100
        log.append("mod")
    elif name == "insert_pivot":
        s["cells"].append({"id": 100, "v": s["acc"] % 20, "tag": "p"})
        log.append("ins")
    elif name == "reverse_cells":
        s["cells"].reverse()
        log.append("rev")
    elif name == "gc_pivot_tag":
        for c in s["cells"]:
            if c["tag"] == "p":
                c["v"] = (c["v"] + 5) % 20
                c["tag"] = "n"
        log.append("gc")
    elif name == "sum_ids_even_v":
        amt = sum(c["id"] for c in s["cells"] if c["v"] % 2 == 0)
        s["acc"] += amt
        log.append("acc:" + str(amt))
    elif name == "clamp_v":
        for c in s["cells"]:
            c["v"] = min(c["v"], 15)
        log.append("clamp")
    elif name == "tag_by_id_parity":
        for c in s["cells"]:
            c["tag"] = "e" if c["id"] % 2 == 0 else "o"
        log.append("tag")
    elif name == "delta_encode":
        orig = [c["v"] for c in s["cells"]]
        for i, c in enumerate(s["cells"]):
            if i:
                c["v"] = orig[i] - orig[i - 1]
        log.append("delta")
    elif name == "acc_negatives":
        amt = sum(1 for c in s["cells"] if c["v"] < 0)
        s["acc"] += amt
        log.append("acc:" + str(amt))
    elif name == "restore_cumsum":
        run = 0
        for c in s["cells"]:
            run += c["v"]
            c["v"] = run
        log.append("cumsum")
    elif name == "keep_top3_by_v":
        ranked = sorted(range(len(s["cells"])), key=lambda i: (-s["cells"][i]["v"], s["cells"][i]["id"]))
        keep = set(ranked[:3])
        s["cells"] = [c for i, c in enumerate(s["cells"]) if i in keep]
        log.append("top3")
    elif name == "finalize":
        s["final"] = {"acc": s["acc"], "ids": sorted(c["id"] for c in s["cells"]),
                      "vsum": sum(c["v"] for c in s["cells"]), "events": len(log)}
        log.append("fin")
    return s


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
    for a in (["init", "-q"], ["add", "-A"], ["-c", "user.email=c@l", "-c", "user.name=c", "commit", "-qm", "b"]):
        subprocess.run(["git", "-C", str(d)] + a, capture_output=True)


TASK = """Edit state.json IN PLACE so it reflects the rule in MEMO.md applied to the current state exactly.
The memo is the complete contract; apply it literally even where it fights intuition. Keep state.json valid JSON. Preserve fields the memo doesn't mention. Reply DONE."""


def main():
    arm, model, effort = sys.argv[1], sys.argv[2], sys.argv[3]
    expected = []
    s = copy.deepcopy(STATE0)
    for k in range(len(MEMOS)):
        s = apply(s, k)
        expected.append(copy.deepcopy(s))
    current = copy.deepcopy(STATE0)
    report = {"arm": arm, "stages": {}, "first_divergence": None}
    for k in range(len(MEMOS)):
        d = W / arm / f"s{k:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(current, indent=1), encoding="utf-8")
        (d / "MEMO.md").write_text(f"MEMO stage {k+1}/20 - {MEMOS[k][0]}\n\n{MEMOS[k][1]}\n", encoding="utf-8")
        git_init(d)
        start = time.time()
        rc = codex(d, model, effort, TASK + "\n\n" + (d / "MEMO.md").read_text(encoding="utf-8"))
        secs = round(time.time() - start, 1)
        try:
            produced = json.loads((d / "state.json").read_text(encoding="utf-8"))
        except Exception as exc:
            report["stages"][k] = {"rc": rc, "secs": secs, "match": False, "err": str(type(exc).__name__)}
            report["first_divergence"] = k
            print(f"{arm} s{k:02d} BAD-JSON", flush=True)
            break
        match = produced == expected[k]
        report["stages"][k] = {"rc": rc, "secs": secs, "match": match}
        if not match and report["first_divergence"] is None:
            report["first_divergence"] = k
        print(f"{arm} s{k:02d} ({MEMOS[k][0]}): match={match} {secs}s", flush=True)
        current = produced
    report["final_match"] = report["stages"].get(len(MEMOS) - 1, {}).get("match", False)
    (W / f"report_{arm}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"W8 COMPLETE {arm}: first_divergence={report['first_divergence']} final_match={report['final_match']}", flush=True)


if __name__ == "__main__":
    main()
