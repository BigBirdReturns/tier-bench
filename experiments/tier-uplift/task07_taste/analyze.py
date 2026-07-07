#!/usr/bin/env python3
"""Analyze the taste probe: is judgment flat across tiers, and is there a
generation gap? No oracle exists — so the signals are (1) inter-judge rank
agreement and (2) consensus rank of each tier's (anonymized) candidates.
"""
import json
import re
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY = json.loads((HERE / "pool_key.json").read_text())      # id -> author tier
IDS = list(KEY.keys())
JUDGES = ["haiku", "sonnet", "opus"]


def read_ranking(tier):
    txt = (HERE / "judge" / f"{tier}.txt").read_text(encoding="utf-8")
    m = re.search(r"RANKING:\s*(.+)", txt)
    ids = re.findall(r"C\d{2}", m.group(1)) if m else []
    # keep first occurrence, order preserved
    seen, order = set(), []
    for i in ids:
        if i in KEY and i not in seen:
            seen.add(i); order.append(i)
    top = re.search(r"TOP:\s*(C\d{2})", txt)
    return order, (top.group(1) if top else (order[0] if order else None))


def spearman(r1, r2):
    """Spearman rho between two full rankings (lists of ids, best-first)."""
    common = [i for i in r1 if i in r2]
    n = len(common)
    if n < 2:
        return None
    p1 = {i: r1.index(i) for i in common}
    p2 = {i: r2.index(i) for i in common}
    d2 = sum((p1[i] - p2[i]) ** 2 for i in common)
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def main():
    rankings, tops = {}, {}
    for t in JUDGES:
        rankings[t], tops[t] = read_ranking(t)

    print("=== each judge's blind ranking (best -> worst) ===")
    for t in JUDGES:
        print(f"  {t:7}: {','.join(rankings[t])}   TOP={tops[t]} (author={KEY.get(tops[t],'?')})")

    print("\n=== (1) IS TASTE FLAT? inter-judge Spearman rho ===")
    rhos = []
    for a, b in combinations(JUDGES, 2):
        rho = spearman(rankings[a], rankings[b])
        rhos.append(rho)
        print(f"  {a:7} vs {b:7}: rho = {rho}")
    valid = [r for r in rhos if r is not None]
    mean_rho = round(sum(valid) / len(valid), 3) if valid else None
    print(f"  mean pairwise rho = {mean_rho}   "
          f"({'HIGH — taste largely shared' if mean_rho and mean_rho >= 0.6 else 'LOW/MIXED — taste diverges by tier'})")

    # top-pick overlap
    tp = [tops[t] for t in JUDGES]
    print(f"  top picks: {dict(zip(JUDGES, tp))}  -> "
          f"{'UNANIMOUS' if len(set(tp))==1 else str(len(set(tp)))+' distinct'}")

    print("\n=== (2) GENERATION GAP: consensus rank by AUTHOR tier (lower = better) ===")
    # Borda: position in each judge's ranking (0=best). Average across judges, per candidate.
    pos = {i: [] for i in IDS}
    for t in JUDGES:
        for rank, i in enumerate(rankings[t]):
            pos[i].append(rank)
    cand_mean = {i: sum(v) / len(v) for i, v in pos.items() if v}
    by_tier = {"haiku": [], "sonnet": [], "opus": []}
    for i, m in cand_mean.items():
        by_tier[KEY[i]].append(m)
    for tier in ["haiku", "sonnet", "opus"]:
        vals = by_tier[tier]
        avg = round(sum(vals) / len(vals), 2) if vals else None
        print(f"  {tier:7}: mean consensus position {avg}   (its 4 lines: "
              f"{[round(x,1) for x in sorted(vals)]})")
    # overall winner line
    best_id = min(cand_mean, key=cand_mean.get)
    print(f"  overall best line: {best_id} (author={KEY[best_id]}, mean pos {cand_mean[best_id]:.2f})")

    # self-preference: does each judge rank its OWN lines higher than the others do?
    print("\n=== self-preference check (does a judge over-rank its own anonymized lines?) ===")
    for t in JUDGES:
        own = [i for i in IDS if KEY[i] == t]
        my_pos = sum(rankings[t].index(i) for i in own) / len(own)
        others = [j for j in JUDGES if j != t]
        oth_pos = sum(rankings[j].index(i) for j in others for i in own) / (len(own) * len(others))
        tag = "ranks own HIGHER" if my_pos < oth_pos - 0.5 else ("ranks own LOWER" if my_pos > oth_pos + 0.5 else "no bias")
        print(f"  {t:7}: own lines avg pos {my_pos:.2f} (self) vs {oth_pos:.2f} (others) -> {tag}")

    (HERE / "analysis.json").write_text(json.dumps({
        "rankings": rankings, "tops": tops, "mean_rho": mean_rho,
        "pairwise_rho": dict(zip([f"{a}-{b}" for a, b in combinations(JUDGES, 2)], rhos)),
        "consensus_pos_by_tier": {t: (round(sum(by_tier[t]) / len(by_tier[t]), 3) if by_tier[t] else None) for t in by_tier},
        "best_line": {"id": best_id, "author": KEY[best_id]},
    }, indent=1))
    print("\nwrote analysis.json")


if __name__ == "__main__":
    main()
