from typing import Iterable, List, TypeVar

T = TypeVar("T")


def stable_unique(items: Iterable[T]) -> List[T]:
    """Return a list of the first occurrence of each value in items, preserving order.

    Equality is determined by Python's `==` operator and no hashing is required.
    Input items and their members are not mutated.
    """
    uniques: List[T] = []

    for item in items:
        for existing in uniques:
            if existing == item:
                break
        else:
            uniques.append(item)

    return uniques