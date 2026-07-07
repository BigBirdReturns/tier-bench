# ledger.py — Missing Validation & Degenerate Inputs

Scope: `ledger.py` only. Lens: unvalidated input that breaks a method or violates
an invariant.

## `open_account(account_id, opening_balance=0)` — lines 12–15

No validation of `opening_balance`.

- **Breaking input:** `open_account("A", -100)`
- **Effect:** account is created with a negative balance from the start. Nothing
  downstream (deposit/withdraw/transfer) ever rejects this, so a "impossible"
  negative balance becomes a legitimate ledger state, silently violating the
  implicit non-negative-balance invariant that `withdraw`/`transfer` otherwise
  try to enforce (lines 28–29, 36–38).
- Also no type check — a non-numeric `opening_balance` (e.g. a string) is
  accepted and only fails later, non-obviously, wherever arithmetic is first
  attempted (e.g. `deposit`, line 23).

## `balance(account_id)` — line 17–18

No existence check.

- **Breaking input:** `balance("nonexistent")`
- **Effect:** raw `KeyError` instead of a meaningful ledger-level error.

## `deposit(account_id, amount)` — lines 20–23

`amount <= 0` is checked (line 21), but `account_id` existence is not.

- **Breaking input:** `deposit("nonexistent", 100)`
- **Effect:** `KeyError` at line 23 (`self._balances[account_id] += amount`).
- Also no upper bound / type check on `amount`; `deposit("A", 1e18)` or
  `deposit("A", float("inf"))` is accepted and corrupts the "cents" invariant
  implied by the comment on line 9 (balances become float/`inf`).

## `withdraw(account_id, amount)` — lines 25–30

Same gap as `deposit`.

- **Breaking input:** `withdraw("nonexistent", 100)`
- **Effect:** `KeyError` at line 28 (`self._balances[account_id] < amount`),
  before the insufficient-funds check ever runs.

## `transfer(from_id, to_id, amount)` — lines 32–40

`amount <= 0` is checked, but `from_id`/`to_id` existence is not, and the
funds are moved *before* the sufficiency check, which creates a data-loss bug
on top of the missing validation.

