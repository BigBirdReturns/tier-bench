"""API layer using cache. Tests cover the cross-module TTL behavior."""
import time
from cache import Cache


def make_api():
    """Create an API instance with a short TTL cache for testing."""
    cache = Cache(ttl=0.3)  # 300ms TTL for fast testing

    def fetch(key: str, compute_fn) -> object:
        """Cache-through fetch. Returns cached value if valid, otherwise computes."""
        cached = cache.get(key)
        if cached is not None:
            return cached
        value = compute_fn()
        cache.set(key, value)
        return value

    def invalidate(key: str) -> bool:
        return cache.delete(key)

    return fetch, invalidate, cache


def test_basic_cache():
    """Set a value and immediately get it back."""
    fetch, _, cache = make_api()
    call_count = 0
    def compute():
        nonlocal call_count
        call_count += 1
        return "result"

    v1 = fetch("k", compute)
    v2 = fetch("k", compute)
    assert v1 == "result"
    assert v2 == "result"
    assert call_count == 1, f"Cache miss: compute called {call_count} times (expected 1)"


def test_ttl_expiry():
    """After TTL, cache should miss and recompute."""
    fetch, _, cache = make_api()
    counter = 0
    def compute():
        nonlocal counter
        counter += 1
        return f"v{counter}"

    v1 = fetch("k", compute)
    assert v1 == "v1"

    time.sleep(0.5)  # Wait past 300ms TTL

    v2 = fetch("k", compute)
    assert v2 == "v2", f"Expected recompute after TTL, got '{v2}'"
    assert counter == 2, f"Expected 2 computes after TTL, got {counter}"


def test_invalidate():
    """Manual invalidation should force recompute."""
    fetch, invalidate, cache = make_api()
    counter = 0
    def compute():
        nonlocal counter
        counter += 1
        return counter

    assert fetch("k", compute) == 1
    invalidate("k")
    assert fetch("k", compute) == 2


def test_independent_keys():
    """Different keys should not interfere."""
    fetch, _, cache = make_api()
    fetch("a", lambda: "alpha")
    fetch("b", lambda: "beta")
    assert fetch("a", lambda: "WRONG") == "alpha"
    assert fetch("b", lambda: "WRONG") == "beta"


def main():
    tests = [
        test_basic_cache,
        test_ttl_expiry,
        test_invalidate,
        test_independent_keys,
    ]
    for t in tests:
        try:
            t()
        except AssertionError as e:
            raise SystemExit(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            raise SystemExit(f"ERROR {t.__name__}: {e}")
    print("OK")


if __name__ == "__main__":
    main()
