# dense_orders — planted-defect key (HIDDEN from all solvers)

10 defects across 8 classes. A finding "catches" a bug only if it names the
function AND the failure mechanism (not just vague unease near the line).

| id | class | location | defect (fingerprint) |
|----|-------|----------|----------------------|
| B1 | control_flow | `page_of` | `end = start + size - 1` with an exclusive slice → every page returns size−1 items; last item of each page silently dropped |
| B2 | state | `search_orders` | mutable module-level `DEFAULT_FILTERS` as default arg, then `filters["flagged"] = True` mutates it → permanent cross-call contamination |
| B3 | data_types | `totals_match` / `invoice_total` | float accumulation + `==` equality on money → false mismatches from representation error |
| B4 | concurrency | `reserve` | check-then-act on `_stock` WITHOUT `_stock_lock` (which `restock`/`release` do take) → two concurrent reserves oversell; cross-function lock-discipline disagreement |
| B5a | resource_lifetime | `load_catalog` | returns a lazy generator bound to `fh`; the `with` closes the file at return → iteration in `catalog_index` hits a CLOSED file (use-after-close escaping a with-block) |
| B5b | resource_lifetime | `export_report` | `open` without `with`; early `return written` on `total < 0` leaks the handle and loses buffered rows (no flush/close on that path) |
| B6a | contracts | `parse_qty` | returns 0 on `ValueError` — invalid qty silently becomes a "valid" zero line instead of raising |
| B6b | contracts | `intake_order` | `prices.get(sku, 0.0)` — unknown/typo SKU silently priced $0.00 (free items), no validation |
| B7 | adversarial | `apply_discounts` | SPEC says apply in listed order; code SORTS percent-first (with a plausible justifying comment) → computed totals violate the stated contract |
| B8 | data_types/contracts | `hold_expired` (+`intake_order`) | docstring says timestamps are UTC, code uses local `datetime.now()` → holds expire wrong by the TZ offset |

Scoring: judged against solver text with quotes; ambiguous credit goes AGAINST
the lens (the bar is lift the baseline MISSED, so ties favor the baseline).