- **Breaking input A:** `transfer("A", "nonexistent_to", 50)` where `A` has
  balance 50.
  - **Effect:** line 36 decrements `A` to 0, line 37 sufficiency check passes
    (0 is not < 0... actually with a smaller amount than balance it's fine),
    then line 39 (`self._balances[to_id] += amount`) raises `KeyError` because
    `to_id` doesn't exist. `A`'s balance has **already been debited** and the
    history entry is never appended — the money is silently destroyed. This
    is a real invariant break (`net_position`, line 62–64, is no longer
    conserved) caused purely by not validating `to_id` up front.
- **Breaking input B:** `transfer("nonexistent_from", "B", 50)`
  - **Effect:** `KeyError` at line 36 immediately (no funds moved yet), so
    less damaging than A, but still an unhandled `KeyError` instead of a
    validation error.
- **Breaking input C:** `transfer("A", "A", 50)` (self-transfer, no existence
  check on `from_id != to_id`)
  - **Effect:** balance ends up unchanged (subtract then add back) but a
    history row `("A", "A", 50)` is still appended, inflating
    `total_deposits("A")` (line 42–48) and polluting `statement("A", ...)`
    with a phantom transaction that has no real economic meaning.

## `total_deposits(account_id)` — lines 42–48

No validation of `account_id`.

- **Breaking input:** `total_deposits("nonexistent")`
- **Effect:** doesn't crash — silently returns `0`, which is indistinguishable
  from "account exists and legitimately has zero deposits." Typos in
  `account_id` fail silently rather than surfacing an error.

## `statement(account_id, page=0, per_page=10)` — lines 50–56

No validation of `page` or `per_page`; both are used directly as slice
arithmetic (lines 54–56), which never raises but silently returns wrong data.

- **Breaking input: `per_page=0`** — `statement("A", page=0, per_page=0)`
  - **Effect:** `start = 0`, `end = 0` for *every* `page` value, so
    `rows[0:0]` is always `[]`. Every page silently returns empty instead of
    raising or paginating — a caller with `per_page=0` gets no error and no
    data, and can't tell if the account has any history at all.
- **Breaking input: negative `page`** — `statement("A", page=-1, per_page=10)`
  - **Effect:** `start = -1 * 10 = -10`, `end = -10 + 10 = 0`, so
    `rows[-10:0]`. Because Python slicing treats negative indices as
    "from the end," this silently returns some real slice of `rows` (the
    10 entries before the last one) instead of failing — i.e. `page=-1`
    quietly returns *a* page of transactions rather than being rejected as
    an invalid page number. This is functionally wrong, not just
    unvalidated: the caller thinks they asked for an invalid page and got
    real, misleading data back.
- **Breaking input: negative `per_page`** — `statement("A", page=1, per_page=-5)`
  - **Effect:** `start = 1 * -5 = -5`, `end = -5 + -5 = -10`, so
    `rows[-5:-10]`. Since `start` index (from the end) is numerically after
    `end` index, this yields `[]` for typical list lengths — again silently
    wrong/empty rather than an explicit rejection of a nonsensical
    `per_page`.

## `apply_interest(account_id, rate)` — lines 58–60

No validation of `rate`, and no existence check on `account_id`.

- **Breaking input A (existence):** `apply_interest("nonexistent", 0.05)`
  - **Effect:** `KeyError` at line 60.
- **Breaking input B (rate < -1 flips sign):** balance `A = 100`,
  `apply_interest("A", -2)`
  - **Effect:** `100 * (1 + (-2)) == 100 * -1 == -100`. A single call with an
    out-of-range rate turns a positive balance negative, violating the same
    non-negative-balance invariant `withdraw`/`transfer` try to protect.
    Nothing stops `rate` from being `<= -1` (total wipeout at exactly `-1`,
    sign flip below `-1`).
- **Breaking input C (float corrupts integer cents):** balance `A = 3` (cents),
  `apply_interest("A", 0.1)`
  - **Effect:** `3 * 1.1 == 3.3000000000000003`. The comment on line 9 states
    balances are stored in cents (implying integers); `apply_interest` is the
    only method that silently converts a balance to a `float`, introducing
    fractional cents and floating-point rounding error with no rounding/
    validation step. Every subsequent `deposit`/`withdraw`/`transfer` now
    operates on a corrupted, non-integer "cents" value.
- **Breaking input D (absurd magnitude):** `apply_interest("A", 1e18)` — no
  upper bound, balance explodes to an astronomical, meaningless value with no
  error.

## `net_position()` — lines 62–64

Not directly parametrized, so nothing to validate here, but it is the
observable victim of the unvalidated inputs above: after
`transfer("A", "nonexistent_to", 50)` (destroyed funds) or
`apply_interest("A", -2)` (manufactured negative balance), `net_position()`
silently returns an incorrect total with no indication anything is wrong —
demonstrating that the missing validation upstream breaks a documented
system-wide invariant ("should be conserved by transfers", line 63).

## `richest(accounts)` — lines 66–74

No validation of `accounts` (empty list, unknown ids) and, more seriously, the
`best_bal = 0` initialization (line 69) silently assumes all balances are
non-negative, which is never enforced anywhere else in the file (see
`open_account` and `apply_interest` above).

- **Breaking input A (empty list):** `richest([])`
  - **Effect:** loop body never runs, returns `None`. No error, and callers
    that don't expect `None` will typically pass it straight into `balance()`
    or another lookup, producing a downstream `KeyError`.
- **Breaking input B (unknown account id):** `richest(["nonexistent"])`
  - **Effect:** `KeyError` at line 71 (`self._balances[a] > best_bal`).
- **Breaking input C (all-negative balances) — the real logic bug:**
  `open_account("A", -50)`, `open_account("B", -20)`,
  `richest(["A", "B"])`
  - **Effect:** `best_bal` starts at `0` and the comparison is strict `>`.
    Since `-50 > 0` and `-20 > 0` are both `False`, `best` never gets
    assigned and the function returns `None` — even though `B` (`-20`) is
    unambiguously the account with the highest balance among the two. This
    is a genuine, silent wrong-answer bug, not just an unhandled exception,
    and it only manifests because nothing validates/prevents negative
    balances upstream.
- **Breaking input D (all-zero balances):** `open_account("A", 0)`,
  `open_account("B", 0)`, `richest(["A", "B"])`
  - **Effect:** `0 > 0` is `False` for every account, so `best` stays `None`
    and the function again returns `None` instead of either tied account —
    a caller cannot distinguish "no accounts had a positive balance" from
    "the accounts list was empty" (case A), even though both are
    meaningfully different situations.
