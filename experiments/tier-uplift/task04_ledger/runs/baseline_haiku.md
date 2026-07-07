# Ledger Correctness Bugs

1. **Line 36-40: transfer() — State corruption on insufficient funds**
   The from_id balance is decremented at line 36 before the funds check at line 37-38. If insufficient funds are detected, ValueError is raised after to_id has already been credited and from_id has a negative balance, leaving the ledger in an inconsistent state.

2. **Line 23: deposit() — Missing account existence check**
   Calling deposit() on a nonexistent account raises KeyError when attempting `self._balances[account_id] += amount`, rather than failing with a descriptive error or validating the account exists first.

3. **Line 28: withdraw() — Missing account existence check**
   Calling withdraw() on a nonexistent account raises KeyError when accessing `self._balances[account_id] < amount`, rather than validating the account exists.

4. **Line 36-39: transfer() — Missing account existence checks for both parties**
   Calling transfer() with a nonexistent from_id or to_id raises KeyError instead of providing proper validation, leaving the ledger in potentially corrupted state if only from_id is missing (amount already deducted at line 36).

5. **Line 60: apply_interest() — Floating-point arithmetic breaks integer invariant**
   Multiplying an integer balance by a float (1 + rate) converts the balance to a float, violating the invariant that account balances should remain integers representing cents and introducing precision errors in subsequent calculations.

6. **Line 71: richest() — Missing account existence check**
   Passing an account_id in the accounts list that doesn't exist in _balances raises KeyError instead of handling missing accounts.

7. **Line 74: richest() — Unexpected None return on empty input**
   When accounts list is empty, the loop never executes and best remains None, returning None silently instead of signaling an error condition.

8. **Line 42-48: total_deposits() — Opening balance excluded from audit trail**
   Opening balance set via open_account() is never recorded in _history, so total_deposits() cannot account for initial deposits and creates an incomplete transaction history for auditing.
