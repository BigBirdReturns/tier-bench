def wildcard_match(pattern: str, text: str) -> bool:
    def parse_pattern_tokens(pattern):
        tokens = []
        i = 0
        while i < len(pattern):
            if pattern[i] == '*':
                tokens.append(('STAR',))
                i += 1
            elif pattern[i] == '?':
                tokens.append(('QUESTION',))
                i += 1
            elif pattern[i] == '[':
                is_negated, char_set, end_idx = parse_char_class(pattern, i)
                tokens.append(('CHARCLASS', (is_negated, char_set)))
                i = end_idx + 1
            elif pattern[i] == '\\':
                if i + 1 >= len(pattern):
                    raise ValueError()
                tokens.append(('LITERAL', pattern[i + 1]))
                i += 2
            else:
                tokens.append(('LITERAL', pattern[i]))
                i += 1
        return tokens

    def parse_char_class(pattern, start_idx):
        idx = start_idx + 1
        is_negated = False

        if idx < len(pattern) and pattern[idx] == '!':
            is_negated = True
            idx += 1

        chars = set()
        ranges = []

        if idx < len(pattern) and pattern[idx] == ']':
            chars.add(']')
            idx += 1

        while idx < len(pattern):
            if pattern[idx] == ']':
                return is_negated, (chars, ranges), idx

            if idx + 2 < len(pattern) and pattern[idx + 1] == '-' and pattern[idx + 2] != ']':
                start_char = pattern[idx]
                end_char = pattern[idx + 2]
                if ord(start_char) > ord(end_char):
                    raise ValueError()
                ranges.append((start_char, end_char))
                idx += 3
            else:
                chars.add(pattern[idx])
                idx += 1

        raise ValueError()

    def char_in_class(char, is_negated, char_set):
        chars, ranges = char_set
        in_class = char in chars
        for start, end in ranges:
            if ord(start) <= ord(char) <= ord(end):
                in_class = True
                break
        return not in_class if is_negated else in_class

    tokens = parse_pattern_tokens(pattern)
    memo = {}

    def match(token_idx, text_idx):
        if (token_idx, text_idx) in memo:
            return memo[(token_idx, text_idx)]

        if token_idx == len(tokens):
            result = text_idx == len(text)
        else:
            token = tokens[token_idx]
            if token[0] == 'STAR':
                result = match(token_idx + 1, text_idx)
                if not result and text_idx < len(text):
                    result = match(token_idx, text_idx + 1)
            elif token[0] == 'QUESTION':
                result = match(token_idx + 1, text_idx + 1) if text_idx < len(text) else False
            elif token[0] == 'CHARCLASS':
                is_negated, char_set = token[1]
                result = match(token_idx + 1, text_idx + 1) if text_idx < len(text) and char_in_class(text[text_idx], is_negated, char_set) else False
            else:
                char = token[1]
                result = match(token_idx + 1, text_idx + 1) if text_idx < len(text) and text[text_idx] == char else False

        memo[(token_idx, text_idx)] = result
        return result

    return match(0, 0)
