# Boundary & Off-By-One Review: metrics.py

## Findings

### 1. OFF-BY-ONE ERROR in `moving_window()` (Line 40)

**Location**: Lines 38-41

**Issue**: The range excludes the final window.

```python
for i in range(len(values) - k):
    yield values[i:i + k]
```

**Concrete Failing Example**:
- Input: `values = [1, 2, 3, 4, 5]`, `k = 2`
- Expected windows: 4 (indices 0-1, 1-2, 2-3, 3-4)
- Actual windows: 3

**Trace**:
- `len(values) - k = 5 - 2 = 3`
- `range(3)` = [0, 1, 2]
- i=0: yield [1, 2] ✓
- i=1: yield [2, 3] ✓
- i=2: yield [3, 4] ✓
- i=3: never reached — **[4, 5] is missing** ✗

**Fix**: Change `range(len(values) - k)` to `range(len(values) - k + 1)`

---

## Other Functions Reviewed

- `running_average()`: No boundary issues.
- `median()`: Boundary logic correct for both odd/even cases.
- `percent_change()`: No loops or ranges.
- `dedupe()`: No boundary errors (though logic bug exists: `seen` never updated).
- `retry()`: `range(attempts)` is correct.
- `normalize()`: No boundary issues.
- `top_k()`: Slice `[:k]` is correct; returns fewer if fewer available.
