# Focused review: hostile & aliased inputs — `ledger.py`

Scope: only `from_id == to_id`, unopened-account references, and double-open. Traced line by line.

## 1. Self-transfer (`from_id == to_id`)

`transfer()`, lines 32-40:
```
36  self._balances[from_id] -= amount
37  if self._balances[from_id] < 0:
38      raise ValueError("insufficient funds")
39  self._balances[to_id] += amount
40  self._history.append((from_id, to_id, amount))
```

Because `from_id` and `to_id` are the same key, lines 36 and 39 both mutate `self._balances[A]`.

- **Amount ≤ balance (e.g. balance=100, `transfer(A, A, 50)`):** line 36 sets `balances[A] = 50`; line 37 check passes; line 39 sets it back to `balances[A] = 100`. Net balance is unchanged (correct), but line 40 still appends `(A, A, 50)` to history. `total_deposits(A)` (line 42-48) sums `amt` for every history row where `t == account_id`, so it counts this self-transfer as 50 in "total deposits" even though no external money moved and the balance didn't change — **inflates `total_deposits` with phantom volume for any self-transfer**, trigger: any `transfer(A, A, n)` with `n <= balance(A)`.

- **Amount > balance (e.g. balance=100, `transfer(A, A, 150)`):** line 36 sets `balances[A] = -50`; line 37 sees `-50 < 0` and raises `ValueError("insufficient funds")` **before line 39 runs**. Execution stops, so the compensating credit on line 39 never happens. Result: `balances[A]` is left permanently at **-50** — a self-transfer that should be a semantic no-op instead corrupts the account into a negative balance that no other code path repairs. Trigger: `transfer(A, A, amount)` with `amount > balance(A)`. (Note: the same partial-mutation-then-raise pattern also corrupts ordinary two-party transfers when `amount > balance(from_id)`, since `from_id` is debited on line 36 before the failure is detected on line 37 — self-transfer just makes it visible on a single account instead of two.)

## 2. Never-opened account passed to any method

Every method indexes `self._balances[account_id]` directly with no existence check (the only guard is in `open_account`, line 13). An id that was never passed to `open_account` triggers an **unhandled `KeyError`** (not the module's own `ValueError`, so callers catching `ValueError` for business errors will not catch this):

- `balance(x)` — line 18, `return self._balances[account_id]` → `KeyError` immediately. Trigger: `balance("ghost")`.
- `deposit(x, amt)` — line 23, `self._balances[account_id] += amount` reads the key before writing → `KeyError`. Trigger: `deposit("ghost", 10)`.
- `withdraw(x, amt)` — line 28, `self._balances[account_id] < amount` reads the key → `KeyError`. Trigger: `withdraw("ghost", 10)`.
- `apply_interest(x, rate)` — line 60, `self._balances[account_id] *= (1 + rate)` → `KeyError`. Trigger: `apply_interest("ghost", 0.05)`.
- `richest(accounts)` — line 71, `self._balances[a]` inside the loop → `KeyError` as soon as any unopened id appears in the list, even if other ids in the list are valid. Trigger: `richest(["real_acct", "ghost"])`.
- `transfer(from_id, to_id, amt)`, two sub-cases:
  - `from_id` unopened: line 36 raises `KeyError` immediately, nothing is mutated yet, `to_id` is untouched, history not appended — fails atomically (relatively "safe" but still an unhandled `KeyError` instead of a clean domain error).
  - `from_id` opened, `to_id` unopened (the dangerous case): line 36 debits `from_id` and line 37's check passes (assuming sufficient funds); line 39, `self._balances[to_id] += amount`, raises `KeyError` because `to_id` was never opened. By this point `from_id` has **already been permanently debited** (line 36 already executed) but no account is ever credited, and line 40 (history append) never runs because the exception fires first. **Money is silently destroyed from the ledger** — `net_position()` (line 62-64), which is documented as "should be conserved by transfers," will report a lower total after this failure, with no history record explaining why. Trigger: `transfer(real_from, "ghost_to", amount)` where `real_from` has `amount` available.
- `total_deposits(x)` and `statement(x)` do **not** crash on an unopened id — they only scan `self._history` (lines 42-48, 50-56), and an id that never appears in any transfer simply yields `0` / `[]`. This is silently permissive rather than an error, which is inconsistent with every other method raising on the same bad input (an unopened account is indistinguishable from an opened-but-untouched one for these two methods).

## 3. Same account opened twice

`open_account()`, lines 12-15:
```
12  def open_account(self, account_id, opening_balance=0):
13      if account_id in self._balances:
14          raise ValueError("account exists")
15      self._balances[account_id] = opening_balance
```
This case is actually **guarded correctly**: a second `open_account("A", ...)` call raises `ValueError("account exists")` on line 13-14 and line 15 never executes, so the existing balance for `A` is left untouched — no overwrite, no state corruption, no way to use a duplicate "open" to reset/launder a balance. This is the one hostile-input case in the file that is handled safely; it stands in contrast to the unopened-account and self-transfer cases above.

## Summary of concrete breakages
| Trigger | Location | Effect |
|---|---|---|
| `transfer(A, A, n)`, `n <= balance(A)` | ledger.py:36-40 | Balance unchanged but history/`total_deposits` inflated with phantom self-deposit |
| `transfer(A, A, n)`, `n > balance(A)` | ledger.py:36-38 | Raises "insufficient funds" but leaves `balances[A]` permanently negative (line 36 mutation not rolled back) |
| `balance`/`deposit`/`withdraw`/`apply_interest` on unopened id | ledger.py:18 / 23 / 28 / 60 | Unhandled `KeyError` instead of a domain error |
| `richest([..., unopened_id])` | ledger.py:71 | Unhandled `KeyError`, aborts before returning any result even if other ids are valid |
| `transfer(opened_from, unopened_to, amt)` | ledger.py:36 then 39 | `from_id` debited, `KeyError` on credit to `to_id`, no history entry, money vanishes from `net_position()` |
| `total_deposits`/`statement` on unopened id | ledger.py:42-56 | Silently returns `0`/`[]` instead of erroring, inconsistent with rest of API |
| `open_account(A)` twice | ledger.py:13-15 | Correctly raises `ValueError`, balance untouched (not a bug) |
