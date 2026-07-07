"""
Held-out subject for proving a candidate lens (concurrency / atomicity).

The only defect is a check-then-act race: the classic memoize looks correct and
single-threaded it IS correct, so a general review tends to pass it. Under two
interleaved callers the 'create it once' contract breaks — both see the key
absent, both call factory() (double side effect / double cost), and one value is
silently discarded. The lens under test targets TOCTOU / non-atomic compound
updates, so it should surface what the plain pass waves through.

Not tuned to any lens's wording.
"""

_cache: dict = {}


def get_or_create(key, factory):
    """Return the cached value for key, creating it exactly once with factory()."""
    if key not in _cache:
        _cache[key] = factory()
    return _cache[key]


def increment(counter_name, store):
    """Add one to a named counter in the shared store."""
    current = store.get(counter_name, 0)
    store[counter_name] = current + 1
    return store[counter_name]
