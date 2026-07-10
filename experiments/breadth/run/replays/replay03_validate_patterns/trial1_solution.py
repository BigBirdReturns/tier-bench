def validate_patterns(patterns: list[str]) -> list[bool]:
    result = []
    for pattern in patterns:
        result.append(_is_valid_pattern(pattern))
    return result


def _is_valid_pattern(pattern: str) -> bool:
    """Validate a single wildcard pattern."""
    i = 0
    while i < len(pattern):
        char = pattern[i]

        if char == '[':
            # Find the closing ] for this character class
            end_pos = _find_class_end(pattern, i)
            if end_pos == -1:
                return False  # Unclosed character class
            # Validate the character class contents
            if not _is_valid_character_class(pattern, i, end_pos):
                return False
            i = end_pos + 1

        elif char == '\\':
            # Escape sequence (only outside character classes)
            if i + 1 >= len(pattern):
                return False  # Trailing backslash with nothing after
            i += 2  # Skip the backslash and the escaped character

        else:
            # *, ?, or any other character is valid at the top level
            i += 1

    return True


def _find_class_end(pattern: str, start: int) -> int:
    """Find the closing ] for the [ at position start. Return -1 if not found."""
    i = start + 1

    # Handle leading ! (negation)
    if i < len(pattern) and pattern[i] == '!':
        i += 1

    # Handle leading ] as literal (first member of class)
    if i < len(pattern) and pattern[i] == ']':
        i += 1

    # Now find the closing ]
    while i < len(pattern):
        if pattern[i] == ']':
            return i
        i += 1

    return -1  # Not found


def _is_valid_character_class(pattern: str, start: int, end: int) -> bool:
    """Validate character class from start (where '[' is) to end (where ']' is)."""
    i = start + 1

    # Handle leading ! (negation marker)
    if i < end and pattern[i] == '!':
        i += 1

    # Handle leading ] as a literal ]
    if i < end and pattern[i] == ']':
        i += 1

    # Parse the rest of the class
    while i < end:
        char = pattern[i]

        # Check for range: char-char (but only if there's a char after the -)
        if i + 2 < end and pattern[i + 1] == '-':
            low = ord(char)
            high = ord(pattern[i + 2])
            # Range is invalid if low > high (out of order)
            if low > high:
                return False
            i += 3  # Skip the range (char, -, next_char)

        # Check for trailing - (at the end of the class, before ])
        elif char == '-' and i + 1 == end:
            i += 1  # Trailing - is a literal

        else:
            i += 1

    return True
