```python
from typing import Any, Iterable, List


def stable_unique(items: Iterable[Any]) -> List[Any]:
    """Return first occurrences from *items* in original order using == equality."""
    unique_items: List[Any] = []
    for value in items:
        for existing in unique_items:
            if existing == value:
                break
        else:
            unique_items.append(value)
    return unique_items
```