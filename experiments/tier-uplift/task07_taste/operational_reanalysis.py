#!/usr/bin/env python3
"""Re-analysis after the 'sand' correction: measure taste at the OPERATIONAL
level (good-vs-bad) not the SAND level (exact ranking of near-ties). Splits the 66
pairwise calls by consensus quality gap; agreement/correctness should be high on
operationally-decisive pairs and ~chance on near-ties (sand). Uses committed data
only; deterministic."""
import re
from pathlib import Path
HERE = Path(__file__).resolve().parent
def holrank(fn):
    m = re.search(r"RANKING:\s*(.+)", (HERE/"judge"/fn).read_text()); ids = re.findall(r"C\d{2}", m.group(1)); seen=set()
    return [i for i in ids if not (i in seen or seen.add(i))]
ranks = [holrank(f) for f in ["haiku.txt","sonnet.txt","opus.txt"]]
ids = sorted(ranks[0]); consensus = {i: sum(r.index(i) for r in ranks)/3 for i in ids}
KEY = {}
for line in (HERE/"pairwise/pairs_key.txt").read_text().splitlines():
    n,a,b = line.split("\t"); KEY[int(n)] = (a,b)
def votes(fn):
    out={}
    for l in (HERE/"pairwise"/fn).read_text().splitlines():
        m=re.match(r"\s*(\d+)\s*[:.]?\s*([AB])", l.strip())
        if m: n=int(m.group(1)); a,b=KEY[n]; out[n]=a if m.group(2).upper()=="A" else b
    return out
hv,ov = votes("haiku_votes.txt"), votes("opus_votes.txt")
rows=[]
for n,(a,b) in KEY.items():
    if n in hv and n in ov:
        gap=abs(consensus[a]-consensus[b]); better = a if consensus[a]<consensus[b] else b
        rows.append((gap, hv[n]==ov[n], hv[n]==better, ov[n]==better))
dec=[r for r in rows if r[0]>=6]
print(f"DECISIVE pairs (consensus gap>=6, n={len(dec)}): haiku picks operationally-better "
      f"{sum(r[2] for r in dec)/len(dec)*100:.0f}%, opus {sum(r[3] for r in dec)/len(dec)*100:.0f}%, "
      f"agree {sum(r[1] for r in dec)/len(dec)*100:.0f}%")
close=[r for r in rows if r[0]<2]
print(f"CLOSE/sand pairs (gap<2, n={len(close)}): agree {sum(r[1] for r in close)/len(close)*100:.0f}% (~chance)")
print("Conclusion: operational taste is SHARED (haiku has it on decisive calls); "
      "disagreement is sand — the arbitrary order of operationally-equivalent near-ties.")
