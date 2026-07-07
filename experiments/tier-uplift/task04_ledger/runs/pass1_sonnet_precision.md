# ledger.py — Numeric Type & Precision Review

Scope: every place a balance/amount can become a non-integer (float) and how that float
then propagates and corrupts later arithmetic or comparisons. Balances are supposed to be
integer cents throughout.

## 1. `apply_interest` — line 60 — the primary float generator
```python
self._balances[account_id] *= (1 + rate)
```
- `rate` is a float (e.g. `0.05`). `int * float` in Python always produces a `float`, so
  the instant `apply_interest` is called, that account's balance stops being an integer-cents
  value and becomes a `float` — even for "clean" results.
  Trigger: `balance("a") == 1000` (int); `apply_interest("a", 0.05)` → `1000 * 1.05 == 1050.0`
  (float, not `1050`).
- Worse, binary floating point makes the result **inexact**, not just the wrong type.
  Trigger: balance `333`; `apply_interest("a", 0.10)` → `333 * 1.1 == 366.29999999999995`.
  The account now holds a fractional-cent, non-representable amount. Calling
  `apply_interest` repeatedly (e.g. monthly compounding) compounds this error further with
  every call since there is no rounding/quantization back to integer cents anywhere in the
  method.

## 2. `open_account` — line 12/15 — unvalidated opening balance
```python
def open_account(self, account_id, opening_balance=0):
    ...
    self._balances[account_id] = opening_balance
```
No type/`isinstance` check on `opening_balance`. Trigger: `open_account("a", 99.99)` stores
`99.99` directly as the balance — a float, and not even a valid integer-cents amount — from
the moment the account is created, before any transaction has occurred.

## 3. `deposit` — lines 20-23 — unvalidated amount
```python
if amount <= 0:
    raise ValueError("amount must be positive")
self._balances[account_id] += amount
```
Only checks sign, not type/integrality. Trigger: `deposit("a", 10.5)` → `self._balances["a"] += 10.5`.
If the balance was an `int`, `int + float = float`; the account balance now permanently
becomes a `float` (and represents a fractional cent, which shouldn't be possible).

## 4. `withdraw` — lines 25-30 — unvalidated amount, same propagation
```python
if amount <= 0:
    raise ValueError("amount must be positive")
if self._balances[account_id] < amount:
    raise ValueError("insufficient funds")
self._balances[account_id] -= amount
```
Trigger: `withdraw("a", 5.5)` on an int balance turns it into a `float` via line 30
(`-= 5.5`), and the guard at line 28 becomes a float comparison, silently allowing a
fractional-cent withdrawal that should have been rejected as invalid input.

## 5. `transfer` — lines 32-40 — unvalidated amount, corrupts both endpoints
```python
self._balances[from_id] -= amount
if self._balances[from_id] < 0:
    raise ValueError("insufficient funds")
self._balances[to_id] += amount
self._history.append((from_id, to_id, amount))
```
No type check on `amount`. Trigger: `transfer("a", "b", 7.25)` makes both `_balances["a"]`
(line 36) and `_balances["b"]` (line 39) floats, and also records the float `7.25` into
`_history` (line 40), so the contamination reaches transaction history too, not just live
balances.

## 6. Cross-account propagation via interest → transfer
Once `apply_interest` (line 60) has made an account's balance a `float` (see #1), any
subsequent `transfer` that moves "the whole balance" out of that account passes that float
as `amount` into line 36/39. Line 39 (`self._balances[to_id] += amount`) then contaminates
a previously clean, integer-only counterparty account with a float — spreading the
corruption across the ledger through perfectly normal-looking transfer calls, with no type
validation anywhere in `transfer` to catch it.
Trigger: `apply_interest("a", 0.1)` → `balance("a") == 366.29999999999995`; then
`transfer("a", "b", ledger.balance("a"))` → `_balances["b"]` becomes float too.

## 7. `total_deposits` — lines 44-48 — sum silently upgrades to float
```python
total = 0
for f, t, amt in self._history:
    if t == account_id:
        total += amt
return total
```
`total` starts as `int`, but if any historical `amt` is a float (from #5/#6 above via line
40's unvalidated append), `total += amt` upgrades the running sum to `float` for the rest of
the loop. Reported deposit totals become imprecise (e.g. `1234.9999999999998` instead of
`1235`), which is a silent, hard-to-notice reporting corruption downstream of a single bad
transfer call.

## 8. `net_position` — line 64 — invariant check corrupted by float drift
```python
return sum(self._balances.values())
```
If any account balance is a float (from `apply_interest`, or propagated per #2-#6), the sum
is a `float`. Since `net_position` is documented as "should be conserved by transfers," a
caller comparing before/after snapshots will see spurious drift purely from floating-point
rounding error (e.g. `100000` vs `99999.99999999999`) even when no real leak occurred, or —
worse — could mask an actual conservation bug within the noise floor of float error.

## 9. Comparisons against corrupted balances — lines 28, 37, 71
- Line 28: `if self._balances[account_id] < amount:` — once the balance is an inexact float
  (e.g. `366.29999999999995` from #1), comparing against an integer withdrawal amount near
  the boundary (e.g. `366`) can pass or fail unpredictably vs. the "true" cents value,
  letting a withdrawal through that should be blocked or vice versa.
- Line 37: `if self._balances[from_id] < 0:` — same class of boundary error after float
  contamination; a balance that is mathematically supposed to be exactly `0` after a
  transfer may instead be a tiny negative float (e.g. `-1e-13`) or tiny positive float,
  flipping this check incorrectly.
- Line 71: `if self._balances[a] > best_bal:` in `richest()` — `best_bal` starts as the
  int `0`; once account balances are floats from interest, two accounts that should be
  exactly tied (e.g. identical opening balance + identical interest rate applied) can
  differ by a float-imprecision epsilon (e.g. `1050.0000000000002` vs `1050.0`), causing
  `richest()` to pick the "wrong" account for what is really a tie.

## Summary of propagation chain
`apply_interest` (line 60) is the single largest source of float corruption — it always
converts an int balance to a float, and frequently to an *inexact* float. From there,
`deposit`/`withdraw`/`transfer` (lines 23, 30, 36, 39) have no type validation on `amount`
and no re-quantization of balances, so floats are "sticky": once an account balance is a
float, every future `+=`/`-=` on it stays a float, and any transfer that moves a float
amount (whether directly caller-supplied per #2-#5, or indirectly the account's own
now-floaty balance per #6) spreads the contamination to other accounts, into `_history`
(line 40), and ultimately into aggregate/reporting functions `total_deposits` (line 47) and
`net_position` (line 64), plus comparison-based logic in `withdraw`, `transfer`, and
`richest` (lines 28, 37, 71). There is no `isinstance(amount, int)` guard and no rounding
back to integer cents anywhere in the class.
