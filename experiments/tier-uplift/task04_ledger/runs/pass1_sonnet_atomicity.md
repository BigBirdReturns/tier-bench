# Atomicity & State-Corruption Review — ledger.py

Lens: for each mutator of `self._balances` / `self._history`, does a mid-method
exception leave state half-updated with no rollback, and does mutate-before-check
ordering corrupt state on the error path?

## Mutators inventoried

- `open_account` (12-15)
- `deposit` (20-23)
- `withdraw` (25-30)
- `transfer` (32-40)
- `apply_interest` (58-60)

(`balance`, `total_deposits`, `statement`, `net_position`, `richest` are read-only.)

## Findings

### 1. `transfer` (lines 32-40): mutate-before-check destroys money on insufficient funds — CRITICAL

```
36    self._balances[from_id] -= amount
37    if self._balances[from_id] < 0:
38        raise ValueError("insufficient funds")
39    self._balances[to_id] += amount
40    self._history.append((from_id, to_id, amount))
```

`from_id` is debited on line 36 *before* the funds-sufficiency check on line 37.
When the check fails, the method raises but line 36's debit is never undone —
there is no rollback (`self._balances[from_id] += amount` to restore it). The
credit to `to_id` (line 39) and the history append (line 40) never happen
because the exception unwinds first. Net effect: money is permanently deleted
from the ledger and the debited account is left with a negative balance, a
state `withdraw` explicitly refuses to ever produce (it checks *before*
mutating, at line 28-29).

**Concrete failing sequence:**
```python
l = Ledger()
l.open_account("A", 100)
l.open_account("B", 0)
l.transfer("A", "B", 150)   # raises ValueError("insufficient funds")

l.balance("A")     # -50  (permanently negative — violates the invariant
                    #       withdraw() enforces: balance never goes below 0)
l.balance("B")     # 0    (never credited)
l.net_position()   # -50  (was 100 before the call — 150 "vanished")
l.total_deposits("B")  # 0 (history has no record of the attempt or the loss)
```

`net_position()`'s own docstring claims "should be conserved by transfers" —
this failed transfer proves that guarantee is false the moment `transfer`
raises after line 36 but before line 40.

### 2. `transfer` (lines 36-39): mutate-before-check also loses money when `to_id` doesn't exist — CRITICAL

Even when `from_id` has sufficient funds, line 39 (`self._balances[to_id] +=
amount`) raises `KeyError` if `to_id` was never opened via `open_account`. By
that point line 36 has already debited `from_id` and line 37's check passed
(balance stayed ≥ 0), so the exception at line 39 still leaves `from_id`
permanently short and nothing credited anywhere, with no history entry to
explain the discrepancy.

**Concrete failing sequence:**
```python
l = Ledger()
l.open_account("A", 100)
l.transfer("A", "ghost", 50)   # raises KeyError('ghost')

l.balance("A")      # 50 (debited, never restored)
l.net_position()    # 50 (was 100 — 50 destroyed, and 'ghost' was never
                     #     created so the money isn't "waiting" anywhere)
```

Note this failure mode raises `KeyError`, not `ValueError` like the
insufficient-funds path (line 38) or `deposit`/`withdraw`'s validation
(lines 22, 27) — an inconsistency in what exception types callers must guard
against, compounding the corruption risk since a caller catching only
`ValueError` around a transfer will not even notice the money loss.

### 3. `withdraw` vs `transfer`: two methods disagree on the "no negative balance" invariant

`withdraw` (lines 28-30) checks `self._balances[account_id] < amount` *before*
mutating, so a failed withdrawal never touches state — correct check-then-act
ordering. `transfer` (lines 36-38) implements the same "don't go negative"
rule with mutate-then-check ordering, so it fails *after* corrupting state.
The two "debit" paths in the same class enforce an identical invariant with
opposite atomicity guarantees. Sequence proving the disagreement:

```python
l = Ledger()
l.open_account("A", 100)
l.withdraw("A", 150)        # raises, l.balance("A") == 100  (unchanged — safe)
l.transfer("A", "A", 150)   # raises, l.balance("A") == -50  (corrupted — unsafe)
```

(The self-transfer `"A"->"A"` above also shows line 36 and line 39 operate on
the *same* dict entry when `from_id == to_id`; since line 39 is never reached
here it doesn't self-heal, but it's worth flagging that `transfer` has no
guard against `from_id == to_id` at all — a successful same-account transfer
would append a no-op history entry, which is a lesser but related history/
balance consistency wrinkle.)

### 4. `open_account`, `deposit`, `apply_interest`: single-statement mutations are safe (no partial-update risk found)

- `open_account` (12-15): check on line 13 happens strictly before the only
  mutation on line 15, and the mutation is a single atomic dict assignment —
  no partial-state path.
- `deposit` (20-23): `self._balances[account_id] += amount` on line 23 is
  `d[k] = d[k] + amount`; if `account_id` is missing, the read `d[k]` raises
  `KeyError` *before* any write occurs, so the dict is left untouched (fails
  clean, not corrupted). Same reasoning applies to `withdraw` line 28's read
  and line 30's write, and to `apply_interest` line 60.
- `apply_interest` (58-60): single augmented-assignment statement; same
  read-before-write safety as above. No exception can fire strictly between
  a read and a write here because it's one bytecode-level statement, so
  there's no window for half-updated state.

### 5. `_history` vs `_balances` consistency after failures

Because `transfer` appends to `_history` only on the last line (40), every
failure path in Findings #1-#2 leaves `_balances` mutated but `_history`
untouched. This means `total_deposits` (42-48) and `statement` (50-56), which
derive their answers purely from `_history`, can never explain or reconcile
the phantom balance changes produced by a failed `transfer` — there is no
audit trail for money that `net_position()` shows as missing. Any reconciliation
job trusting "`sum(_balances.values())` should equal `sum` of net flows in
`_history`" will silently diverge after the very first failed transfer.

## Summary

The sole atomicity defect is in `transfer` (lines 32-40): it mutates
`self._balances[from_id]` before validating the operation can succeed, and
has no compensating rollback on any of its two failure exits (insufficient
funds at line 37-38, missing `to_id` at line 39). Both failure paths
permanently destroy money and desynchronize `_balances` from `_history`,
directly contradicting `net_position()`'s documented conservation guarantee.
All other mutators (`open_account`, `deposit`, `withdraw`, `apply_interest`)
are single-statement, read-before-write operations that fail cleanly with no
partial mutation.
