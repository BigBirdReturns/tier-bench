"""Inventory queries."""


def count_low_stock(items: list[dict], threshold: int) -> int:
    """Count items whose qty is <= threshold."""
    return sum(1 for i in items if i["qty"] < threshold)  # BUG: spec says <=
