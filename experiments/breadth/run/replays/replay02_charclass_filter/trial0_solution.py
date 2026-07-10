def charclass_filter(cls: str, chars: str) -> str:
    # Verify the class is closed (has a terminating ])
    if not cls.endswith(']'):
        raise ValueError("Unclosed character class")

    # Check for opening [
    if not cls.startswith('['):
        raise ValueError("Invalid character class")

    # Extract the content between [ and ]
    content = cls[1:-1]

    # Check for negation
    negate = False
    if content and content[0] == '!':
        negate = True
        content = content[1:]

    # Build a set of matching characters
    matches = set()
    i = 0

    while i < len(content):
        # Check if this is part of a range
        if i + 1 < len(content) and content[i + 1] == '-' and i + 2 < len(content):
            # This is a range
            start_char = content[i]
            end_char = content[i + 2]
            start_code = ord(start_char)
            end_code = ord(end_char)

            if start_code > end_code:
                raise ValueError("Invalid range")

            for code in range(start_code, end_code + 1):
                matches.add(chr(code))
            i += 3
        else:
            # Single character
            matches.add(content[i])
            i += 1

    # Filter chars based on matches
    if negate:
        result = ''.join(c for c in chars if c not in matches)
    else:
        result = ''.join(c for c in chars if c in matches)

    return result
