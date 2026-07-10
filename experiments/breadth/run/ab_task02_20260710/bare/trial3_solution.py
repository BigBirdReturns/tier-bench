def wildcard_match(pattern: str, text: str) -> bool:
    # Tokenize the pattern to identify special constructs
    tokens = []
    i = 0

    while i < len(pattern):
        if pattern[i] == '\\':
            # Escape sequence
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            tokens.append(('LITERAL', pattern[i + 1]))
            i += 2
        elif pattern[i] == '*':
            tokens.append(('STAR', None))
            i += 1
        elif pattern[i] == '?':
            tokens.append(('QUESTION', None))
            i += 1
        elif pattern[i] == '[':
            # Character class
            j = i + 1
            negated = False

            # Check for negation
            if j < len(pattern) and pattern[j] == '!':
                negated = True
                j += 1

            # Collect characters and ranges
            class_chars = set()
            class_ranges = []

            # Special case: ] as first character is literal
            if j < len(pattern) and pattern[j] == ']':
                class_chars.add(']')
                j += 1

            # Parse the rest of the class
            while j < len(pattern) and pattern[j] != ']':
                if pattern[j] == '\\':
                    # Escaped character in class
                    if j + 1 >= len(pattern):
                        raise ValueError("Unclosed character class")
                    class_chars.add(pattern[j + 1])
                    j += 2
                elif j + 2 < len(pattern) and pattern[j + 1] == '-' and pattern[j + 2] != ']':
                    # This is a range (X-Y where Y is not ])
                    start_char = pattern[j]
                    end_char = pattern[j + 2]
                    if start_char > end_char:
                        raise ValueError("Reversed range")
                    class_ranges.append((start_char, end_char))
                    j += 3
                elif pattern[j] == '-':
                    # Trailing dash or dash not forming a range
                    class_chars.add('-')
                    j += 1
                else:
                    class_chars.add(pattern[j])
                    j += 1

            # Check for unclosed class
            if j >= len(pattern):
                raise ValueError("Unclosed character class")

            tokens.append(('CLASS', (negated, class_chars, class_ranges)))
            i = j + 1
        else:
            # Literal character
            tokens.append(('LITERAL', pattern[i]))
            i += 1

    # Helper function to check if a character matches a token
    def matches_token(token, char):
        token_type, value = token
        if token_type == 'LITERAL':
            return value == char
        elif token_type == 'QUESTION':
            return True
        elif token_type == 'CLASS':
            negated, chars, ranges = value
            in_class = char in chars
            if not in_class:
                for start, end in ranges:
                    if start <= char <= end:
                        in_class = True
                        break
            return (not negated) if in_class else negated
        return False

    # Dynamic programming approach
    # dp[i][j] = True if tokens[0:i] matches text[0:j]
    m, n = len(tokens), len(text)
    dp = [[False] * (n + 1) for _ in range(m + 1)]

    # Base case: empty pattern matches empty text
    dp[0][0] = True

    # Handle leading stars (star can match empty string)
    for i in range(1, m + 1):
        if tokens[i - 1][0] == 'STAR':
            dp[i][0] = dp[i - 1][0]
        else:
            break

    # Fill the DP table
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if tokens[i - 1][0] == 'STAR':
                # Star can match zero characters (dp[i-1][j])
                # or one or more characters (dp[i][j-1])
                dp[i][j] = dp[i - 1][j] or dp[i][j - 1]
            else:
                # For other tokens, they must match exactly one character
                if matches_token(tokens[i - 1], text[j - 1]):
                    dp[i][j] = dp[i - 1][j - 1]

    return dp[m][n]
