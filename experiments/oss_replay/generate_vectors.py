#!/usr/bin/env python3
"""OSS replay field — vector generator + drift guard for ossrf_fnmatch_charclass_001.

The hidden grader's expected values are not hand-written. They are produced by
a REFERENCE implementation of CPython v3.12.0's character-class translation
(the `[...]` branch of `fnmatch.translate`, Lib/fnmatch.py lines 93-145),
transcribed here, and that reference is proven faithful two ways:

  1. SPLICE EQUIVALENCE — a full `translate` built from the reference class
     segment plus the surrounding upstream machinery must reproduce the
     vendored upstream module byte-for-byte on the whole pattern corpus.
  2. NAIVE FAILS — a naive implementation (backslash treated as an escape
     inside the class, the exact miss the task02 capture recorded in the wild)
     must fail at least one hidden vector; if it stops failing, the vectors
     stopped discriminating.

`--check` (CI) re-runs both proofs and verifies the baked VECTORS block in the
fixture's hidden grader matches a fresh regeneration. `--emit` prints the
VECTORS block for pasting into the hidden grader.

Upstream provenance: data/oss_replay/upstream/cpython_fnmatch_v3.12.0/
(exact bytes, PSF-2.0, pinned to release tag v3.12.0 = 0fb6e700c2f9).
"""
from __future__ import annotations

import ast
import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
UPSTREAM = REPO / "data/oss_replay/upstream/cpython_fnmatch_v3.12.0/fnmatch.py"
UPSTREAM_SHA256 = "6683da36e47af523f3f41e18ad244d837783e19e98911cc0b7415dea81494ebc"
HIDDEN = REPO / "fixtures/t2_ossrf_fnmatch_charclass/hidden_tests.py"


def reference_translate_charclass(pat: str, i: int) -> tuple[str, int]:
    """Exact transcription of the `[` branch of CPython v3.12.0 fnmatch.translate."""
    assert pat[i] == "["
    n = len(pat)
    j = i + 1
    if j < n and pat[j] == "!":
        j += 1
    if j < n and pat[j] == "]":
        j += 1
    while j < n and pat[j] != "]":
        j += 1
    if j >= n:
        return "\\[", i + 1
    s = i + 1
    stuff = pat[s:j]
    if "-" not in stuff:
        stuff = stuff.replace("\\", r"\\")
    else:
        chunks = []
        k = s + 2 if pat[s] == "!" else s + 1
        while True:
            k = pat.find("-", k, j)
            if k < 0:
                break
            chunks.append(pat[s:k])
            s = k + 1
            k = k + 3
        chunk = pat[s:j]
        if chunk:
            chunks.append(chunk)
        else:
            chunks[-1] += "-"
        for k in range(len(chunks) - 1, 0, -1):
            if chunks[k - 1][-1] > chunks[k][0]:
                chunks[k - 1] = chunks[k - 1][:-1] + chunks[k][1:]
                del chunks[k]
        stuff = "-".join(c.replace("\\", r"\\").replace("-", r"\-") for c in chunks)
    stuff = re.sub(r"([&~|])", r"\\\1", stuff)
    if not stuff:
        return "(?!)", j + 1
    if stuff == "!":
        return ".", j + 1
    if stuff[0] == "!":
        stuff = "^" + stuff[1:]
    elif stuff[0] in ("^", "["):
        stuff = "\\" + stuff
    return f"[{stuff}]", j + 1


def naive_translate_charclass(pat: str, i: int) -> tuple[str, int]:
    """The wild miss: backslash treated as an ESCAPE inside the class (it is a
    literal in fnmatch), plus no literal-first ']' rule. Must fail vectors."""
    n = len(pat)
    j = i + 1
    negate = j < n and pat[j] == "!"
    if negate:
        j += 1
    body = []
    while j < n and pat[j] != "]":
        if pat[j] == "\\" and j + 1 < n:
            body.append(re.escape(pat[j + 1]))
            j += 2
        else:
            body.append(pat[j])
            j += 1
    if j >= n:
        return "\\[", i + 1
    stuff = "".join(body)
    if not stuff:
        return "(?!)", j + 1
    return ("[^" if negate else "[") + stuff + "]", j + 1


