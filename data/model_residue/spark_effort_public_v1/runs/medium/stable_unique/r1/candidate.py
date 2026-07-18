from typing import Iterable, List, TypeVar

T = TypeVar("T")


def stable_unique(items: Iterable[T]) -> List[T]:
    unique: List[T] = []
    for item in items:
        for existing in unique:
            if item == existing:
                break
        else:
            unique.append(item)
    return unique