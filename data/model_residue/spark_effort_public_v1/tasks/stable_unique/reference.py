def stable_unique(items):
    result = []
    for item in items:
        if not any(item == prior for prior in result):
            result.append(item)
    return result

