"""
ledger.py — an in-memory account ledger with transfers and history.
Part of a payments service. Review for correctness.
"""


class Ledger:
    def __init__(self):
        self._balances = {}          # account_id -> balance (cents)
        self._history = []           # list of (from_id, to_id, amount) tuples

    def open_account(self, account_id, opening_balance=0):
        if account_id in self._balances:
            raise ValueError("account exists")
        self._balances[account_id] = opening_balance

    def balance(self, account_id):
        return self._balances[account_id]

    def deposit(self, account_id, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        self._balances[account_id] += amount

    def withdraw(self, account_id, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        if self._balances[account_id] < amount:
            raise ValueError("insufficient funds")
        self._balances[account_id] -= amount

    def transfer(self, from_id, to_id, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        # move funds
        self._balances[from_id] -= amount
        if self._balances[from_id] < 0:
            raise ValueError("insufficient funds")
        self._balances[to_id] += amount
        self._history.append((from_id, to_id, amount))

    def total_deposits(self, account_id):
        """Sum of all amounts ever transferred INTO account_id."""
        total = 0
        for f, t, amt in self._history:
            if t == account_id:
                total += amt
        return total

    def statement(self, account_id, page=0, per_page=10):
        """Return one page of this account's transactions, newest first."""
        rows = [h for h in self._history if account_id in (h[0], h[1])]
        rows = rows[::-1]
        start = page * per_page
        end = start + per_page
        return rows[start:end]

    def apply_interest(self, account_id, rate):
        """Grow the balance by rate (e.g. 0.05 for 5%)."""
        self._balances[account_id] *= (1 + rate)

    def net_position(self):
        """Total money in the ledger — should be conserved by transfers."""
        return sum(self._balances.values())

    def richest(self, accounts):
        """Return the account_id with the highest balance among `accounts`."""
        best = None
        best_bal = 0
        for a in accounts:
            if self._balances[a] > best_bal:
                best_bal = self._balances[a]
                best = a
        return best
