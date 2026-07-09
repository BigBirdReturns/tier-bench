"""Pricing helpers."""


def unit_price(item: dict) -> float:
    return float(item["price"])


def total(items: list[dict]) -> float:
    return sum(unit_price(i) * i["qty"] for i in items)
