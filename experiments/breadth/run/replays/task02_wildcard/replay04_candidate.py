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
        elif pattern[i] == '*':
            tokens.append(('star', None))
            i += 1
        elif pattern[i] == '?':
            tokens.append(('question', None))
            i += 1
        elif pattern[i] == '[':
            j = i + 1
            negate = False
            if j < len(pattern) and pattern[j] == '!':
                negate = True
                j += 1
            start_of_class = j
            if j < len(pattern) and pattern[j] == ']':
                j += 1
            while j < len(pattern) and pattern[j] != ']':
                j += 1
            if j >= len(pattern):
                raise ValueError("Unclosed character class")
            class_content = pattern[start_of_class:j]
            char_set = set()
            k = 0
            while k < len(class_content):
                if k + 2 < len(class_content) and class_content[k + 1] == '-':
                    low = class_content[k]
                    high = class_content[k + 2]
                    if low > high:
                        raise ValueError("Reversed range")
                    for c in range(ord(low), ord(high) + 1):
                        char_set.add(chr(c))
                    k += 3
                else:
                    char_set.add(class_content[k])
                    k += 1
            tokens.append(('class', (char_set, negate)))
            i = j + 1
        else:
            tokens.append(('literal', pattern[i]))
            i += 1

    # Dynamic programming
    m, n = len(tokens), len(text)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = True

    for i in range(1, m + 1):
        if tokens[i - 1][0] == 'star':
            dp[i][0] = dp[i - 1][0]
        else:
            break

    for i in range(1, m + 1):
        for j in range(0, n + 1):
            token_type, token_val = tokens[i - 1]
            if token_type == 'star':
                dp[i][j] = dp[i - 1][j]
                if j > 0 and dp[i][j - 1]:
                    dp[i][j] = True
            elif token_type == 'question':
                if j > 0 and dp[i - 1][j - 1]:
                    dp[i][j] = True
            elif token_type == 'literal':
                if j > 0 and text[j - 1] == token_val and dp[i - 1][j - 1]:
                    dp[i][j] = True
            elif token_type == 'class':
                if j > 0:
                    char_set, negate = token_val
                    char_in_class = text[j - 1] in char_set
                    if negate:
                        char_in_class = not char_in_class
                    if char_in_class and dp[i - 1][j - 1]:
                        dp[i][j] = True

    return dp[m][n]
