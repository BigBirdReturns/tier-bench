"""Frozen formatting — downstream consumers parse this exact layout."""


def render(s: dict) -> str:
    return f"TOTAL={s['total']:.2f} LOW={s['low_stock']}"
