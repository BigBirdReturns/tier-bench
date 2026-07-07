# Edge Case Analysis: metrics.py

## 1. running_average (lines 7-10)
**Mutable default argument bug (semantic, not crash):**
- Empty input: N/A (history[] is default)
- Single element: Works, returns sample
- All-elements-equal: Works
- Zero/Negative: Works
- **Issue**: Mutable default `history=[]` persists across function calls, causing unbounded growth and incorrect means

## 2. median (lines 13-20)
**Critical: IndexError on empty input**
- **CRASH - Empty input**: `len(values)=0`, `n%2==1` is False (0 is even), executes line 20: `return (values[mid] + values[mid-1])/2` → `(values[0] + values[-1])/2` → **IndexError: list index out of range**

**Normal cases:**
- Single element: Works (n=1, returns values[0])
- All-elements-equal: Works
- Zero/Negative: Works

## 3. percent_change (lines 23-25)
**Critical: ZeroDivisionError when old=0**
- **CRASH - old=0**: Line 25: `return (new - old) / old * 100.0` → division by zero → **ZeroDivisionError**
- Single element: N/A (takes two scalars)
- All-elements-equal: Works (new=old returns 0.0)
- Negative: Works mathematically

## 4. dedupe (lines 28-35)
- Empty input: Works, returns []
- Single element: Works
- All-elements-equal: Works, returns single-element list
- Zero/Negative: Works
- **No edge case crashes**

## 5. moving_window (lines 38-41)
**Off-by-one: Missing final window when k=1**
- **CRASH - Single element, k=1**: `range(len(values) - k) = range(1-1) = range(0)` → yields nothing, but should yield `[values[0]]`
- **CRASH - k=0**: `range(len(values) - 0) = range(len(values))`, yields empty slices `values[i:i]` for each i
- k > len(values): Works correctly (yields nothing)
- **Negative k**: `range(len(values) - k)` becomes very large; if values=[1,2,3] and k=-1, yields windows of size 4 with out-of-bounds access → **IndexError**

## 6. retry (lines 44-50)
**Silent failure: Returns None on all failures**
- attempts=0: Returns None (range(0) is empty, loop never runs)
- Negative attempts: Returns None (range(negative) is empty)
- Normal case: Works
- **Issue**: All attempts fail → silently returns None instead of raising or signaling failure

## 7. normalize (lines 53-57)
**Critical: ZeroDivisionError on single element or all-equal**
- **CRASH - Empty input**: Line 55: `lo = min([])` → **ValueError: min() arg is an empty sequence**
- **CRASH - Single element**: `lo=hi=value`, line 57: `(v - lo) / (hi - lo)` → `(v - v) / 0` → **ZeroDivisionError**
- **CRASH - All-elements-equal**: Same as single element, `hi - lo = 0` → **ZeroDivisionError**, all results are `[nan]`

## 8. top_k (lines 60-62)
- Empty input: Works, returns []
- Single element: Works
- k=0: Works, returns []
- k > len(values): Works, returns all elements sorted descending
- Negative k: Works (negative slice indices in Python work as intended)
- **No edge case crashes**

## Summary of Critical Bugs

| Function | Line | Input | Expected | Actual |
|----------|------|-------|----------|--------|
| median | 20 | empty list | Error/None | IndexError |
| percent_change | 25 | old=0 | Error/Inf | ZeroDivisionError |
| moving_window | 40 | [1], k=1 | [[1]] | [] (empty) |
| moving_window | 40 | values=[1,2,3], k=-1 | Error | IndexError on out-of-bounds |
| normalize | 55 | [] | Error/None | ValueError |
| normalize | 57 | [5] | [0.0] | ZeroDivisionError |
| normalize | 57 | [5,5,5] | [0,0,0] | ZeroDivisionError |
