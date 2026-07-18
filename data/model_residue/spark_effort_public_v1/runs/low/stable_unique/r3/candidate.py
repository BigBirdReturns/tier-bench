def stable_unique(items):
    """
    Return a new list containing the first occurrence of each value in `items`,
    preserving original order. Equality uses Python's `==` operator, so unhashable
    items (including nested lists/dicts) are handled naturally.
    """
    result = []
    for item in items:
        for existing in result:
            if existing == item:
                break
        else:
            result.append(item)
    return result