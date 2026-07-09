#!/usr/bin/env python3
"""task02 edge-family prober — new decisive cases, the SAME frozen oracle.

No new grading authority is created here: every expected verdict is computed
from tier-uplift task02's hand-verified reference (`hidden_oracle._ref`), the
invariant frozen when that shard shipped. This script only (a) enumerates the
eight probe groups from run/task02_edge_family.md and (b) scores a candidate's
agreement with the reference per group — isolating WHICH judgment boundary a
candidate gets wrong, where the flat oracle score only says THAT one exists.

    python edge_grade.py <candidate.py> [more.py ...]   # per-group profile
    python edge_grade.py --show                          # print frozen verdicts
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "experiments/tier-uplift/task02_wildcard"))
import hidden_oracle  # noqa: E402  (the frozen reference lives here)

PROBES: dict[str, list[tuple[str, str]]] = {
    "malformed_class_vs_valid_nonmatch": [
        ("[", "a"), ("[a", "a"), ("[\\]", "]b"), ("[\\]", "]]"), ("[\\]", "\\"),
    ],
    "escaped_literal_inside_class": [
        ("[\\*]", "*"), ("[\\*]", "a"), ("[\\?]", "?"), ("[a\\*b]", "*"),
    ],
    "escaped_range_boundary": [
        ("[a\\-z]", "-"), ("[a\\-z]", "m"), ("[a\\-z]", "a"), ("[\\--0]", "."),
    ],
    "trailing_escape": [
        ("\\", "\\"), ("a\\", "a"), ("ab\\", "ab"), ("[a]\\", "a"),
    ],
    "class_negation_edge": [
        ("[!]", "!"), ("[!]", "a"), ("[!a]", "a"), ("[!a]", "b"), ("[!!]", "!"),
    ],
    "literal_hyphen_edge": [
        ("[-a]", "-"), ("[-a]", "a"), ("[a-]", "-"), ("[-]", "-"), ("[!-]", "-"),
    ],
    "literal_closing_bracket_edge": [
        ("[]a]", "]"), ("[]a]", "a"), ("[]]", "]"), ("[!]a]", "b"), ("[!]a]", "]"),
    ],
    "escape_outside_class": [
        ("\\*", "*"), ("\\*", "a"), ("\\\\", "\\"), ("\\[a]", "[a]"), ("a\\?c", "a?c"),
    ],
}


def verdict(fn, pattern, text):
    try:
        return bool(fn(pattern, text))
    except ValueError:
        return "ValueError"
    except Exception as e:  # noqa: BLE001
        return f"crash:{type(e).__name__}"


def load(path: str):
    spec = importlib.util.spec_from_file_location("cand", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wildcard_match


def main() -> int:
    if "--show" in sys.argv:
        for group, cases in PROBES.items():
            print(f"[{group}]")
            for p, t in cases:
                print(f"  {p!r:14s} vs {t!r:8s} -> {verdict(hidden_oracle._ref, p, t)}")
        return 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    names = list(PROBES)
    print("candidate".ljust(44) + " ".join(n[:12].ljust(12) for n in names) + " overall")
    for path in sys.argv[1:]:
        try:
            fn = load(path)
        except Exception as e:  # noqa: BLE001
            print(f"{Path(path).as_posix()[-43:]:44s} UNLOADABLE ({type(e).__name__}) — transport casualty, not graded")
            continue
        cols, total_bad = [], 0
        for group, cases in PROBES.items():
            bad = sum(1 for p, t in cases if verdict(fn, p, t) != verdict(hidden_oracle._ref, p, t))
            total_bad += bad
            cols.append(("ok" if bad == 0 else f"{bad}/{len(cases)}X").ljust(12))
        print(f"{Path(path).as_posix()[-43:]:44s}" + " ".join(cols) + (" PASS" if total_bad == 0 else f" {total_bad} disagreements"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
