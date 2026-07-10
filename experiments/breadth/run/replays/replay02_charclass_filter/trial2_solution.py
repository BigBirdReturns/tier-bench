def charclass_filter(cls: str, chars: str) -> str:
    """Filter characters by wildcard character class.

    cls: Character class token like [abc], [a-z], [!x], etc.
    chars: String to filter
    Returns: Characters from chars that match the class
    """
    # Check if class is properly closed
    if not cls.endswith(']'):
        raise ValueError()

    # Remove the opening [ and closing ]
    content = cls[1:-1]

    # Check for negation
    negate = False
    if content.startswith('!'):
        negate = True
        content = content[1:]

    # Build the set of matching characters
    match_set = set()

    i = 0
    while i < len(content):
        # Handle ] as first character (literal member)
        if i == 0 and content[i] == ']':
            match_set.add(']')
            i += 1
            continue

        # Check for range: we need current char, a dash, and a next char
        # i + 2 < len(content) ensures indices i, i+1, i+2 all exist
        if i + 2 < len(content) and content[i+1] == '-':
            start_char = content[i]
            end_char = content[i+2]

            start_ord = ord(start_char)
            end_ord = ord(end_char)

            if start_ord > end_ord:
                raise ValueError()

            # Add all characters in the range
            for c_ord in range(start_ord, end_ord + 1):
                match_set.add(chr(c_ord))

            i += 3
        else:
            # Single character (including - if it's first, last, or not followed by another char)
            match_set.add(content[i])
            i += 1

    # Filter the input characters
    result = ""
    for c in chars:
        if negate:
            if c not in match_set:
                result += c
        else:
            if c in match_set:
                result += c

    return result
