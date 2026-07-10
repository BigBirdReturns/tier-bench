def charclass_filter(cls: str, chars: str) -> str:
    # Check if the class is closed (ends with ']')
    if not cls.endswith(']'):
        raise ValueError("Unclosed character class")

    # Check if the class starts with '['
    if not cls.startswith('['):
        raise ValueError("Invalid character class format")

    # Extract the content between [ and ]
    content = cls[1:-1]

    # Check for negation
    negate = False
    if content and content[0] == '!':
        negate = True
        content = content[1:]

    # Parse the character class
    matched_chars = set()
    i = 0
    while i < len(content):
        # Special case: literal ']' as first character
        if i == 0 and content[i] == ']':
            matched_chars.add(']')
            i += 1
        # Literal '-' at start or end
        elif content[i] == '-' and (i == 0 or i == len(content) - 1):
            matched_chars.add('-')
            i += 1
        # Check for range (e.g., 'a-z')
        # A range is X-Y where there are at least 3 characters starting from current position
        elif i + 2 < len(content) and content[i + 1] == '-':
            start = content[i]
            end = content[i + 2]
            start_ord = ord(start)
            end_ord = ord(end)
            if start_ord > end_ord:
                raise ValueError("Invalid range in character class")
            for c in range(start_ord, end_ord + 1):
                matched_chars.add(chr(c))
            i += 3
        # Regular character
        else:
            matched_chars.add(content[i])
            i += 1

    # Filter chars based on the class
    result = []
    for c in chars:
        if negate:
            if c not in matched_chars:
                result.append(c)
        else:
            if c in matched_chars:
                result.append(c)

    return ''.join(result)
