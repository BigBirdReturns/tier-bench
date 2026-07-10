def wildcard_match(pattern: str, text: str) -> bool:
    def parse_pattern(p):
        """Parse pattern into tokens. Raises ValueError for malformed patterns."""
        i = 0
        tokens = []
        while i < len(p):
            if p[i] == '\\':
                if i + 1 >= len(p):
                    raise ValueError("Trailing backslash")
                tokens.append(('ESCAPED', p[i + 1]))
                i += 2
            elif p[i] == '[':
                # Parse character class
                i += 1
                negate = False
                if i < len(p) and p[i] == '!':
                    negate = True
                    i += 1
                chars = set()
                # First char can be ]
                if i < len(p) and p[i] == ']':
                    chars.add(']')
                    i += 1
                # Parse range and chars
                while i < len(p) and p[i] != ']':
                    if i + 2 < len(p) and p[i + 1] == '-' and p[i + 2] != ']':
                        # Range
                        start = p[i]
                        end = p[i + 2]
                        if ord(start) > ord(end):
                            raise ValueError("Reversed range")
                        for c in range(ord(start), ord(end) + 1):
                            chars.add(chr(c))
                        i += 3
                    else:
                        chars.add(p[i])
                        i += 1
                if i >= len(p):
                    raise ValueError("Unclosed character class")
                i += 1  # Skip ]
                tokens.append(('CLASS', chars, negate))
            elif p[i] == '*':
                tokens.append(('STAR',))
                i += 1
            elif p[i] == '?':
                tokens.append(('QUESTION',))
                i += 1
            else:
                tokens.append(('LITERAL', p[i]))
                i += 1
        return tokens

    tokens = parse_pattern(pattern)

    # Use memoization for efficiency
    memo = {}

    def matches(t_idx, token_idx):
        """Recursively check if text matches tokens."""
        if (t_idx, token_idx) in memo:
            return memo[(t_idx, token_idx)]

        # Base cases
        if token_idx == len(tokens):
            result = t_idx == len(text)
        elif t_idx == len(text):
            # Check if remaining tokens are all STAR
            result = all(tokens[j][0] == 'STAR' for j in range(token_idx, len(tokens)))
        else:
            token = tokens[token_idx]

            if token[0] == 'STAR':
                # Try matching zero characters
                result = matches(t_idx, token_idx + 1)
                if not result:
                    # Try matching one or more characters
                    result = matches(t_idx + 1, token_idx)
            elif token[0] == 'LITERAL':
                result = text[t_idx] == token[1] and matches(t_idx + 1, token_idx + 1)
            elif token[0] == 'ESCAPED':
                result = text[t_idx] == token[1] and matches(t_idx + 1, token_idx + 1)
            elif token[0] == 'QUESTION':
                result = matches(t_idx + 1, token_idx + 1)
            elif token[0] == 'CLASS':
                chars, negate = token[1], token[2]
                matched = text[t_idx] in chars
                if negate:
                    matched = not matched
                result = matched and matches(t_idx + 1, token_idx + 1)
            else:
                result = False

        memo[(t_idx, token_idx)] = result
        return result

    return matches(0, 0)
