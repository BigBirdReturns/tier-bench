def validate_patterns(patterns: list[str]) -> list[bool]:
    return [is_valid_pattern(p) for p in patterns]


def is_valid_pattern(pattern: str) -> bool:
    i = 0
    while i < len(pattern):
        if pattern[i] == '[':
            # Parse character class
            i, valid = parse_char_class(pattern, i)
            if not valid:
                return False
        elif pattern[i] == '\\':
            # Escape outside class
            if i + 1 >= len(pattern):
                return False  # Trailing backslash with nothing after
            i += 2
        else:
            # Regular character or wildcard (* or ?)
            i += 1

    return True


def parse_char_class(pattern: str, start: int) -> tuple[int, bool]:
    """Parse a character class starting at position start (which should point to '[').

    Returns (next_position, is_valid).
    - Inside a class, backslash is a literal member, not an escape prefix.
    - Ranges are specified as X-Y where X and Y are single characters.
    - A range is invalid if ord(X) > ord(Y).
    - Leading ! negates the class.
    - ] is literal if it's the first member.
    - - is literal if it's at the edges.
    """
    i = start + 1

    if i >= len(pattern):
        return i, False  # Unclosed class

    # Check for negation (!)
    if pattern[i] == '!':
        i += 1

    if i >= len(pattern):
        return i, False  # Unclosed class after !

    # Handle ] as first character (it's literal, not the closing bracket)
    if pattern[i] == ']':
        i += 1

    # Parse class content
    while i < len(pattern):
        if pattern[i] == ']':
            # Found the closing bracket
            return i + 1, True

        # Current character
        current = pattern[i]

        # Look ahead for range operator (-)
        # A range is specified as X-Y where:
        # - X is the current character
        # - Y is the character after the -
        # - The - is not at the edge of the class
        if (i + 1 < len(pattern) and
            pattern[i + 1] == '-' and
            i + 2 < len(pattern) and
            pattern[i + 2] != ']'):
            # This is a range: current - pattern[i+2]
            end_char = pattern[i + 2]
            if ord(current) > ord(end_char):
                return i, False  # Invalid range (low > high)
            i += 3
        else:
            # Not a range, just a regular character (or - as literal)
            i += 1

    return i, False  # Unclosed class (we never found ])
