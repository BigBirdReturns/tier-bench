def wildcard_match(pattern: str, text: str) -> bool:
    # Validate pattern for malformed cases
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2
        elif pattern[i] == '[':
            j = i + 1
            if j < len(pattern) and pattern[j] == '!':
                j += 1
            if j < len(pattern) and pattern[j] == ']':
                j += 1
            start_of_content = j
            while j < len(pattern) and pattern[j] != ']':
                j += 1
            if j >= len(pattern):
                raise ValueError("Unclosed class")

            # Validate ranges
            k = start_of_content
            while k < j:
                if k + 2 < j and pattern[k + 1] == '-':
                    if ord(pattern[k]) > ord(pattern[k + 2]):
                        raise ValueError("Reversed range")
                    k += 3
                else:
                    k += 1

            i = j + 1
        else:
            i += 1

    # Match pattern against text
    memo = {}

    def match(p_idx, t_idx):
        if (p_idx, t_idx) in memo:
            return memo[(p_idx, t_idx)]

        result = False

        if p_idx == len(pattern):
            result = (t_idx == len(text))
        elif pattern[p_idx] == '*':
            for i in range(t_idx, len(text) + 1):
                if match(p_idx + 1, i):
                    result = True
                    break
        elif pattern[p_idx] == '?':
            if t_idx < len(text):
                result = match(p_idx + 1, t_idx + 1)
        elif pattern[p_idx] == '[':
            if t_idx < len(text):
                j = p_idx + 1
                negated = False
                if pattern[j] == '!':
                    negated = True
                    j += 1

                chars = set()
                if pattern[j] == ']':
                    chars.add(']')
                    j += 1

                while pattern[j] != ']':
                    if j + 2 < len(pattern) and pattern[j + 1] == '-' and pattern[j + 2] != ']':
                        for c in range(ord(pattern[j]), ord(pattern[j + 2]) + 1):
                            chars.add(chr(c))
                        j += 3
                    else:
                        chars.add(pattern[j])
                        j += 1

                char_in_class = text[t_idx] in chars
                if negated:
                    char_in_class = not char_in_class

                if char_in_class:
                    result = match(j + 1, t_idx + 1)
        elif pattern[p_idx] == '\\':
            if t_idx < len(text) and text[t_idx] == pattern[p_idx + 1]:
                result = match(p_idx + 2, t_idx + 1)
        else:
            if t_idx < len(text) and text[t_idx] == pattern[p_idx]:
                result = match(p_idx + 1, t_idx + 1)

        memo[(p_idx, t_idx)] = result
        return result

    return match(0, 0)
