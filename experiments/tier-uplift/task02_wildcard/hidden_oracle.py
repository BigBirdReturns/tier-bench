#!/usr/bin/env python3
"""Hidden oracle grader for task 02 (wildcard_match).

A hand-verified reference implementation is the oracle. A candidate is graded on
(a) a curated set of tricky hand-verified cases and (b) a large deterministically
enumerated set — for each, the candidate must agree with the reference, INCLUDING
raising ValueError exactly where the reference does. The reference is checked
against the curated cases at import so a broken oracle can't silently pass junk.

    python hidden_oracle.py <candidate.py>     ->  SCORE ok/total (+ sample fails)
"""
import importlib.util
import itertools
import sys

_SENTINEL = object()


# ---------------------------------------------------------------- reference
def _compile(pattern):
    """pattern -> list of tokens; raise ValueError on malformed."""
    toks, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            toks.append(("lit", pattern[i + 1])); i += 2
        elif c == "*":
            toks.append(("any",)); i += 1
        elif c == "?":
            toks.append(("one",)); i += 1
        elif c == "[":
            j = i + 1
            neg = False
            if j < n and pattern[j] == "!":
                neg = True; j += 1
            members, first = [], True
            while True:
                if j >= n:
                    raise ValueError("unclosed class")
                ch = pattern[j]
                if ch == "]" and not first:
                    j += 1; break
                first = False
                # range a-z: ch, '-', hi   (only if '-' not last and next != ']')
                if (j + 2 < n and pattern[j + 1] == "-" and pattern[j + 2] != "]"):
                    lo, hi = ch, pattern[j + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("bad range")
                    members.append(("range", lo, hi)); j += 3
                else:
                    members.append(("ch", ch)); j += 1
            toks.append(("class", neg, members)); i = j
        else:
            toks.append(("lit", c)); i += 1
    return toks


def _class_ok(members, neg, ch):
    hit = False
    for m in members:
        if m[0] == "ch" and ch == m[1]:
            hit = True; break
        if m[0] == "range" and m[1] <= ch <= m[2]:
            hit = True; break
    return hit != neg


def _ref(pattern, text):
    toks = _compile(pattern)
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def m(ti, si):
        if ti == len(toks):
            return si == len(text)
        t = toks[ti]
        if t[0] == "any":
            return m(ti + 1, si) or (si < len(text) and m(ti, si + 1))
        if si >= len(text):
            return False
        if t[0] == "one":
            return m(ti + 1, si + 1)
        if t[0] == "lit":
            return text[si] == t[1] and m(ti + 1, si + 1)
        if t[0] == "class":
            return _class_ok(t[2], t[1], text[si]) and m(ti + 1, si + 1)
        return False

    return m(0, 0)


# ---------------------------------------------------------------- cases
CURATED = [
    ("*", "", True), ("*", "abc", True), ("a*c", "abbbc", True), ("a*c", "abbb", False),
    ("?", "", False), ("?", "a", True), ("a?c", "abc", True), ("a?c", "ac", False),
    ("[a-c]", "b", True), ("[a-c]", "d", False), ("[!a-c]", "d", True), ("[!a-c]", "b", False),
    ("[]a]", "]", True), ("[]a]", "a", True), ("[]a]", "b", False),
    (r"\*", "*", True), (r"\*", "a", False), (r"\?", "?", True), (r"\[", "[", True),
    ("a[b-d]*z", "acxyz", True), ("a[b-d]*z", "aexyz", False),
    ("*.txt", "a.txt", True), ("*.txt", "a.txtx", False), ("**", "abc", True),
    ("", "", True), ("", "a", False), ("a*", "a", True), ("*a", "ba", True), ("*a*", "xax", True),
    ("[a-c]*[x-z]", "boohooz", True), ("[a-c]*[x-z]", "boohoo", False),
    ("?*", "a", True), ("?*", "", False), ("a*b*c", "axbyc", True), ("a*b*c", "axbyd", False),
]
# patterns the reference MUST reject
CURATED_INVALID = ["[abc", "a\\", "[", "[a-", "[!", "[z-a]", "[a-c"]


def _check_reference():
    for p, t, want in CURATED:
        got = _ref(p, t)
        assert got == want, f"REFERENCE WRONG on ({p!r},{t!r}): {got} != {want}"
    for p in CURATED_INVALID:
        try:
            _ref(p, "x"); raise AssertionError(f"REFERENCE should reject {p!r}")
        except ValueError:
            pass


_check_reference()


def _enumerate_cases():
    """Deterministic case set: curated + enumerated small patterns/texts."""
    cases = []  # (pattern, text)
    for p, t, _ in CURATED:
        cases.append((p, t))
    for p in CURATED_INVALID:
        cases.append((p, "x"))
    palpha = "ab*?[]!-\\"
    talpha = "ab]"
    for plen in (1, 2, 3):
        for ptup in itertools.product(palpha, repeat=plen):
            p = "".join(ptup)
            for tlen in (0, 1, 2):
                for ttup in itertools.product(talpha, repeat=tlen):
                    cases.append((p, "".join(ttup)))
    # de-dup, cap
    seen, out = set(), []
    for c in cases:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


CASES = _enumerate_cases()


def _oracle(p, t):
    try:
        return _ref(p, t)
    except ValueError:
        return _SENTINEL  # oracle says: must raise


# ---------------------------------------------------------------- grade
def load(path):
    spec = importlib.util.spec_from_file_location("cand", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wildcard_match


def grade(path):
    try:
        fn = load(path)
    except Exception as e:
        return 0, len(CASES), [f"LOAD ERROR: {e}"]
    ok, fails = 0, []
    for p, t in CASES:
        want = _oracle(p, t)
        try:
            got = fn(p, t)
            if want is _SENTINEL:
                fails.append(f"({p!r},{t!r}): returned {got!r}, oracle wants ValueError")
            elif bool(got) == want:
                ok += 1
            else:
                fails.append(f"({p!r},{t!r}): got {got!r}, want {want}")
        except ValueError:
            if want is _SENTINEL:
                ok += 1
            else:
                fails.append(f"({p!r},{t!r}): raised ValueError, want {want}")
        except Exception as e:
            fails.append(f"({p!r},{t!r}): {type(e).__name__}: {e}")
    return ok, len(CASES), fails


if __name__ == "__main__":
    ok, total, fails = grade(sys.argv[1])
    print(f"SCORE {ok}/{total}  ({100*ok//total}%)")
    for f in fails[:25]:
        print("  FAIL", f)
    if len(fails) > 25:
        print(f"  ... and {len(fails) - 25} more")