def spliced_translate(pat: str, charclass) -> str:
    """Upstream v3.12.0 translate with the class branch delegated to `charclass`.
    Everything else is a faithful copy of the vendored module's logic."""
    STAR = object()
    res = []
    add = res.append
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            i += 1
            if (not res) or res[-1] is not STAR:
                add(STAR)
        elif c == "?":
            i += 1
            add(".")
        elif c == "[":
            frag, i = charclass(pat, i)
            add(frag)
        else:
            i += 1
            add(re.escape(c))
    inp, res, add = res, [], None
    out = []
    i, n = 0, len(inp)
    while i < n and inp[i] is not STAR:
        out.append(inp[i])
        i += 1
    while i < n:
        assert inp[i] is STAR
        i += 1
        if i == n:
            out.append(".*")
            break
        fixed = []
        while i < n and inp[i] is not STAR:
            fixed.append(inp[i])
            i += 1
        fixed = "".join(fixed)
        if i == n:
            out.append(".*")
            out.append(fixed)
        else:
            out.append(f"(?>.*?{fixed})")
    return fr"(?s:{''.join(out)})\Z"


# Whole-pattern corpus for the splice-equivalence proof (covers every class rule
# in context: stars, literals, multiple classes, all knot shapes).
CORPUS = [
    "[abc]", "[a-z]", "[!x]", "[^ab]", "[]a]", "[]]", "[!]a]", "[a\\]",
    "[a\\\\b]", "[abc", "[!]", "[]", "[[a]", "[a-]", "[-a]", "[--0]",
    "[\\-z]", "[a-z0-9_]", "[a&b]", "[~|]", "[b-a]", "[z-a-9]", "[0--]",
    "*.[ch]", "a[a\\]z", "x*[!0-9]y?", "[a-c-e]", "lib[!.]*.so", "??[]!]",
    "[a-]b-c]", "*[\\]*", "no_class_at_all*?", "[&&]", "[!!]", "[^^]",
    "deep[a\\]er[b-a]mix*", "[-]", "[!-]",
]

# Direct hidden-grader vectors: (pat, i) -> (fragment, next_i).
VECTOR_INPUTS = [
    ("[abc]", 0), ("x[a-z]y", 1), ("[!x]", 0),
    ("[a\\]", 0), ("[a\\\\b]", 0), ("[abc", 0), ("[]", 0), ("[!]", 0),
    ("[]a]", 0), ("[]]", 0), ("[!]a]", 0), ("[[a]", 0), ("[^ab]", 0),
    ("[a-]", 0), ("[-a]", 0), ("[--0]", 0), ("[\\-z]", 0), ("[b-a]", 0),
    ("[a&b]", 0), ("[~|]", 0), ("ab[!0-9]", 2), ("[z-a-9]", 0), ("[!-]", 0),
]


def load_upstream():
    data = UPSTREAM.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != UPSTREAM_SHA256:
        raise SystemExit(f"vendored upstream drifted: {digest} != {UPSTREAM_SHA256}")
    spec = importlib.util.spec_from_file_location("ossrf_upstream_fnmatch", UPSTREAM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def generate() -> list[tuple[str, int, str, int]]:
    return [(pat, i, *reference_translate_charclass(pat, i)) for pat, i in VECTOR_INPUTS]


def baked_vectors() -> list:
    tree = ast.parse(HIDDEN.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "VECTORS":
            return [tuple(v) for v in ast.literal_eval(node.value)]
    raise SystemExit(f"no VECTORS block found in {HIDDEN}")


def check() -> int:
    up = load_upstream()
    bad = [p for p in CORPUS if spliced_translate(p, reference_translate_charclass) != up.translate(p)]
    if bad:
        print(f"FAIL — splice mismatch vs upstream on {len(bad)} pattern(s): {bad[:5]}")
        return 1
    print(f"ok  splice == upstream translate on {len(CORPUS)}/{len(CORPUS)} corpus patterns")
    fresh = generate()
    naive_misses = [v for v in fresh if naive_translate_charclass(v[0], v[1]) != (v[2], v[3])]
    if not naive_misses:
        print("FAIL — the naive escape-inside-class implementation passes every vector; "
              "the hidden set no longer discriminates the knot")
        return 1
    print(f"ok  naive implementation fails {len(naive_misses)}/{len(fresh)} vectors (knot discriminates)")
    baked = baked_vectors()
    if baked != fresh:
        print("FAIL — baked hidden VECTORS drifted from regeneration; "
              "re-run --emit and update the hidden grader deliberately")
        return 1
    print(f"ok  {len(baked)} baked hidden vectors match regeneration byte-for-byte")
    return 0


def emit() -> int:
    print("VECTORS = [")
    for pat, i, frag, nxt in generate():
        print(f"    ({pat!r}, {i}, {frag!r}, {nxt}),")
    print("]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check()
    if a.emit:
        return emit()
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
