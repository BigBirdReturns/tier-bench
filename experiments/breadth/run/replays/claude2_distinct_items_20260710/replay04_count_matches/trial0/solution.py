def count_matches(pattern: str, words: list[str]) -> int:
    """Count how many words match the pattern entirely."""
    # Parse and validate pattern first
    parsed = parse_pattern(pattern)

    # Count matches
    count = 0
    for word in words:
        if matches_pattern(word, parsed):
            count += 1
    return count


def parse_pattern(pattern: str):
    """Parse pattern and validate it. Returns a list of pattern elements."""
    i = 0
    elements = []

    while i < len(pattern):
        if pattern[i] == '*':
            elements.append(('star', None))
            i += 1
        elif pattern[i] == '?':
            elements.append(('question', None))
            i += 1
        elif pattern[i] == '[':
            # Parse character class
            char_class, end_idx = parse_char_class(pattern, i)
            elements.append(('class', char_class))
            i = end_idx
        elif pattern[i] == '\\':
            # Escape sequence (outside character class)
            if i + 1 >= len(pattern):
                raise ValueError("trailing backslash")
            escaped_char = pattern[i + 1]
            elements.append(('literal', escaped_char))
            i += 2
        else:
            # Regular literal character
            elements.append(('literal', pattern[i]))
            i += 1

    return elements


def parse_char_class(pattern: str, start: int):
    """Parse a character class [...]. Returns ((chars, negated), end_index)."""
    if pattern[start] != '[':
        raise ValueError("Expected '['")

    i = start + 1
    if i >= len(pattern):
        raise ValueError("unclosed character class")

    # Check for negation
    negated = False
    if pattern[i] == '!':
        negated = True
        i += 1

    chars = set()

    # ] as first member is literal
    if i < len(pattern) and pattern[i] == ']':
        chars.add(']')
        i += 1

    # Parse class members
    while i < len(pattern) and pattern[i] != ']':
        # Handle escape
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("trailing backslash")
            current_char = pattern[i + 1]
            i += 2
        else:
            current_char = pattern[i]
            i += 1

        # Check if followed by - and then another character (not ])
        if i < len(pattern) and pattern[i] == '-' and i + 1 < len(pattern) and pattern[i + 1] != ']':
            # This is a range
            i += 1  # Skip dash

            # Get end character
            if pattern[i] == '\\':
                if i + 1 >= len(pattern):
                    raise ValueError("trailing backslash")
                end_char = pattern[i + 1]
                i += 2
            else:
                end_char = pattern[i]
                i += 1

            # Validate range
            if ord(current_char) > ord(end_char):
                raise ValueError(f"bad range {current_char}-{end_char}")

            # Add all characters in range
            for c in range(ord(current_char), ord(end_char) + 1):
                chars.add(chr(c))
        else:
            # Not a range, just add the character
            chars.add(current_char)

    if i >= len(pattern):
        raise ValueError("unclosed character class")

    # i is now at ']'
    return (chars, negated), i + 1


def matches_pattern(word: str, pattern_elements: list) -> bool:
    """Check if word matches the pattern."""
    return matches_helper(word, 0, pattern_elements, 0)


def matches_helper(word: str, w_idx: int, pattern: list, p_idx: int) -> bool:
    """Recursive helper to check if word matches pattern."""

    # Base case: both at end
    if p_idx >= len(pattern):
        return w_idx >= len(word)

    elem_type, elem_val = pattern[p_idx]

    if elem_type == 'star':
        # Try matching 0 characters (skip this * and continue)
        if matches_helper(word, w_idx, pattern, p_idx + 1):
            return True
        # Try matching 1+ characters
        if w_idx < len(word):
            if matches_helper(word, w_idx + 1, pattern, p_idx):
                return True
        return False

    elif elem_type == 'question':
        # Must match exactly one character
        if w_idx >= len(word):
            return False
        return matches_helper(word, w_idx + 1, pattern, p_idx + 1)

    elif elem_type == 'class':
        # Must match one character from the class
        if w_idx >= len(word):
            return False
        chars, negated = elem_val
        char_in_class = word[w_idx] in chars
        if negated:
            char_in_class = not char_in_class
        if not char_in_class:
            return False
        return matches_helper(word, w_idx + 1, pattern, p_idx + 1)

    else:  # literal
        # Must match the exact character
        if w_idx >= len(word) or word[w_idx] != elem_val:
            return False
        return matches_helper(word, w_idx + 1, pattern, p_idx + 1)
