def wildcard_match(pattern: str, text: str) -> bool:
    # Parse pattern into tokens
    tokens = []
    i = 0
    while i < len(pattern):
        if pattern[i] == '*':
            tokens.append(('*',))
            i += 1
        elif pattern[i] == '?':
            tokens.append(('?',))
            i += 1
        elif pattern[i] == '[':
            # Parse character class
            i += 1
            if i >= len(pattern):
                raise ValueError("Unclosed character class")

            negated = False
            if pattern[i] == '!':
                negated = True
                i += 1

            class_chars = set()
            ranges = []

            # Special case: first char can be ]
            if i < len(pattern) and pattern[i] == ']':
                class_chars.add(']')
                i += 1

            # Parse class content
            while i < len(pattern):
                if pattern[i] == ']':
                    tokens.append(('class', class_chars, ranges, negated))
                    i += 1
                    break

                # Look ahead for a range X-Y
                if i + 2 < len(pattern) and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                    low = pattern[i]
                    high = pattern[i + 2]
                    if ord(low) > ord(high):
                        raise ValueError("Reversed range")
                    ranges.append((low, high))
                    i += 3
                elif pattern[i] == '-' and i + 1 < len(pattern) and pattern[i + 1] == ']':
                    # Literal - at the end
                    class_chars.add('-')
                    i += 1
                else:
                    # Regular character (including backslash inside class)
                    class_chars.add(pattern[i])
                    i += 1
            else:
                raise ValueError("Unclosed character class")
        elif pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 1
            tokens.append(('literal', pattern[i]))
            i += 1
        else:
            tokens.append(('literal', pattern[i]))
            i += 1

    # DP matching: dp[i][j] = can we match tokens[0:i] with text[0:j]?
    n = len(tokens)
    m = len(text)

    dp = [[False] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = True

    # Handle leading * (can match empty string)
    for i in range(1, n + 1):
        if tokens[i - 1][0] == '*':
            dp[i][0] = dp[i - 1][0]
        else:
            break

    # Fill DP table
    for i in range(1, n + 1):
        for j in range(m + 1):
            token = tokens[i - 1]

            if token[0] == 'literal':
                if j > 0 and text[j - 1] == token[1] and dp[i - 1][j - 1]:
                    dp[i][j] = True
            elif token[0] == '?':
                if j > 0 and dp[i - 1][j - 1]:
                    dp[i][j] = True
            elif token[0] == '*':
                # Match 0 characters: dp[i-1][j]
                dp[i][j] = dp[i - 1][j]
                # Match 1+ characters: dp[i][j-1]
                if j > 0:
                    dp[i][j] = dp[i][j] or dp[i][j - 1]
            elif token[0] == 'class':
                if j > 0:
                    _, class_chars, ranges, negated = token
                    char = text[j - 1]
                    in_class = char in class_chars or any(ord(low) <= ord(char) <= ord(high) for low, high in ranges)
                    if negated:
                        in_class = not in_class
                    if in_class and dp[i - 1][j - 1]:
                        dp[i][j] = True

    return dp[n][m]
