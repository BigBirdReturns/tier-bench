"""Shell-pattern character classes — CPython's exact translation rules.

Implement:

    def translate_charclass(pat: str, i: int) -> tuple[str, int]

`pat` is a shell (fnmatch) pattern and `pat[i] == '['` — the start of a
character-class token. Return `(fragment, next_i)`: the regular-expression
fragment this token translates to, and the index of the first pattern
character after the token. This is the `[...]` rule of the translator used by
every Python installation on earth; implement it exactly.

The rules (complete — every sentence is normative):

1. SCAN for the closing bracket. Let j = i+1. If pat[j] is '!', advance j once
   (negation marker). Then, if pat[j] is ']', advance j once — a ']' in the
   first content position is CONTENT, not the closer. Then advance j until
   pat[j] == ']' or the pattern ends. If no closer was found, the class is
   UNTERMINATED: the '[' alone is literal — return ('\\[', i + 1) and let the
   caller rescan everything after the '['. (Note what this implies for '[!]':
   its only ']' is consumed by the first-position rule, so it is unterminated.)

2. Let stuff = pat[i+1:j] (everything between the brackets, exclusive).

3. NO HYPHEN: if '-' does not occur in stuff, backslashes in stuff are
   literals and must be doubled: stuff = stuff.replace('\\', '\\\\').

4. HYPHENS: otherwise split stuff into range chunks. Let s = i+1 and start
   the search at k = s+2 if pat[s] == '!' else s+1 (a hyphen in the first
   content position cannot end a range). Repeatedly find k = pat.find('-', k, j);
   on each hit append pat[s:k] to the chunk list, set s = k+1, and resume the
   search at k+3 (a range consumes the character after the hyphen). When no
   hyphen remains: if pat[s:j] is non-empty append it as the final chunk,
   otherwise the pattern ends with a dangling '-' — append '-' to the LAST
   chunk instead. Then remove invalid ranges: walking k from the last chunk
   index down to 1, if chunks[k-1][-1] > chunks[k][0] (the range's low end
   sorts above its high end), merge: chunks[k-1] = chunks[k-1][:-1] +
   chunks[k][1:], and delete chunks[k]. Finally rejoin with '-' after escaping
   each chunk's backslashes ('\\' -> '\\\\') and hyphens ('-' -> '\\-'):
   stuff = '-'.join(escaped chunks).

5. SET OPERATIONS: in the result of rule 3 or 4, escape every '&', '~' and
   '|' with a preceding backslash (regex set-operation characters).

6. EMPTY: if stuff is now empty, the class can never match — return
   ('(?!)', j + 1). If stuff is exactly '!', a negated empty class matches
   any character — return ('.', j + 1).

7. FIRST CHARACTER: if stuff starts with '!', replace that '!' with '^'
   (negation). Otherwise, if stuff starts with '^' or '[', prefix it with a
   backslash (those are literals here, not regex operators).

8. Return ('[' + stuff + ']', j + 1).

The knot: inside a shell character class, backslash is a LITERAL character,
never an escape. Every rule above is graded, including the interactions the
visible checks do not exercise.
"""


def translate_charclass(pat: str, i: int) -> tuple[str, int]:
    raise NotImplementedError


def main() -> int:
    checks = [
        (("[abc]", 0), ("[abc]", 5)),
        (("x[a-z]y", 1), ("[a-z]", 6)),
        (("[!x]", 0), ("[^x]", 4)),
    ]
    ok = True
    for args, want in checks:
        got = translate_charclass(*args)
        if tuple(got) != want:
            print(f"FAIL {args}: got {got}, want {want}")
            ok = False
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
