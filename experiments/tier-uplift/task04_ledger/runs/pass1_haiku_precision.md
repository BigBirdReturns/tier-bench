# Code Review: ledger.py — Numeric Type & Precision

**Lens:** NUMERIC TYPE & PRECISION — Balances must be integer cents throughout

---

## Findings

### 1. **Line 15: Unvalidated opening_balance parameter**
**Severity:** CRITICAL  
**Issue:** `open_account()` accepts `opening_balance` without type checking. Caller can pass float.  
**Concrete Trigger:**
```python
ledger.open_account("acc1", 100.50)  # Stores float 100.5 instead of 10050 cents
```
**Propagation:** Float stored directly in `_balances["acc1"]`. All subsequent arithmetic preserves float type.

---

### 2. **Line 23: Unvalidated amount in deposit()**
**Severity:** CRITICAL  
**Issue:** `amount` parameter has no type validation. Addition of float to int balance produces float.  
**Concrete Trigger:**
```python
ledger.open_account("acc1", 0)       # balance = 0 (int)
ledger.deposit("acc1", 10.5)         # 0 + 10.5 = 10.5 (float)
```
**Propagation:** Balance becomes `10.5` (float). Remains float for all future operations.

---

### 3. **Line 30: Unvalidated amount in withdraw()**
**Severity:** CRITICAL  
**Issue:** `amount` parameter has no type validation. Subtraction produces float if amount is float.  
**Concrete Trigger:**
```python
ledger.open_account("acc1", 10000)   # balance = 10000 (int)
ledger.withdraw("acc1", 5.5)         # 10000 - 5.5 = 9994.5 (float)
```
**Propagation:** Balance corrupts to float. Stays float indefinitely.

---

### 4. **Lines 36, 39: Unvalidated amount in transfer()**
**Severity:** CRITICAL  
**Issue:** `amount` parameter has no type validation. Both from and to balances become float.  
**Concrete Trigger:**
```python
ledger.open_account("a", 1000)       # both int
ledger.open_account("b", 500)
ledger.transfer("a", "b", 123.45)    # 1000 - 123.45 = 876.55 (float)
                                     # 500 + 123.45 = 623.45 (float)
```
**Propagation:** Both accounts corrupted to float. Transfer history stores float, affecting `total_deposits()` sums.

---

### 5. **Line 60: Interest multiplication produces float**
**Severity:** CRITICAL  
**Issue:** `apply_interest()` multiplies balance (int) by `(1 + rate)` (float), always producing float.  
**Concrete Trigger:**
```python
ledger.open_account("acc1", 10000)   # balance = 10000 (int)
ledger.apply_interest("acc1", 0.05)  # 10000 * 1.05 = 10500.0 (float, not 10500)
```
**Propagation:** Float persists permanently. No path to convert back to int. All future operations on this account use float arithmetic.

---

## Summary

**Total float infection points:** 5 (opening_balance, deposit, withdraw, transfer, apply_interest)

**Corruption mechanism:**
- Any of 5 entry points accepts float/non-integer amounts unvalidated
- Python's `int + float = float` rule taints the balance permanently
- No conversion back to int exists; once float, always float
- Float arithmetic can cause precision loss in comparisons (e.g., `9994.5 > 0` works, but `(1000 - 123.45) == 876.55` is fragile)
- `net_position()` sum inherits float type if any balance is float

**Critical missing:** Type validation and int conversion at all amount entry points (lines 15, 21–22, 26–27, 33–34, 59).
