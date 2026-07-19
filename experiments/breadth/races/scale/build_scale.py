"""Breadth-scaling test: one spec with N independent field-normalization rules.
Per-rule recall measured with isolating probes -> exactly which rules drop.
Willing to fail: scale N until recall degrades, or prove it doesn't.
Usage (build+grade a solved arm): build_scale.py grade <arm_dir> <N>
       (author a packet):         build_scale.py make <out_dir> <N>
"""
import json
import random
import sys
from pathlib import Path

# 12 primitive field ops. Each: (spec_text_fn, apply_fn, probe_value_fn).
# Deterministic given a seed + field index.


def make_rules(n, seed):
    rng = random.Random(seed)
    ops = []
    for i in range(n):
        f = f"f{i:02d}"
        kind = rng.choice([
            "strip", "lower", "upper", "clamp", "default", "round_to",
            "map", "prefix", "suffix_trim", "abs_cap", "mod", "bool_flip",
        ])
        rule = {"field": f, "kind": kind}
        if kind == "clamp":
            rule["lo"], rule["hi"] = rng.randrange(0, 5), rng.randrange(10, 20)
        elif kind == "default":
            rule["val"] = rng.randrange(1, 9)
        elif kind == "round_to":
            rule["mult"] = rng.choice([5, 10, 25])
        elif kind == "map":
            keys = rng.sample(["a", "b", "c", "d", "e"], 3)
            rule["table"] = {k: rng.randrange(1, 9) for k in keys}
        elif kind == "prefix":
            rule["p"] = rng.choice(["x_", "id_", "n_"])
        elif kind == "suffix_trim":
            rule["s"] = rng.choice(["_tmp", "_old", "_v2"])
        elif kind == "abs_cap":
            rule["cap"] = rng.randrange(50, 100)
        elif kind == "mod":
            rule["m"] = rng.choice([7, 12, 100])
        ops.append(rule)
    return ops


def spec_text(rules):
    lines = ["normalize(record) -> dict",
             "record is a dict. Return a NEW dict with EVERY listed field transformed",
             "exactly as specified. Fields not listed are copied unchanged. A listed",
             "field absent from the input is created only where a rule says so (default);",
             "otherwise an absent listed field stays absent. Rules:"]
    for i, r in enumerate(rules, 1):
        f, k = r["field"], r["kind"]
        if k == "strip":
            t = f"strip leading/trailing whitespace from {f} (a string)"
        elif k == "lower":
            t = f"lowercase {f} (a string)"
        elif k == "upper":
            t = f"uppercase {f} (a string)"
        elif k == "clamp":
            t = f"clamp integer {f} to the range [{r['lo']}, {r['hi']}]"
        elif k == "default":
            t = f"if {f} is absent, set it to {r['val']}; if present, leave it"
        elif k == "round_to":
            t = f"round integer {f} DOWN to the nearest multiple of {r['mult']}"
        elif k == "map":
            t = f"replace {f} using this table {json.dumps(r['table'])}; if the value is not a key, set {f} to 0"
        elif k == "prefix":
            t = f"prepend the literal {r['p']!r} to string {f}"
        elif k == "suffix_trim":
            t = f"if string {f} ends with {r['s']!r}, remove that suffix; else leave it"
        elif k == "abs_cap":
            t = f"set {f} to min(abs(int {f}), {r['cap']})"
        elif k == "mod":
            t = f"replace integer {f} with {f} % {r['m']}"
        elif k == "bool_flip":
            t = f"replace boolean {f} with its logical NOT"
        lines.append(f"{i}. {t}")
    return "\n".join(lines)


