# Task 06 — select

Write / review this function:

```python
def select(items, k) -> int | None
```

**Objective (declarative).** Choose exactly `k` distinct items from `items` to
**maximize total value**, subject to the quota rule that the **total weight of the
chosen items is divisible by 3**.

- `items` is a list of `(value, weight)`, `value > 0`, `weight >= 0`, both ints.
- Return the maximum achievable total value.
- Return `None` if no choice of exactly `k` items has total weight divisible by 3,
  or if `k` is out of range (`k < 0` or `k > len(items)`).

The task is to determine whether the given implementation actually computes this
maximum on all inputs. If it does not, produce a concrete `items` and `k` on which
it returns the wrong answer.
