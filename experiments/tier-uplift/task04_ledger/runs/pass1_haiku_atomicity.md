# Atomicity & State-Corruption Review: ledger.py

## Summary
**CRITICAL ATOMICITY BUG in `transfer()` method.** State-corrupting mutation ordering and missing error handling expose incomplete updates on exception paths.

---

## Issue 1: CRITICAL — transfer() Mutates Before Validation (Lines 36–40)

**Location:** `transfer()` method, lines 32–40

**Problem:**
The method mutates `self._balances[from_id]` *before* checking whether the balance would go negative. When the check fails, the from_id account has already been decremented with no rollback.

```python
def transfer(self, from_id, to_id, amount):
    if amount <= 0:
        raise ValueError("amount must be positive")
    # move funds
    self._balances[from_id] -= amount           # ← MUTATE (line 36)
    if self._balances[from_id] < 0:             # ← CHECK (lines 37–38)
        raise ValueError("insufficient funds")
    self._balances[to_id] += amount
    self._history.append((from_id, to_id, amount))
```

**State Corruption on Error:**

When validation fails (balance would go negative), `from_id`'s balance has already been reduced by `amount`, but:
- `to_id`'s balance is **never incremented**
- `self._history` is **never updated**
- Total money (`net_position()`) is **permanently reduced** — violating the invariant

**Concrete Failing Call Sequence:**
```python
ledger.open_account("A", 100)
ledger.open_account("B", 0)

# Precondition: net_position() == 100
try:
    ledger.transfer("A", "B", 150)  # Insufficient funds (A only has 100)
except ValueError as e:
    # Exception raised: "insufficient funds"
    pass

# Postcondition: A is now -50, B is still 0
# net_position() is now -50
# Total money LOST: 150 coins vanished from the system
# Invariant violated: transfers should conserve total money
```

**Impact:** Money disappears from the ledger permanently; double-spending is possible if A's balance is never validated before further transfers.

---

## Issue 2: CRITICAL — transfer() Incomplete on KeyError (Lines 36–40)

**Location:** `transfer()` method, same as Issue 1

**Problem:**
Even if `from_id` balance is decremented successfully (line 36) and passes the check (lines 37–38), line 39 attempts to increment `to_id`'s balance:

```python
self._balances[to_id] += amount  # ← line 39
```

If `to_id` does not exist in `self._balances`, this raises `KeyError`. At that moment:
- `from_id`'s balance has been **decremented**
- `to_id` was **never incremented** (no key to increment)
- `self._history` was **never appended**

**State Corruption on KeyError:**

```python
ledger.open_account("A", 100)
ledger.open_account("B", 0)

# Transfer everything from A to nonexistent account C
try:
    ledger.transfer("A", "C", 100)  # C doesn't exist
except KeyError:
    # Exception raised: 'C' not in balances
    pass

# Postcondition: A is now 0 (decremented), but the transfer never happened
# ledger.balance("A")  # → 0 (correct by accident)
# ledger.balance("B")  # → 0 (untouched)
# self._history is empty (no record of transfer attempt)
# net_position() is 0 (money lost; only A's 100 remains)
```

If `C` was subsequently opened, the transfer would appear never to have occurred, but A's balance would not be restored.

---

## Issue 3: transfer() Violates net_position() Invariant

**Location:** `net_position()` method (line 62), called as invariant check on `transfer()`

**Problem:**
The `net_position()` docstring claims: *"Total money in the ledger — should be conserved by transfers."*

However, a failed `transfer()` (either from insufficient funds or missing to_id) **reduces** `net_position()` because `from_id` is decremented before validation.

**Concrete Invariant Violation:**
```python
ledger.open_account("A", 1000)
ledger.open_account("B", 0)

initial = ledger.net_position()  # 1000

try:
    ledger.transfer("A", "B", 1500)  # Insufficient funds
except ValueError:
    pass

final = ledger.net_position()  # Now 500, not 1000
# Invariant: net_position should be unchanged after a failed transfer
# Violated: initial (1000) != final (500)
```

---

## Summary Table

| Method | Lines | Mutation | Error Path Corruption |
|--------|-------|----------|----------------------|
| `open_account` | 12–15 | `self._balances[account_id]` | None (check before set) |
| `deposit` | 20–23 | `self._balances[account_id]` | None (validation first, KeyError if missing) |
| `withdraw` | 25–30 | `self._balances[account_id]` | None (all checks before mutation) |
| `transfer` | 32–40 | `self._balances`, `self._history` | **CRITICAL**: Mutate-before-check; incomplete on KeyError; loses money |
| `apply_interest` | 58–60 | `self._balances[account_id]` | None (but KeyError if missing account) |

---

## Recommended Fixes

1. **Reorder validations:** Check balance *before* mutating, using a temporary calculation:
   ```python
   new_balance = self._balances[from_id] - amount
   if new_balance < 0:
       raise ValueError("insufficient funds")
   ```

2. **Guard to_id access:** Ensure `to_id` exists or raise an explicit error before any mutation:
   ```python
   if to_id not in self._balances:
       raise ValueError("to_id account does not exist")
   ```

3. **Atomic grouping:** All three mutations should complete or none should occur. In Python, consider:
   - A single transaction function that performs all updates, rolling back on any exception, or
   - A separate "staging" phase that validates everything before any update

4. **Invariant check:** Add a post-condition assertion that `net_position()` is conserved (or decremented exactly by interest/fees, if those exist).
