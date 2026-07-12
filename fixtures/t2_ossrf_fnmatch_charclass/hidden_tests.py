"""Hidden grader for t2_ossrf_fnmatch_charclass — never shown to the solver.

Expected values are machine-derived from the vendored CPython v3.12.0
Lib/fnmatch.py (data/oss_replay/upstream/cpython_fnmatch_v3.12.0/) by
experiments/oss_replay/generate_vectors.py; CI `--check` proves splice
equivalence with the shipping implementation and guards drift of this block.
"""
import input as candidate

VECTORS = [
    ('[abc]', 0, '[abc]', 5),
    ('x[a-z]y', 1, '[a-z]', 6),
    ('[!x]', 0, '[^x]', 4),
    ('[a\\]', 0, '[a\\\\]', 4),
    ('[a\\\\b]', 0, '[a\\\\\\\\b]', 6),
    ('[abc', 0, '\\[', 1),
    ('[]', 0, '\\[', 1),
    ('[!]', 0, '\\[', 1),
    ('[]a]', 0, '[]a]', 4),
    ('[]]', 0, '[]]', 3),
    ('[!]a]', 0, '[^]a]', 5),
    ('[[a]', 0, '[\\[a]', 4),
    ('[^ab]', 0, '[\\^ab]', 5),
    ('[a-]', 0, '[a\\-]', 4),
    ('[-a]', 0, '[\\-a]', 4),
    ('[--0]', 0, '[\\--0]', 5),
    ('[\\-z]', 0, '[\\\\-z]', 5),
    ('[b-a]', 0, '(?!)', 5),
    ('[a&b]', 0, '[a\\&b]', 5),
    ('[~|]', 0, '[\\~\\|]', 4),
    ('ab[!0-9]', 2, '[^0-9]', 8),
    ('[z-a-9]', 0, '[\\-9]', 7),
    ('[!-]', 0, '[^\\-]', 4),
]


def main() -> int:
    passed = 0
    failures = []
    for pat, i, frag, nxt in VECTORS:
        try:
            got = tuple(candidate.translate_charclass(pat, i))
        except Exception as exc:  # noqa: BLE001 — a crash is a miss, not a crash of the grader
            got = ("<raised %s: %s>" % (type(exc).__name__, exc), None)
        if got == (frag, nxt):
            passed += 1
        else:
            failures.append((pat, i, got, (frag, nxt)))
    print(f"SCORE {passed}/{len(VECTORS)}")
    for pat, i, got, want in failures:
        print(f"  FAIL ({pat!r}, {i}): got {got}, want {want}")
    return 0 if passed == len(VECTORS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
