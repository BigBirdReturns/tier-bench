# Ledger.py correctness review — findings

1. **Line 36–38, `transfer`** — The debit `self._balances[from_id] -= amount` happens *before* the insufficient-funds check, so when funds are insufficient the exception is raised only after `from_id` has already been decremented; the balance is left negative (and the credit never happens), corrupting state and destroying money. Triggers whenever a transfer amount exceeds `from_id`'s balance.

2. **Line 39, `transfer`** — There is no existence check on `to_id`, so if `to_id` is not an open account, `self._balances[to_id] += amount` raises `KeyError` *after* `from_id` was already debited (line 36), leaving the sender short and the money vanished. Triggers on any transfer to an unknown/typo'd destination account.

3. **Line 36, `transfer`** — No existence check on `from_id` either; `KeyError` is raised on an unknown source, and no atomic rollback exists for the multi-step mutation. Triggers when `from_id` is not an open account.

4. **Line 32–40, `transfer`** — A self-transfer (`from_id == to_id`) is permitted and appends a bogus history row; worse, if `amount` exceeds the balance it still raises "insufficient funds" (and per bug #1 leaves the account negative) even though the net effect should be zero. Triggers when caller passes the same id for both ends.

5. **Line 60, `apply_interest`** — `self._balances[account_id] *= (1 + rate)` multiplies an integer-cents balance by a float, converting the balance to a `float` with fractional cents and no rounding, permanently breaking the integer-cents invariant for that account and all later `net_position`/sum arithmetic. Triggers on any interest application (e.g. rate 0.05 on 101 cents → 106.05).

6. **Line 58–60, `apply_interest`** — `rate` is unvalidated, so a negative rate silently shrinks the balance (and a rate < -1 makes it negative), with no check that the account exists (raises `KeyError` otherwise). Triggers on negative/out-of-range rate or unknown account.

7. **Line 69, `richest`** — `best_bal` is initialized to `0`, so any account whose balance is `0` or negative can never win; if every account in `accounts` has a balance ≤ 0 the method returns `None` instead of the actual highest account. Triggers when all candidate balances are non-positive.

8. **Line 71, `richest`** — No existence check on `a`; `self._balances[a]` raises `KeyError` if any id in `accounts` is not open. Triggers when the caller passes an unknown account id.

9. **Line 12–15, `open_account`** — `opening_balance` is not validated to be non-negative (or an integer), so an account can be opened already overdrawn or with a float balance. Triggers when caller supplies a negative or non-integer opening balance.

10. **Line 17–18, `balance`** — Direct `self._balances[account_id]` lookup raises a raw `KeyError` for an unknown account instead of a domain error. Triggers on any query for an account that was never opened.

11. **Line 20–23, `deposit`** — No membership check before `self._balances[account_id] += amount`, so depositing to a non-existent account raises `KeyError`; also `amount` is not required to be an integer, so a float deposit corrupts the cents invariant. Triggers on unknown account or float amount.

12. **Line 25–30, `withdraw`** — Same missing-account `KeyError` (line 28 lookup) and same lack of integer-type enforcement on `amount` as deposit. Triggers on unknown account or float amount.

13. **Line 42–48, `total_deposits`** — Despite its name it counts *only* transfers recorded in `_history` and ignores every `deposit()` call (deposits are never appended to history), silently under-reporting the true total deposited into an account. Triggers whenever funds entered via `deposit` rather than `transfer`.

14. **Line 50–56, `statement`** — A negative `page` produces a negative `start`, turning `rows[start:end]` into an unintended tail slice (e.g. `page=-1` → `rows[-10:0]` returns empty/garbage) rather than an error; `per_page=0` silently returns an empty page for every page number. Triggers on negative page index or zero `per_page`.

15. **General (lines 20–40, 60)** — No method enforces that amounts/balances stay `int` cents; once any float enters (via interest, float amount, or float opening balance) it propagates through `deposit`/`withdraw`/`transfer` comparisons and `net_position`, producing accumulating floating-point precision errors in monetary totals. Triggers after any float contamination.
