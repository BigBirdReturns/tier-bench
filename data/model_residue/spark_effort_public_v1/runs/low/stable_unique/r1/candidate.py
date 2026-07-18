from collections.abc import Iterable
from typing import Any, List


def stable_unique(items: Iterable[Any]) -> List[Any]:
    """
    Return a new list containing the first occurrence of each value in `items`,
    preserving original order and using Python equality (==).

    Works for unhashable values (e.g., dicts, lists) and does not mutate `items`
    or any of its members.
    """
    result: List[Any] = []
    for value in items:
        for existing in result:
            if value == existing:
                break
        else:
            result.append(value)
    return result