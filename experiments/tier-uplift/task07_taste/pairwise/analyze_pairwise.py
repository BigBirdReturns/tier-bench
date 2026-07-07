#!/usr/bin/env python3
"""Does taste agree at the ATOMIC (pairwise) level, even though holistic ranking
diverged? Measures haiku-vs-opus agreement on 66 pairwise judgments, and whether a
Copeland ranking built from pairwise votes aligns with the frontier better than the
holistic ranking did (haiku holistic vs frontier was rho~0.13)."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
T7 = HERE.parent
KEY = {}  # pair# -> (a_id, b_id)
for line in (HERE / "pairs_key.txt").read_text().splitlines():
    n, a, b = line.split("\t"); KEY[int(n)] = (a, b)
IDS = sorted({x for ab in KEY.values() for x in ab})


def votes(fn):
    """pair# -> winning candidate id."""
    out = {}
    for line in (HERE / fn).read_text().splitlines():
        m = re.match(r"\s*(\d+)\s*[:.]?\s*([AB])", line.strip())
        if m:
            n = int(m.group(1)); a, b = KEY[n]
            out[n] = a if m.group(2).upper() == "A" else b
    return out


def copeland(v):
    """rank ids by number of pairwise wins (Copeland), best first."""
    wins = {i: 0 for i in IDS}
    for n, w in v.items():
        wins[w] += 1
    return sorted(IDS, key=lambda i: -wins[i]), wins


def rho(r1, r2):
    c = [i for i in r1 if i in r2]; n = len(c)
    p1 = {i: r1.index(i) for i in c}; p2 = {i: r2.index(i) for i in c}
    return round(1 - 6 * sum((p1[i] - p2[i]) ** 2 for i in c) / (n * (n * n - 1)), 3)


def holistic(fn):
    txt = (T7 / "judge" / fn).read_text(); m = re.search(r"RANKING:\s*(.+)", txt)
    ids = re.findall(r"C\d{2}", m.group(1)); seen = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def main():
    hv, ov = votes("haiku_votes.txt"), votes("opus_votes.txt")
    common = [n for n in KEY if n in hv and n in ov]
    agree = sum(1 for n in common if hv[n] == ov[n])
    print(f"=== ATOMIC AGREEMENT (haiku vs opus, per pairwise taste call) ===")
    print(f"  {agree}/{len(common)} = {100*agree/len(common):.0f}%   (chance = 50%)")

    hr, hw = copeland(hv); orank, ow = copeland(ov)
    print(f"\n=== Copeland rankings from pairwise votes ===")
    print(f"  haiku-pairwise: {','.join(hr)}")
    print(f"  opus-pairwise : {','.join(orank)}")
    print(f"  haiku-pairwise vs opus-pairwise rho = {rho(hr, orank)}")

    # compare to holistic (frontier = opus+sonnet holistic consensus earlier)
    o_hol, s_hol = holistic("opus.txt"), holistic("sonnet.txt")
    h_hol = holistic("haiku.txt")
    def front(r): return round((rho(r, o_hol) + rho(r, s_hol)) / 2, 3)
    print(f"\n=== does pairwise beat holistic at frontier-alignment? ===")
    print(f"  haiku HOLISTIC   vs frontier: {front(h_hol)}")
    print(f"  haiku PAIRWISE   vs frontier: {front(hr)}")
    print(f"  opus  PAIRWISE   vs opus holistic: {rho(orank, o_hol)}  (sanity: is opus self-consistent?)")

    print(f"\n  frontier's #1 line C09 — haiku holistic #{h_hol.index('C09')+1}, "
          f"haiku pairwise #{hr.index('C09')+1}")

    (HERE / "pairwise_result.json").write_text(json.dumps({
        "atomic_agreement": round(agree / len(common), 3), "n_pairs": len(common),
        "haiku_pairwise_vs_opus_pairwise_rho": rho(hr, orank),
        "haiku_holistic_vs_frontier": front(h_hol),
        "haiku_pairwise_vs_frontier": front(hr),
        "interpretation_hint": "high atomic agreement + low holistic = the gap was aggregation, not taste",
    }, indent=1))
    print("\nwrote pairwise_result.json")


if __name__ == "__main__":
    main()
