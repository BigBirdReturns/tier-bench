def slugify(text: str) -> str:
    """
    Convert text to a URL-friendly slug.

    Rules:
    - Lowercase
    - Strip leading/trailing whitespace
    - Replace spaces and underscores with hyphens
    - Remove any character that is not alphanumeric or hyphen
    - Collapse multiple hyphens into one
    - Return empty string for empty input
    """
    result = []
    for char in text.strip().lower():
        if char == " " or char == "_":
            char = "-"
        if ("a" <= char <= "z") or ("0" <= char <= "9") or char == "-":
            if char != "-" or not result or result[-1] != "-":
                result.append(char)
    return "".join(result)

def main():
    cases = [
        (" Hello_World  ", "hello-world"),
        ("A--B", "a-b"),
        ("", ""),
        ("Spaced   out", "spaced-out"),
        ("Café", "caf"),
    ]
    for s, exp in cases:
        got = slugify(s)
        if got != exp:
            raise SystemExit(f"FAIL {s!r}: {got!r} != {exp!r}")
    print("OK")

if __name__ == "__main__":
    main()
