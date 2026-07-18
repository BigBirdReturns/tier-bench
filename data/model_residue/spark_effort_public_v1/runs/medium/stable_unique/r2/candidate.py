def stable_unique(items):
    """Return first occurrences of each value in input order using == equality."""
    unique = []
    for item in items:
        for seen in unique:
            if seen == item:
                break
        else:
            unique.append(item)
    return unique