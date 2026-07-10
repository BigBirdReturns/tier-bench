def wildcard_match(pattern: str, text: str) -> bool:
    def parse_char_class(pattern, i):
        """Parse a character class starting at position i (after '[').
        Returns (set_of_chars, negated, next_i) or raises ValueError."""
        if i >= len(pattern):
            raise ValueError("Unclosed character class")

        negated = False
        if pattern[i] == '!':
            negated = True
            i += 1

        chars = set()

        # Handle ] as first character (literal)
        if i < len(pattern) and pattern[i] == ']':
            chars.add(']')
            i += 1

        while i < len(pattern):
            if pattern[i] == ']':
                return chars, negated, i + 1

            # Check for range (char1-char2)
            if i + 2 < len(pattern) and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                # This is a range
                start = ord(pattern[i])
                end = ord(pattern[i + 2])
                if start > end:
                    raise ValueError(f"Reversed range [{pattern[i]}-{pattern[i+2]}]")
                for code in range(start, end + 1):
                    chars.add(chr(code))
                i += 3
            else:
                # Single character or - at end
                chars.add(pattern[i])
                i += 1

        raise ValueError("Unclosed character class")

    def parse_pattern(pattern):
        """Parse pattern into tokens. Raises ValueError for invalid patterns."""
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
                chars, negated, next_i = parse_char_class(pattern, i + 1)
                if negated:
                    tokens.append(('negclass', chars))
                else:
                    tokens.append(('class', chars))
                i = next_i
            else:
                tokens.append(('literal', pattern[i]))
                i += 1
        return tokens

    tokens = parse_pattern(pattern)

    def match(ti, text_idx):
        """Match tokens[ti:] against text[text_idx:].
        Returns True if matches entire remaining text."""
        if ti == len(tokens):
            return text_idx == len(text)

        token_type, token_val = tokens[ti]

        if token_type == 'star':
            # * can match 0 or more characters
            # Try matching 0 characters first, then 1, 2, ...
            for consume in range(len(text) - text_idx + 1):
                if match(ti + 1, text_idx + consume):
                    return True
            return False

        elif token_type == 'literal':
            if text_idx >= len(text) or text[text_idx] != token_val:
                return False
            return match(ti + 1, text_idx + 1)

        elif token_type == 'question':
            if text_idx >= len(text):
                return False
            return match(ti + 1, text_idx + 1)

        elif token_type == 'class':
            if text_idx >= len(text) or text[text_idx] not in token_val:
                return False
            return match(ti + 1, text_idx + 1)

        elif token_type == 'negclass':
            if text_idx >= len(text) or text[text_idx] in token_val:
                return False
            return match(ti + 1, text_idx + 1)

        return False

    return match(0, 0)
