def wildcard_match(pattern: str, text: str) -> bool:
    # Parse and validate pattern
    parsed = []
    i = 0

    while i < len(pattern):
        if pattern[i] == '\\':
            # Escape sequence
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            parsed.append(('literal', pattern[i + 1]))
            i += 2

        elif pattern[i] == '[':
            # Character class
            i += 1
            negate = False
            if i < len(pattern) and pattern[i] == '!':
                negate = True
                i += 1

            chars = set()
            # First char can be ] literally
            if i < len(pattern) and pattern[i] == ']':
                chars.add(']')
                i += 1

            # Parse rest of class
            while i < len(pattern):
                if pattern[i] == ']':
                    i += 1
                    break

                # Check if this is a range
                if i + 2 < len(pattern) and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                    start_char = pattern[i]
                    end_char = pattern[i + 2]
                    if ord(start_char) > ord(end_char):
                        raise ValueError("Reversed range")
                    for c in range(ord(start_char), ord(end_char) + 1):
                        chars.add(chr(c))
                    i += 3
                else:
                    chars.add(pattern[i])
                    i += 1
            else:
                # Didn't find closing ]
                raise ValueError("Unclosed character class")

            parsed.append(('class', chars, negate))

        elif pattern[i] == '*':
            parsed.append(('star',))
            i += 1

        elif pattern[i] == '?':
            parsed.append(('question',))
            i += 1

        else:
            parsed.append(('literal', pattern[i]))
            i += 1

    # Match text against parsed pattern
    def match(p_idx, t_idx):
        # Base case: we've consumed all pattern tokens
        if p_idx == len(parsed):
            return t_idx == len(text)

        token = parsed[p_idx]

        if token[0] == 'literal':
            if t_idx >= len(text) or text[t_idx] != token[1]:
                return False
            return match(p_idx + 1, t_idx + 1)

        elif token[0] == 'question':
            if t_idx >= len(text):
                return False
            return match(p_idx + 1, t_idx + 1)

        elif token[0] == 'class':
            if t_idx >= len(text):
                return False
            chars, negate = token[1], token[2]
            char_matches = text[t_idx] in chars
            if negate:
                char_matches = not char_matches
            if not char_matches:
                return False
            return match(p_idx + 1, t_idx + 1)

        elif token[0] == 'star':
            # Star can match 0 or more characters
            # Try matching 0, then 1, then 2, etc.
            for num_matched in range(len(text) - t_idx + 1):
                if match(p_idx + 1, t_idx + num_matched):
                    return True
            return False

    return match(0, 0)
