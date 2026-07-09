# Feature request

1. Add a `discount(price, percent)` function to `pricing.py`: returns the price
   reduced by `percent` percent, rounded to 2 decimal places. Raise `ValueError`
   if `percent` is outside 0..100.
2. Fix the bug in `inventory.py`: `count_low_stock` must count items whose
   quantity is **less than or equal to** the threshold (its docstring already
   says `<=`), but the code uses strict `<`.
3. Update `report.py` so the summary it builds includes a discounted total
   (10% off) computed via the new `pricing.discount`.

Constraints: do NOT touch `output.py` — its formatting is frozen for downstream
consumers.
