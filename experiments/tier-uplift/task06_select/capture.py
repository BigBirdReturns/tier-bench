#!/usr/bin/env python3
"""Use all the buffalo: turn every run file into a retained, structured record.

Scans runs/*.md, extracts each run's claimed `COUNTEREXAMPLE: items=...; k=...`
line, verifies it against the brute-force reference, and appends ONE record per
run to results.jsonl — capturing valid AND invalid counterexamples (an invalid
one is evidence of the reasoning wall, not garbage), plus the raw file path so the
full text is always recoverable. Idempotent: rewrites results.jsonl from scratch.

    python capture.py
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from grader import check  # subject-vs-reference counterexample check

CE = re.compile(r"COUNTEREXAMPLE:\s*items\s*=\s*(\[.*?\])\s*;\s*k\s*=\s*(\d+)", re.IGNORECASE | re.DOTALL)

# Per-1M OUTPUT-token price (USD). We price at the output rate as a labeled UPPER
# BOUND, since the harness reports a single `subagent_tokens` count with no
# input/output split. Token counts themselves are hard data; the dollar figure is
# an explicit over-estimate for apples-to-apples comparison across tiers.
PRICE_PER_1M = {"haiku": 5.0, "sonnet": 15.0, "opus": 25.0}


def _load_usage():
    p = HERE / "usage.jsonl"
    if not p.exists():
        return {}
    return {json.loads(l)["run"]: json.loads(l)
            for l in p.read_text().splitlines() if l.strip()}


def parse_run(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    name = path.stem  # e.g. baseline_haiku  or  sweep_haiku_5adversarial
    parts = name.split("_")
    mode = parts[0]                       # baseline | sweep
    model = parts[1] if len(parts) > 1 else "?"
    lens = "_".join(parts[2:]) if len(parts) > 2 else ""
    rec = {"run": name, "mode": mode, "model": model, "lens": lens,
           "raw_file": str(path.relative_to(HERE.parent)), "chars": len(text)}
    m = CE.search(text)
    if not m:
        rec.update(found=False, counterexample=None, note="no parseable COUNTEREXAMPLE line")
        return rec
    try:
        items = eval(m.group(1), {"__builtins__": {}})   # our own extracted literal
        k = int(m.group(2))
        is_ce, s, r = check(items, k)
        rec.update(found=bool(is_ce), counterexample={"items": items, "k": k},
                   subject_out=s, reference_out=r,
                   note="valid counterexample" if is_ce else "claimed but NOT a counterexample")
    except Exception as e:
        rec.update(found=False, counterexample=m.group(0), note=f"unparseable/invalid: {e}")
    return rec


def _cost(model, tokens):
    return round((tokens / 1_000_000) * PRICE_PER_1M.get(model, 0.0), 5)


def main():
    runs = sorted((HERE / "runs").glob("*.md"))
    usage = _load_usage()
    records = []
    for p in runs:
        rec = parse_run(p)
        u = usage.get(rec["run"], {})
        rec["tokens"] = u.get("tokens")
        rec["tool_uses"] = u.get("tool_uses")
        rec["duration_ms"] = u.get("duration_ms")
        rec["cost_usd_upperbound"] = _cost(rec["model"], u["tokens"]) if u.get("tokens") else None
        records.append(rec)
    out = HERE / "results.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{len(records)} runs captured -> {out.name}\n")
    print(f"{'run':32}{'found':6}{'tokens':>8}{'tools':>6}{'$ (ub)':>9}")
    print("-" * 63)
    tot_tok = 0
    for r in records:
        f_ = "YES" if r.get("found") else "no"
        tk = r.get("tokens") or 0
        tot_tok += tk
        c = r.get("cost_usd_upperbound")
        print(f"{r['run']:32}{f_:6}{tk:>8}{r.get('tool_uses') or 0:>6}{('$'+format(c,'.4f')) if c is not None else '—':>9}")
    print("-" * 63)
    print(f"{'TOTAL tokens':32}{'':6}{tot_tok:>8}")

    # economy: cheapest FOUND vs the frontier baseline that also found it
    found = [r for r in records if r.get("found") and r.get("cost_usd_upperbound") is not None]
    opus_base = next((r for r in records if r["run"] == "baseline_opus"), None)
    if found and opus_base and opus_base.get("cost_usd_upperbound"):
        cheapest = min(found, key=lambda r: r["cost_usd_upperbound"])
        print(f"\nECONOMY (cost per verified counterexample, $ upper-bound):")
        print(f"  opus solo (frontier):        ${opus_base['cost_usd_upperbound']:.4f}  ({opus_base['tokens']} tok)")
        print(f"  cheapest that FOUND it:      ${cheapest['cost_usd_upperbound']:.4f}  ({cheapest['run']}, {cheapest['tokens']} tok)")
        ratio = cheapest["cost_usd_upperbound"] / opus_base["cost_usd_upperbound"]
        verdict = f"{ratio:.2f}x the cost of opus" if ratio >= 1 else f"{1/ratio:.2f}x CHEAPER than opus"
        print(f"  -> the harness path is {verdict} for the same verified result")


if __name__ == "__main__":
    main()
