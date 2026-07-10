def count_matches(pattern: str, words: list[str]) -> int:
    # Validate pattern for malformed cases
    _validate_pattern(pattern)

    # Count matching words
    count = 0
    for word in words:
        if _matches(pattern, word):
            count += 1
    return count


def _validate_pattern(pattern: str):
    """Validate pattern for malformed syntax."""
    # Check for trailing backslash (outside character classes)
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2
        elif pattern[i] == '[':
            # Find the closing ]
            j = i + 1
            if j >= len(pattern):
                raise ValueError("Unclosed character class")

            # Skip leading ! if present
            if pattern[j] == '!':
                j += 1

            # Skip leading ] if present (it's literal as first member)
            if j < len(pattern) and pattern[j] == ']':
                j += 1

            # Find closing ]
            while j < len(pattern) and pattern[j] != ']':
                j += 1

            if j >= len(pattern):
                raise ValueError("Unclosed character class")

            # Validate ranges in this character class
            _validate_character_class(pattern, i + 1, j)

            i = j + 1
        else:
            i += 1


def _validate_character_class(pattern: str, start: int, end: int):
    """Validate ranges within a character class."""
    j = start

    # Skip leading !
    if j < end and pattern[j] == '!':
        j += 1

    # Skip leading ] if present
    if j < end and pattern[j] == ']':
        j += 1

    # Check for invalid ranges
    while j < end:
        if j + 2 <= end and pattern[j + 1] == '-' and j + 2 < end and pattern[j + 2] != ']':
            # This looks like a range
            low = ord(pattern[j])
            high = ord(pattern[j + 2])
            if low > high:
                raise ValueError(f"Invalid range")
            j += 3
        else:
            j += 1


def _matches(pattern: str, word: str) -> bool:
    """Check if word matches the entire pattern."""
    return _match_recursive(pattern, 0, word, 0)


def _match_recursive(pattern: str, p_idx: int, word: str, w_idx: int) -> bool:
    """Recursive matching logic."""
    # Base case: both pattern and word exhausted
    if p_idx == len(pattern):
        return w_idx == len(word)

    # Handle escaped characters (outside character classes)
    if pattern[p_idx] == '\\':
        if w_idx >= len(word) or pattern[p_idx + 1] != word[w_idx]:
            return False
        return _match_recursive(pattern, p_idx + 2, word, w_idx + 1)

    # Handle * (any sequence, including empty)
    elif pattern[p_idx] == '*':
        # Try matching zero characters
        if _match_recursive(pattern, p_idx + 1, word, w_idx):
            return True
        # Try matching one or more characters
        if w_idx < len(word):
            if _match_recursive(pattern, p_idx, word, w_idx + 1):
                return True
        return False

    # Handle ? (exactly one character)
    elif pattern[p_idx] == '?':
        if w_idx >= len(word):
            return False
        return _match_recursive(pattern, p_idx + 1, word, w_idx + 1)

    # Handle character class [...]
    elif pattern[p_idx] == '[':
        if w_idx >= len(word):
            return False

        # Parse character class
        j = p_idx + 1
        negated = False

        if j < len(pattern) and pattern[j] == '!':
            negated = True
            j += 1

        # Collect characters that match in this class
        matching_chars = set()

        # Handle ] as literal first member
        if j < len(pattern) and pattern[j] == ']':
            matching_chars.add(']')
            j += 1

        # Parse rest of the character class
        while j < len(pattern) and pattern[j] != ']':
            if j + 2 <= len(pattern) and pattern[j + 1] == '-' and j + 2 < len(pattern) and pattern[j + 2] != ']':
                # This is a range: pattern[j] to pattern[j+2]
                low = ord(pattern[j])
                high = ord(pattern[j + 2])
                for code in range(low, high + 1):
                    matching_chars.add(chr(code))
                j += 3
            else:
                # Regular character (backslash is literal inside class)
                matching_chars.add(pattern[j])
                j += 1

        # Check if current word character matches the class
        char_in_class = word[w_idx] in matching_chars
        if negated:
            char_in_class = not char_in_class

        if not char_in_class:
            return False

        # Continue after the closing ]
        j += 1  # Skip the ]
        return _match_recursive(pattern, j, word, w_idx + 1)

    # Handle regular character
    else:
        if w_idx >= len(word) or pattern[p_idx] != word[w_idx]:
            return False
        return _match_recursive(pattern, p_idx + 1, word, w_idx + 1)
