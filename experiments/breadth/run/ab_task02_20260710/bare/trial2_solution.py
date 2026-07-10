def wildcard_match(pattern: str, text: str) -> bool:
    # Tokenize the pattern
    tokens = []
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            tokens.append(('literal', pattern[i + 1]))
            i += 2
        elif pattern[i] == '[':
            # Parse character class
            j = i + 1
            negated = False
            if j < len(pattern) and pattern[j] == '!':
                negated = True
                j += 1

            # Special case: ] as first member
            members = []
            if j < len(pattern) and pattern[j] == ']':
                members.append(']')
                j += 1

            # Parse rest of class
            while j < len(pattern) and pattern[j] != ']':
                if pattern[j] == '-' and j + 1 < len(pattern) and pattern[j + 1] != ']' and len(members) > 0:
                    # This is a range
                    start = members.pop()
                    j += 1
                    end = pattern[j]
                    if ord(start) > ord(end):
                        raise ValueError("Reversed range")
                    # Expand range
                    for ch_code in range(ord(start), ord(end) + 1):
                        members.append(chr(ch_code))
                    j += 1
                else:
                    # It's a literal character
                    members.append(pattern[j])
                    j += 1

            if j >= len(pattern):
                raise ValueError("Unclosed class")

            tokens.append(('class', set(members), negated))
            i = j + 1
        elif pattern[i] == '*':
            tokens.append(('star', None))
            i += 1
        elif pattern[i] == '?':
            tokens.append(('question', None))
            i += 1
        else:
            tokens.append(('literal', pattern[i]))
            i += 1

    # Match tokens against text
    def match_tokens(ti, text_i):
        if ti >= len(tokens):
            return text_i >= len(text)

        token = tokens[ti]

        if token[0] == 'literal':
            if text_i >= len(text) or text[text_i] != token[1]:
                return False
            return match_tokens(ti + 1, text_i + 1)

        elif token[0] == 'question':
            if text_i >= len(text):
                return False
            return match_tokens(ti + 1, text_i + 1)

        elif token[0] == 'class':
            if text_i >= len(text):
                return False
            ch = text[text_i]
            members, negated = token[1], token[2]
            if negated:
                if ch not in members:
                    return match_tokens(ti + 1, text_i + 1)
                return False
            else:
                if ch in members:
                    return match_tokens(ti + 1, text_i + 1)
                return False

        elif token[0] == 'star':
            # Try matching 0 characters
            if match_tokens(ti + 1, text_i):
                return True
            # Try matching 1+ characters
            if text_i < len(text):
                return match_tokens(ti, text_i + 1)
            return False

    return match_tokens(0, 0)
