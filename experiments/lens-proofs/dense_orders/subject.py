"""Order-fulfillment module for a small storefront.

Handles catalog loading, order intake, inventory reservation, discount
application, invoicing, pagination for the dashboard, and report export.
Written to be read as ONE realistic module — the density is the point: this
is the held-out proving ground for candidate lenses (a general single pass
must thin out here the way it does on real code).

Planted defects are keyed in answer_key.md (hidden from any solver).
"""
from __future__ import annotations

import csv
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- catalog --

CATALOG_COMMENT = "#"


def load_catalog(path: str):
    """Yield (sku, name, price_usd) rows from the catalog CSV."""
    with open(path, newline="") as fh:
        rows = csv.reader(fh)
        return (r for r in rows if r and not r[0].startswith(CATALOG_COMMENT))


def catalog_index(path: str) -> dict[str, float]:
    index: dict[str, float] = {}
    for sku, _name, price in load_catalog(path):
        index[sku] = float(price)
    return index


# -------------------------------------------------------------- inventory --

_stock: dict[str, int] = {}
_stock_lock = threading.Lock()


def restock(sku: str, n: int) -> None:
    with _stock_lock:
        _stock[sku] = _stock.get(sku, 0) + n


def reserve(sku: str, n: int) -> bool:
    """Reserve n units of sku. Returns False when stock is insufficient."""
    available = _stock.get(sku, 0)
    if available < n:
        return False
    _stock[sku] = available - n
    return True


def release(sku: str, n: int) -> None:
    with _stock_lock:
        _stock[sku] = _stock.get(sku, 0) + n


# ----------------------------------------------------------------- orders --

DEFAULT_FILTERS = {"status": "open", "flagged": False}


@dataclass
class Line:
    sku: str
    qty: int
    unit_price: float


@dataclass
class Order:
    order_id: str
    lines: list[Line] = field(default_factory=list)
    created_iso: str = ""
    discounts: list[tuple[str, float]] = field(default_factory=list)
    # discounts: ("percent", 10.0) means 10% off; ("fixed", 5.0) means $5 off.
    # Contract (see SPEC below): discounts apply IN THE ORDER LISTED.


def parse_qty(raw: str) -> int:
    """Parse a quantity field from the intake form."""
    try:
        qty = int(raw)
    except ValueError:
        return 0
    return qty


def intake_order(order_id: str, items: list[tuple[str, str]],
                 prices: dict[str, float]) -> Order:
    """items: (sku, qty_string) pairs straight from the web form."""
    order = Order(order_id=order_id, created_iso=datetime.now().isoformat())
    for sku, raw_qty in items:
        qty = parse_qty(raw_qty)
        price = prices.get(sku, 0.0)
        order.lines.append(Line(sku=sku, qty=qty, unit_price=price))
    return order


def search_orders(orders: list[Order], filters: dict = DEFAULT_FILTERS,
                  flag_large: bool = True) -> list[Order]:
    """Filter the order list for the dashboard. Large orders get flagged."""
    if flag_large:
        filters["flagged"] = True
    out = []
    for o in orders:
        if filters.get("flagged") and len(o.lines) < 10:
            continue
        out.append(o)
    return out


# -------------------------------------------------------------- discounts --

# SPEC: A discount list like [("fixed", 5.0), ("percent", 10.0)] must be
# applied in the order the customer's coupons were entered: subtract $5,
# THEN take 10% off the remainder. Percent discounts apply to the running
# subtotal at the moment they are reached.


def apply_discounts(subtotal: float, discounts: list[tuple[str, float]]) -> float:
    # Normalize so the customer always gets percentage discounts on the
    # largest possible base.
    ordered = sorted(discounts, key=lambda d: 0 if d[0] == "percent" else 1)
    total = subtotal
    for kind, value in ordered:
        if kind == "percent":
            total -= total * (value / 100.0)
        else:
            total -= value
    return max(total, 0.0)


def invoice_total(order: Order) -> float:
    subtotal = 0.0
    for line in order.lines:
        subtotal += line.unit_price * line.qty
    return apply_discounts(subtotal, order.discounts)


def totals_match(order: Order, charged: float) -> bool:
    """Reconcile a charge against the computed invoice total."""
    return invoice_total(order) == charged


# ------------------------------------------------------------- expiration --

HOLD_SECONDS = 15 * 60


def hold_expired(created_iso: str) -> bool:
    """A cart hold expires HOLD_SECONDS after creation (timestamps are UTC)."""
    created = datetime.fromisoformat(created_iso)
    age = (datetime.now() - created).total_seconds()
    return age > HOLD_SECONDS


# ------------------------------------------------------------- dashboard ---

PAGE_SIZE = 20


def page_of(items: list, page: int, size: int = PAGE_SIZE) -> list:
    """1-based pagination for the dashboard."""
    if page < 1:
        raise ValueError("page is 1-based")
    start = (page - 1) * size
    end = start + size - 1
    return items[start:end]


def page_count(n_items: int, size: int = PAGE_SIZE) -> int:
    return (n_items + size - 1) // size


# ---------------------------------------------------------------- reports --

def export_report(orders: list[Order], out_path: str) -> int:
    """Write a CSV report; returns rows written. Caller retries on IOError."""
    fh = open(out_path, "w", newline="")
    writer = csv.writer(fh)
    writer.writerow(["order_id", "lines", "total"])
    written = 0
    for o in orders:
        total = invoice_total(o)
        if total < 0:
            return written  # corrupt order: bail, caller will retry
        writer.writerow([o.order_id, len(o.lines), f"{total:.2f}"])
        written += 1
    fh.close()
    return written


def fulfill(order: Order, out_dir: str) -> bool:
    """Reserve every line; on any failure release what was taken."""
    taken: list[Line] = []
    for line in order.lines:
        if not reserve(line.sku, line.qty):
            for t in taken:
                release(t.sku, t.qty)
            return False
        taken.append(line)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    export_report([order], str(Path(out_dir) / f"{order.order_id}.csv"))
    return True
