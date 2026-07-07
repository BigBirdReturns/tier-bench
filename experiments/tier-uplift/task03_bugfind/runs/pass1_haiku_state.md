# State & Side-Effects Issues in metrics.py

## Issue 1: Mutable Default Argument in `running_average` (Line 7)

**Location:** Line 7, parameter `history=[]`

**Problem:** The function uses a mutable list as a default argument. This list is created once when the function is defined and persists across all calls, causing state to leak between invocations.

**Failing Sequence:**
```python
result1 = running_average(10)  # history=[10], returns 10.0
result2 = running_average(20)  # history=[10, 20], returns 15.0
result3 = running_average(5)   # history=[10, 20, 5], returns 11.666...
```
Each call appends to the same persistent list. Second call gives different result than if the function were called in isolation.

**Expected Behavior:** Each call should maintain its own history or operate independently. The second call with input 20 should return 20.0, not 15.0.

---

## Issue 2: In-Place Mutation of Argument in `median` (Line 15)

**Location:** Line 15: `values.sort()`

**Problem:** The function sorts the input list in place, mutating the caller's data. This is a side-effect that persists in the caller's scope.

**Failing Sequence:**
```python
data = [3, 1, 2]
median(data)  # data is now mutated to [1, 2, 3]
# Caller's original data structure is destroyed
```

**Expected Behavior:** The function should sort a copy of the input list, not the original. The caller's data should remain unmodified after calling `median()`.
