def wildcard_match(pattern: str, text: str) -> bool:
    tokens = []
    i = 0

    while i < len(pattern):
        if pattern[i] == '[':
            # Parse character class
            i += 1

            # Check for negation
            negated = False
            if i < len(pattern) and pattern[i] == '!':
                negated = True
                i += 1

            # Collect all characters/ranges in this class
            chars = set()

            # Handle literal ] as first character
            if i < len(pattern) and pattern[i] == ']':
                chars.add(']')
                i += 1

            # Parse rest of class (backslash is literal here)
            while i < len(pattern) and pattern[i] != ']':
                # Look ahead for range pattern: char-char
                if i + 2 < len(pattern) and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                    # This is a range
                    low = pattern[i]
                    high = pattern[i + 2]
                    if ord(low) > ord(high):
                        raise ValueError("Reversed range")
                    for c in range(ord(low), ord(high) + 1):
                        chars.add(chr(c))
                    i += 3
                else:
                    # Single character (including literal backslash)
                    chars.add(pattern[i])
                    i += 1

            if i >= len(pattern):
                raise ValueError("Unclosed class")

            i += 1  # Skip closing ]
            tokens.append(('class', chars, negated))
        elif pattern[i] == '*':
            tokens.append(('*',))
            i += 1
        elif pattern[i] == '?':
            tokens.append(('?',))
            i += 1
        elif pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 1
            tokens.append(('literal', pattern[i]))
            i += 1
        else:
            tokens.append(('literal', pattern[i]))
            i += 1

    # Match using recursion with memoization
    memo = {}

    def match(t_idx, p_idx):
        if (t_idx, p_idx) in memo:
            return memo[(t_idx, p_idx)]

        if p_idx == len(tokens):
            result = t_idx == len(text)
        else:
            token = tokens[p_idx]

            if token[0] == '*':
                # Try matching 0 or more characters
                result = False
                for i in range(t_idx, len(text) + 1):
                    if match(i, p_idx + 1):
                        result = True
                        break
            elif token[0] == '?':
                result = t_idx < len(text) and match(t_idx + 1, p_idx + 1)
            elif token[0] == 'class':
                chars, negated = token[1], token[2]
                if t_idx >= len(text):
                    result = False
                else:
                    char_match = text[t_idx] in chars
                    if negated:
                        char_match = not char_match
                    result = char_match and match(t_idx + 1, p_idx + 1)
            elif token[0] == 'literal':
                result = t_idx < len(text) and text[t_idx] == token[1] and match(t_idx + 1, p_idx + 1)

        memo[(t_idx, p_idx)] = result
        return result

    return match(0, 0)
