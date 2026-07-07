# Answer key — task 04 (PRIVATE, never shown to solvers or the loop)

8 planted bugs in `ledger.py`, by subtlety. Several require **cross-function
reasoning** (tying the transfer path to the stated invariants) — the class where
opus should out-find sonnet solo.

| # | line | bug | subtlety | trigger / why |
|---|---|---|---|---|
| L1 | 36–39 | `transfer` is **non-atomic**: it debits `from_id` (line 36) then checks `< 0` (line 37) and raises — but the debit is **never rolled back**, so on insufficient funds the sender is left debited with no credit. Money destroyed. | subtle | `transfer(a,b, more_than_a_has)` → raises, but `a`'s balance is now wrong (reduced) | 
| L2 | 39 | `transfer` credits `to_id` with `+=` without checking `to_id` exists; a missing `to_id` raises `KeyError` **after** `from_id` was already debited → corruption + wrong error type | med (cross-fn) | `transfer(a, "nope", x)` debits `a`, then KeyError |
| L3 | 60 | `apply_interest` multiplies integer-cent balances by a float → balances become **floats with fractional cents** (money-as-float precision bug) | subtle | `apply_interest(a, 0.05)` on 101 → 106.05 |
| L4 | 69–74 | `richest` initializes `best_bal = 0`, so if every candidate balance is ≤ 0 it returns `None` despite a well-defined max, and it never selects a 0-balance account | subtle | `richest([x])` where balance(x) < 0 → None |
| L5 | 12–15 | `open_account` never validates `opening_balance >= 0` — an account can be created already negative, breaking every downstream invariant | med | `open_account("a", -500)` |
| L6 | 18 (also 22,27,36…) | unknown-account access raises a raw `KeyError` instead of a clean domain error (`balance`, `deposit`, `withdraw`, `transfer` all index `_balances` with no existence check) | med | `balance("ghost")` → KeyError |
| L7 | 33+ | `transfer` permits `from_id == to_id` (self-transfer): pollutes history with no-op entries and, combined with the debit-first ordering, behaves inconsistently | med | `transfer(a, a, x)` |
| L8 | 36–39 vs 62–64 | **cross-function invariant break**: `net_position` documents that transfers conserve total money, but the non-atomic transfer (L1) can change `net_position` on a *failed* transfer — the documented invariant is false | subtle (cross-fn) | net_position drops after a failed transfer |

Scoring: N of 8. Partial credit (0.5) for right location, vague mechanism.
`deposit`/`withdraw` positive-amount guards are CORRECT — flagging them is a
false positive (tracked, not scored).
