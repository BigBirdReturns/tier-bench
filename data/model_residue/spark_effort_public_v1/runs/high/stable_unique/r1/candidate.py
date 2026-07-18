```python
from collections.abc import Iterable
from typing import TypeVar, List

T = TypeVar("T")


def stable_unique(items: Iterable[T]) -> List[T]:
    """
    Return items' first occurrences in original order, using Python's == equality.
    Handles unhashable values (e.g., nested lists/dicts) without mutation.
    """
    unique_items: List[T] = []

    for item in items:
        for seen in unique_items:
            if item == seen:
                break
        else:
            unique_items.append(item)

    return unique_items
```