from __future__ import annotations

import re

FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)\n?```", re.DOTALL)
ENCODING_RE = re.compile(r"^#.*coding[:=]\s*[-\w.]+", re.IGNORECASE)

def _looks_like_file(text: str) -> bool:
    # Must contain at least one newline or be a short single-line python file (rare).
    if "\n" in text:
        return True
    # Allow very small single-line files like: "print(1)"
    return bool(re.search(r"[()=]", text))

def sanitize_model_output(text: str) -> tuple[str | None, str | None]:
    """Return (sanitized_text, reason_if_rejected)."""
    if text is None:
        return None, "empty_output"

    s = text.strip()

    # If the model returned a single fenced code block, extract it.
    m = FENCE_RE.fullmatch(s)
    if m:
        s = m.group(1).strip()

    if not _looks_like_file(s):
        return None, "does_not_look_like_file"

    # Reject obvious prose introductions on the first non-comment hint.
    lowered = s.lstrip().lower()
    bad_starts = [
        "here is",
        "here's",
        "sure,",
        "i updated",
        "i have updated",
        "explanation",
        "note:",
        "ok,",
    ]
    if any(lowered.startswith(b) for b in bad_starts):
        return None, "looks_like_prose"

    # Reject markdown list formatting that suggests commentary,
    # but only if it appears outside of string literals (docstrings are valid Python).
    try:
        import ast
        ast.parse(s)
        # Valid Python — skip all heuristics, accept it.
        return s, None
    except SyntaxError:
        # Not valid Python (yet). Apply the heuristic.
        if re.search(r"^\s*[-*]\s+", s, flags=re.MULTILINE):
            return None, "looks_like_markdown_list"

    # If the first line is not a comment/shebang/encoding and contains sentence punctuation, reject.
    lines = s.splitlines()
    if lines:
        first = lines[0].strip()
        if first and not first.startswith("#") and not first.startswith("import") and not first.startswith("from"):
            if re.search(r"[.!?]$", first) and not re.search(r"\)\s*$", first):
                return None, "first_line_looks_like_sentence"

    # Allow shebang and encoding, nothing else special.
    if lines and lines[0].startswith("#!"):
        pass
    if len(lines) >= 2 and ENCODING_RE.match(lines[0]):
        pass

    return s, None
