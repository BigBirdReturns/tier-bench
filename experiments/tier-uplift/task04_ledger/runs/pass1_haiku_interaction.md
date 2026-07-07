# Ledger.py Security Review: Hostile & Aliased Inputs

## Case 1: Self-Transfer (from_id == to_id)

**Trigger:** `transfer(from_id='A', to_id='A', amount=amount)` where from_id and to_id are identical

**What breaks:**

- **Line 36** (debit): `self._balances[from_id] -= amount` executes first, removing funds
- **Line 37-38** (insufficient check): Evaluates AFTER balance is already negative
- **Critical bug:** If balance < amount, the account goes negative, THEN validation raises ValueError, but **state is corrupted**

**Example:** Account A has 50 cents. Call `transfer('A', 'A', 100)`:
- Line 36: A's balance → -50
- Line 37: Check -50 < 100? TRUE → Raise ValueError
- **Result:** Ledger state corrupted to -50; exception prevents history record but balance already mutated

---

## Case 2: Never-Opened Account (Missing Account ID)

**Trigger:** Any method called with account_id that was never passed to `open_account()`

**What breaks per method:**

| Method | Line | Issue |
|--------|------|-------|
| `balance(account_id)` | 18 | `KeyError` on `self._balances[account_id]` |
| `deposit(account_id, amount)` | 23 | `KeyError` on `self._balances[account_id] += amount` |
| `withdraw(account_id, amount)` | 28 | `KeyError` on `self._balances[account_id] < amount` check |
| `transfer(from_id, to_id, amount)` | 36 | `KeyError` on `self._balances[from_id] -= amount` if from_id missing |
| `transfer(from_id, to_id, amount)` | 39 | **CRITICAL:** `KeyError` on `self._balances[to_id] += amount` if to_id missing **AFTER debit at line 36** — state corrupted |
| `apply_interest(account_id, rate)` | 60 | `KeyError` on `self._balances[account_id] *= (1 + rate)` |
| `richest(accounts)` | 71 | `KeyError` on `self._balances[a] > best_bal` for any missing account in list |
| `total_deposits(account_id)` | — | No validation; silent no-op (iterates history, no state access) |
| `statement(account_id, page, per_page)` | — | No validation; silent no-op (iterates history, no state access) |

**Most critical:** Line 36→39 in `transfer()` — debits unknown `from_id`, then tries to credit unknown `to_id`, corrupting ledger if to_id doesn't exist.

---

## Case 3: Same Account Opened Twice

**Trigger:** `open_account(account_id='A')` called twice with same account_id

**What breaks:**
- **Line 13-14**: `if account_id in self._balances: raise ValueError("account exists")`
- **Result:** Properly caught. No state corruption. Second call rejected before any mutation.

---

## Summary: Critical Issues

1. **State mutation before validation (Line 36→37):** `transfer()` debits before checking sufficiency
2. **Partial transfer failure (Line 36→39):** If to_id doesn't exist, from_id is already debited; ledger imbalanced
3. **No input validation:** Never-opened accounts cause KeyError in 6/9 methods instead of graceful error
4. **Self-transfer allowed:** from_id == to_id doesn't validate; works if balance sufficient, corrupts if insufficient
