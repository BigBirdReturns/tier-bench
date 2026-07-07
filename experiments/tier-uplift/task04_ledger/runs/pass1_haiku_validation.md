# Ledger.py — Validation & Degenerate Input Review

## MISSING VALIDATION & INVARIANT VIOLATIONS

### 1. `open_account()` — Line 12-15
**Negative opening_balance unvalidated**
- **Input that breaks:** `open_account("acc1", -100)`
- **Issue:** Line 15 directly assigns `self._balances[account_id] = opening_balance` without checking if opening_balance < 0
- **Effect:** Violates ledger invariant (balance should not be negative)

---

### 2. `statement()` — Line 50-56
**Negative page parameter unvalidated**
- **Input that breaks:** `statement("acc1", page=-1, per_page=10)`
- **Issue:** Line 54 computes `start = page * per_page = -10`; Line 56 executes `rows[-10:0]` (slice from end backwards to start)
- **Effect:** Degenerate behavior; returns empty list but should reject invalid pagination

**Zero per_page unvalidated**
- **Input that breaks:** `statement("acc1", page=0, per_page=0)`
- **Issue:** Line 55 computes `end = 0 + 0 = 0`; Line 56 executes `rows[0:0]`
- **Effect:** Always returns empty list; violates pagination contract

**Negative per_page unvalidated**
- **Input that breaks:** `statement("acc1", page=0, per_page=-5)`
- **Issue:** Line 55 computes `end = 0 + (-5) = -5`; Line 56 executes `rows[0:-5]`
- **Effect:** Degenerate; returns all rows except last 5 (silently wrong behavior)

---

### 3. `apply_interest()` — Line 58-60
**Negative rate unvalidated**
- **Input that breaks:** `apply_interest("acc1", -1.5)` (account has balance 100)
- **Issue:** Line 60 computes `balance *= (1 + (-1.5)) = 100 * (-0.5) = -50`
- **Effect:** Violates ledger invariant; balance becomes negative; contradicts "interest" semantics

**Absurd rate unvalidated**
- **Input that breaks:** `apply_interest("acc1", 1000)` (account has balance 100)
- **Issue:** Line 60 computes `balance *= 1001 = 100100` (unbounded multiplication)
- **Effect:** No upper bound check; rate can be arbitrarily large or mathematically invalid (e.g., -2.0 causes sign flip)

---

### 4. `richest()` — Line 66-74
**Empty accounts list**
- **Input that breaks:** `richest([])`
- **Issue:** Loop at line 70 never executes; Line 74 returns `best = None`
- **Effect:** Degenerate; method signature promises to return account_id with highest balance, returns None instead

**All-negative balances**
- **Input that breaks:** `richest(["acc1", "acc2"])` where acc1 = -50, acc2 = -100
- **Issue:** Line 71 test `self._balances[a] > best_bal` where best_bal=0; neither -50 nor -100 > 0, so neither satisfies condition
- **Effect:** Returns None instead of acc1 (which is the richest/least negative); logic assumes at least one positive balance

**All-zero balances**
- **Input that breaks:** `richest(["acc1", "acc2"])` where acc1 = 0, acc2 = 0
- **Issue:** Line 71 test `self._balances[a] > best_bal` where best_bal=0; neither 0 > 0
- **Effect:** Returns None despite having tied-highest balances; breaks expected behavior on tie

**Non-existent account in list**
- **Input that breaks:** `richest(["nonexistent"])`
- **Issue:** Line 71 accesses `self._balances["nonexistent"]`
- **Effect:** Raises uncaught KeyError

---

### Summary Table

| Method | Line | Issue | Degenerate Input | Effect |
|--------|------|-------|------------------|--------|
| `open_account` | 15 | No negative check | `open_account("a", -100)` | Negative balance (invariant violation) |
| `statement` | 54-56 | No page < 0 check | `statement("a", page=-1)` | Silent degenerate slice |
| `statement` | 55-56 | No per_page ≤ 0 check | `statement("a", per_page=0)` | Always empty result |
| `statement` | 55-56 | No per_page < 0 check | `statement("a", per_page=-5)` | Wrong pagination logic |
| `apply_interest` | 60 | No rate bounds | `apply_interest("a", -1.5)` | Negative balance (invariant violation) |
| `apply_interest` | 60 | No rate bounds | `apply_interest("a", 1000)` | Unbounded multiplier |
| `richest` | 74 | No empty list check | `richest([])` | Returns None instead of error/empty |
| `richest` | 71 | No all-negative/zero check | `richest(["a","b"])` all zero | Returns None; logic assumes positive balances |
| `richest` | 71 | No account existence check | `richest(["nonexistent"])` | Unhandled KeyError |
