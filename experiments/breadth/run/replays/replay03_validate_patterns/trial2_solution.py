def validate_patterns(patterns: list[str]) -> list[bool]:
    """Validate a list of wildcard patterns.

    Returns True if each pattern is well-formed, False otherwise.
    """
    return [is_valid_pattern(p) for p in patterns]


def is_valid_pattern(pattern: str) -> bool:
    """Check if a single wildcard pattern is well-formed."""
    i = 0
    while i < len(pattern):
        if pattern[i] == '[':
            # Start of character class
            result = validate_char_class(pattern, i)
            if result is None:
                return False
            i = result
        elif pattern[i] == '\\':
            # Outside a class, backslash is an escape prefix
            i += 1
            if i >= len(pattern):
                return False  # Trailing backslash is malformed
            i += 1
        else:
            # Regular character: *, ?, or any other character
            i += 1

    return True


def validate_char_class(pattern: str, start: int) -> int | None:
    """Validate a character class starting at index start (pointing to '[').

    Returns the index after ']' if valid, None if malformed.
    Inside a character class, backslash is a literal member (not an escape).
    """
    i = start + 1

    # Check for negation (!)
    if i < len(pattern) and pattern[i] == '!':
        i += 1

    # Must have at least one character
    if i >= len(pattern):
        return None  # Unclosed class

    # If ']' is the first member, it's literal
    if pattern[i] == ']':
        i += 1

    # Process the rest of the class
    while i < len(pattern):
        if pattern[i] == ']':
            return i + 1  # Found closing bracket

        # Inside a class, check for ranges (char-char where - is not at edges)
        if i + 2 < len(pattern) and pattern[i + 1] == '-' and pattern[i + 2] != ']':
            # This is a range: check if low <= high
            low = ord(pattern[i])
            high = ord(pattern[i + 2])
            if low > high:
                return None  # Invalid range
            i += 3
        else:
            # Just a regular character (including '\' which is literal in classes)
            i += 1

    return None  # Unclosed class
