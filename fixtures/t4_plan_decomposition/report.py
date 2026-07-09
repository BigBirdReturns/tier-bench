"""Build the stock/pricing summary consumed by output.py."""
import inventory
import pricing


def summary(items: list[dict], low_threshold: int) -> dict:
    return {
        "total": pricing.total(items),
        "low_stock": inventory.count_low_stock(items, low_threshold),
    }
