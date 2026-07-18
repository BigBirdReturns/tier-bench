from typing import Any, Iterable, List, TypeVar

T = TypeVar("T")


def stable_unique(items: Iterable[T]) -> List[T]:
    """Return unique values from items in stable (first-occurrence) order.

    Equality is determined by Python's == operator. Supports unhashable values,
    including nested lists and dictionaries.
    """
    result: List[T] = []

    for item in items:
        if not any(item == existing for existing in result):
            result.append(item)

    return result