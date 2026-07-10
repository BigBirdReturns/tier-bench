def count_matches(pattern: str, words: list[str]) -> int:
    """Count how many words match the wildcard pattern."""
    # Parse and validate pattern
    parsed = parse_pattern(pattern)

    # Match each word
    count = 0
    for word in words:
        if matches_word(parsed, word):
            count += 1

    return count


def parse_pattern(pattern: str):
    """Parse pattern and raise ValueError if malformed."""
    parts = []
    i = 0

    while i < len(pattern):
        if pattern[i] == '*':
            parts.append(('*', None))
            i += 1
        elif pattern[i] == '?':
            parts.append(('?', None))
            i += 1
        elif pattern[i] == '[':
            # Parse character class
            i += 1
            if i >= len(pattern):
                raise ValueError("Unclosed character class")

            negate = False
            if pattern[i] == '!':
                negate = True
                i += 1
                if i >= len(pattern):
                    raise ValueError("Unclosed character class")

            # Collect all characters in the class until we find ]
            class_start = i
            while i < len(pattern) and pattern[i] != ']':
                i += 1

            if i >= len(pattern):
                raise ValueError("Unclosed character class")

            class_content = pattern[class_start:i]
            i += 1  # Skip ]

            # Parse class_content to extract characters
            chars = parse_class_content(class_content)

            parts.append(('class', (negate, chars)))
        elif pattern[i] == '\\':
            # Escape (outside character class)
            if i + 1 >= len(pattern):
                raise ValueError("Trailing escape")
            i += 1
            parts.append(('literal', pattern[i]))
            i += 1
        else:
            parts.append(('literal', pattern[i]))
            i += 1

    return parts


def parse_class_content(content: str):
    """Parse character class content into a set of characters.

    Inside a character class:
    - ] as first member is literal
    - - at edges (start or end) is literal
    - a-z is a range (if low > high, raises ValueError)
    - backslash is a literal character (not an escape prefix)
    """
    chars = set()

    if not content:
        return chars

    i = 0

    # Handle ] as first member
    if content[0] == ']':
        chars.add(']')
        i = 1

    # Process remaining content
    while i < len(content):
        # Look ahead to see if this is part of a range
        # Range pattern: X-Y where X, Y are characters and - is not at edges
        if (i + 2 < len(content) and
            content[i + 1] == '-' and
            content[i + 2] != ']'):
            # This is a range: content[i] - content[i + 2]
            start_ord = ord(content[i])
            end_ord = ord(content[i + 2])
            if start_ord > end_ord:
                raise ValueError("Invalid range in character class")
            for c in range(start_ord, end_ord + 1):
                chars.add(chr(c))
            i += 3
        else:
            chars.add(content[i])
            i += 1

    return chars


def matches_word(parts, word):
    """Check if word matches the parsed pattern."""
    return match_pattern(parts, 0, word, 0)


def match_pattern(parts, part_idx, word, word_idx):
    """Recursive pattern matching."""

    # Base case: we've matched all parts
    if part_idx >= len(parts):
        # Pattern is exhausted; word must also be exhausted
        return word_idx >= len(word)

    if parts[part_idx][0] == '*':
        # * matches any sequence (including empty)
        # Try matching 0 characters, then 1, 2, etc.
        for i in range(word_idx, len(word) + 1):
            if match_pattern(parts, part_idx + 1, word, i):
                return True
        return False

    elif parts[part_idx][0] == '?':
        # ? matches exactly one character
        if word_idx >= len(word):
            return False
        return match_pattern(parts, part_idx + 1, word, word_idx + 1)

    elif parts[part_idx][0] == 'class':
        # Character class
        if word_idx >= len(word):
            return False

        negate, chars = parts[part_idx][1]
        char = word[word_idx]

        in_class = char in chars
        if negate:
            in_class = not in_class

        if in_class:
            return match_pattern(parts, part_idx + 1, word, word_idx + 1)
        return False

    elif parts[part_idx][0] == 'literal':
        # Literal character
        if word_idx >= len(word) or word[word_idx] != parts[part_idx][1]:
            return False
        return match_pattern(parts, part_idx + 1, word, word_idx + 1)

    return False