def apply_rules(record, rules):
    out = dict(record)
    for r in rules:
        f, k = r["field"], r["kind"]
        if k == "default":
            if f not in out:
                out[f] = r["val"]
            continue
        if f not in out:
            continue
        v = out[f]
        if k == "strip":
            out[f] = v.strip()
        elif k == "lower":
            out[f] = v.lower()
        elif k == "upper":
            out[f] = v.upper()
        elif k == "clamp":
            out[f] = max(r["lo"], min(r["hi"], v))
        elif k == "round_to":
            out[f] = (v // r["mult"]) * r["mult"]
        elif k == "map":
            out[f] = r["table"].get(v, 0)
        elif k == "prefix":
            out[f] = r["p"] + v
        elif k == "suffix_trim":
            out[f] = v[:-len(r["s"])] if v.endswith(r["s"]) else v
        elif k == "abs_cap":
            out[f] = min(abs(v), r["cap"])
        elif k == "mod":
            out[f] = v % r["m"]
        elif k == "bool_flip":
            out[f] = not v
    return out


def probe_for(rule, rng):
    """A record that exercises exactly this rule's field with a telling value."""
    f, k = rule["field"], rule["kind"]
    if k == "strip":
        return {f: "  hi  "}
    if k == "lower":
        return {f: "AbC"}
    if k == "upper":
        return {f: "AbC"}
    if k == "clamp":
        return {f: rule["hi"] + 5}
    if k == "default":
        return {}
    if k == "round_to":
        return {f: rule["mult"] * 3 + 3}
    if k == "map":
        return {f: list(rule["table"])[0]}
    if k == "prefix":
        return {f: "core"}
    if k == "suffix_trim":
        return {f: "name" + rule["s"]}
    if k == "abs_cap":
        return {f: -(rule["cap"] + 10)}
    if k == "mod":
        return {f: rule["m"] * 2 + 3}
    if k == "bool_flip":
        return {f: True}
    return {f: 1}


def per_rule_probes(rules, seed):
    rng = random.Random(seed + 1)
    return [(probe_for(r, rng), r) for r in rules]


STUB = '''"""{spec}"""


def normalize(record):
    raise NotImplementedError


def main():
    assert normalize({{}}) == {{{defaults}}}
    print("OK")


if __name__ == "__main__":
    main()
'''

TASK_MD = """# Implement normalize(record) in input.py per the docstring.
- Edit ONLY input.py. `python input.py` must print OK and exit 0.
- EVERY numbered rule is graded by hidden tests. Implement all of them.
Reply DONE when finished."""


def defaults_repr(rules):
    d = {}
    for r in rules:
        if r["kind"] == "default":
            d[r["field"]] = r["val"]
    return ", ".join(f'"{k}": {v}' for k, v in d.items())


def make(out_dir, n):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rules = make_rules(n, seed=1000 + n)
    (out / "input.py").write_text(STUB.format(spec=spec_text(rules), defaults=defaults_repr(rules)), encoding="utf-8")
    (out / "TASK.md").write_text(TASK_MD, encoding="utf-8")
    # persist grader material next to it (referee-only)
    probes = per_rule_probes(rules, seed=1000 + n)
    key = [{"field": r["field"], "kind": r["kind"], "probe": p, "expected": apply_rules(p, rules)} for p, r in probes]
    (out / "_key.json").write_text(json.dumps({"rules": rules, "key": key}), encoding="utf-8")


def grade(arm_dir, n):
    import importlib.util
    arm = Path(arm_dir)
    key = json.loads((arm / "_key.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(f"scale_{arm.name}", arm / "input.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        fn = mod.normalize
    except Exception as exc:
        print(json.dumps({"arm": arm.name, "n": n, "load_error": f"{type(exc).__name__}: {exc}", "recall": 0.0}))
        return
    hits, misses = 0, []
    for entry in key["key"]:
        try:
            got = fn(dict(entry["probe"]))
            ok = json.loads(json.dumps(got)) == entry["expected"]
        except Exception:
            ok = False
        if ok:
            hits += 1
        else:
            misses.append(entry["field"] + ":" + entry["kind"])
    total = len(key["key"])
    print(json.dumps({"arm": arm.name, "n": n, "recall": round(hits / total, 4),
                      "hits": hits, "total": total, "dropped": misses[:15]}))


if __name__ == "__main__":
    if sys.argv[1] == "make":
        make(sys.argv[2], int(sys.argv[3]))
    else:
        grade(sys.argv[2], int(sys.argv[3]))
