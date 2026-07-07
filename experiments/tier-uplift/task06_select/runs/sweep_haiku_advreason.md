# Breaking select.py: Single-Swap Repair is Incomplete

## Vulnerability

The function's repair phase only attempts **single swaps** (remove one chosen item, add one unchosen item) to fix the weight modulo constraint. This is incomplete: it's possible that no single swap produces weight divisible by 3, yet a valid selection of exactly k items exists elsewhere in the item space.

## Root Cause

When weight modulo 3 is analyzed:
- If all k chosen items have weight ≡ r (mod 3), then total ≡ kr (mod 3)
- If all unchosen items have weight ≡ q (mod 3), then any single swap produces weight ≡ kr - r + q ≡ (k-1)r + q (mod 3)
- By choosing r and q carefully, we can make this value never equal 0 (mod 3)
- However, a completely different selection of k items may satisfy the constraint

## Counterexample Construction

Set k=2. Choose items such that:
- Top-2 by value have weights ≡ 2 (mod 3): weights 2 and 2 → sum = 4 ≡ 1 (mod 3)
- Remaining items have weights ≡ 0 (mod 3): weights 0 and 3

Single swap analysis:
- Remove weight 2, add weight 0: 1 - 2 + 0 ≡ 2 (mod 3) ✗
- Remove weight 2, add weight 3: 1 - 2 + 3 ≡ 2 (mod 3) ✗
- All four possible single swaps fail to produce 0 (mod 3)

However:
- Selecting items with weights [0, 3]: total = 3 ≡ 0 (mod 3) ✓
- This is a valid selection with value 15

The function returns None (no repair found), but a correct answer exists.

COUNTEREXAMPLE: items=[(10,2),(9,2),(8,0),(7,3)]; k=2
