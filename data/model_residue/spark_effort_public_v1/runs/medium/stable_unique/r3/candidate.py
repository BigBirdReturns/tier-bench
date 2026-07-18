def stable_unique(items):
    """Return first occurrence of each value from items, preserving original order.

    Equality is determined using Python ``==`` and works for unhashable values
    (e.g., lists and dictionaries) without requiring hashing.
    """
    uniques = []
    for item in items:
        for existing in uniques:
            if item == existing:
                break
        else:
            uniques.append(item)
    return uniques