"""
Aggregate control-set disposition runs (data/control-results/*.jsonl) into a
per (model, effort, probe) view with evidence labels.

Mirrors the honesty doctrine of scripts/aggregate.py: every run is self-reported.
A (model, effort, probe) cell scored by only one contributor is 'single-source';
>=2 DISTINCT contributors (and never the subject grading itself) make it
'corroborated'. The label always rides with the number. Scores are human-entered
(2/1/0); this script never invents a grade — null stays null and is reported as
UNGRADED so an ungraded run can never masquerade as a passing one.

Two independence axes, never conflated:
  - contributor != subject     : who administered the probe (corroboration axis)
  - grader lineage != subject  : who scored it. Disposition is a lineage-level
    property, so a grader that SHARES the subject's lineage (e.g. one Claude
    grading another) is a conflict of interest. Such cells are graded but carry
    a 'grader shares subject lineage' flag until an independent grader clears it.

Usage:
    python scripts/aggregate_control.py
    python scripts/aggregate_control.py --data data/control-results --json
"""
from __future__ import annotations
import argparse, json, glob
from collections import defaultdict
from pathlib import Path

# Lineage tokens — used only to decide whether a grader is independent of the
# subject. Extend as new model families show up; unknown => "other".
LINEAGE = {
    "anthropic": ("claude", "opus", "sonnet", "haiku", "fable"),
    "openai": ("gpt", "o1", "o3", "o4", "chatgpt"),
    "google": ("gemini", "gemma", "palm"),
    "meta": ("llama",),
    "mistral": ("mistral", "mixtral"),
    "deepseek": ("deepseek",),
    "qwen": ("qwen",),
}


def _lineage(name: str) -> str:
    n = (name or "").lower()
    for vendor, toks in LINEAGE.items():
        if any(t in n for t in toks):
            return vendor
    return "other"


def load(data_dir: str):
    runs = []
    for f in sorted(glob.glob(str(Path(data_dir) / "*.jsonl"))):
        rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        meta = rows[0]
        assert meta.get("_meta"), f"{f}: missing _meta row"
        meta = dict(meta)
        meta.setdefault("administration_id", Path(f).stem)
        runs.append((meta, rows[1:]))
    return runs


def aggregate(data_dir: str) -> dict:
    """Pool control-results into per (model, effort, probe) cells with evidence
    labels. The single source of truth for the disposition numbers — the CLI
    below and scripts/build_tally.py both read from here, so the ruler can never
    drift between the table and the tally."""
    runs = load(data_dir)

    # cell key: (model, effort, probe_id) -> list of judgment dicts.
    # Preserve repeated administrations by carrying an administration_id. Legacy
    # records derive this stable ID from the filename stem when absent.
    cells = defaultdict(list)
    for meta, probes in runs:
        subj = meta["model"]
        admin_id = meta["administration_id"]
        for p in probes:
            base = {
                "score": p["score"],
                "contributor": meta["contributor"],
                "grader": p["grader"],
                "contaminated": p.get("contaminated", False),
                "grader_independent": _lineage(p["grader"]) != _lineage(subj),
                "administration_id": admin_id,
                "judgment_layer": "original",
            }
            cells[(subj, meta["effort"], p["probe_id"])].append(base)
            for ext in p.get("external_grades", []):
                cells[(subj, meta["effort"], p["probe_id"])].append({
                    "score": ext.get("score"),
                    "contributor": meta["contributor"],
                    "grader": ext.get("grader", "UNGRADED"),
                    "contaminated": p.get("contaminated", False),
                    "grader_independent": _lineage(ext.get("grader", "")) != _lineage(subj),
                    "administration_id": admin_id,
                    "judgment_layer": "external",
                })

    out = {}
    for (model, effort, pid), obs in sorted(cells.items()):
        valid = [o for o in obs if not o["contaminated"]]        # drop contaminated
        graded = [o for o in valid if o["score"] is not None
                  and o["grader"] not in ("UNGRADED", o["contributor"])]  # grader != subject-as-human, score present
        contributors = {o["contributor"] for o in graded}
        independent = [o for o in graded if o["grader_independent"]]
        scores = [o["score"] for o in graded]

        if not graded:
            evidence = "UNGRADED"
        else:
            evidence = "corroborated" if len(contributors) >= 2 else "single-source"
            if not independent:
                # every grade came from a grader sharing the subject's lineage
                evidence += " · grader shares subject lineage"

        out[f"{model}|{effort}|{pid}"] = {
            "model": model, "effort": effort, "probe": pid,
            "n_runs": len({o["administration_id"] for o in valid}), "n_judgments": len(valid), "n_graded": len(graded),
            "n_independent_graded": len(independent),
            "administration_ids": sorted({o["administration_id"] for o in valid}),
            "scores": scores,
            "mean": round(sum(scores) / len(scores), 2) if scores else None,
            "evidence_class": evidence,
            "grader_lineage_flag": bool(graded) and not independent,
            "note": "all self-reported; corroborated=>=2 distinct non-subject contributors; "
                    "lineage flag set when no grader is independent of the subject's lineage",
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/control-results")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = aggregate(a.data)

    if a.json:
        print(json.dumps(out, indent=2))
    else:
        for k, c in out.items():
            m = c["mean"] if c["mean"] is not None else "--"
            print(f"{k:28s}  n={c['n_runs']} graded={c['n_graded']:>2}  "
                  f"mean={m!s:>4}  [{c['evidence_class']}]")


if __name__ == "__main__":
    main()
