"""Test runner for db.py. Tests functionality AND security."""
from db import get_user, search_users, count_users


def test_basic_search():
    results = search_users("alice")
    assert len(results) == 1
    assert results[0]["name"] == "alice"


def test_partial_search():
    results = search_users("o")  # matches bob and carol
    names = {r["name"] for r in results}
    assert names == {"bob", "carol"}, f"Expected bob+carol, got {names}"


def test_empty_search():
    results = search_users("zzz_nonexistent")
    assert results == []


def test_get_user():
    u = get_user(1)
    assert u is not None
    assert u["name"] == "alice"
    assert get_user(999) is None


def test_count():
    assert count_users() == 3


def test_sql_injection_blocked():
    """This is the critical test. An unpatched search_users would return ALL users
    because the injected SQL completes the LIKE and adds OR 1=1."""
    malicious_input = "' OR '1'='1"
    results = search_users(malicious_input)
    # If injection works, this returns all 3 users. If blocked, returns 0.
    assert len(results) == 0, (
        f"SQL INJECTION SUCCEEDED: query with [{malicious_input}] "
        f"returned {len(results)} rows (expected 0). "
        f"The search_users function is vulnerable."
    )


def test_sql_injection_drop_blocked():
    """Ensure a DROP TABLE attempt doesn't crash or destroy data."""
    evil = "'; DROP TABLE users; --"
    try:
        search_users(evil)
    except Exception:
        pass  # Exception is acceptable — crash is not, but data loss is the real test
    # Table must still exist and be intact
    assert count_users() == 3, "Data was destroyed by SQL injection!"


def main():
    tests = [
        test_basic_search,
        test_partial_search,
        test_empty_search,
        test_get_user,
        test_count,
        test_sql_injection_blocked,
        test_sql_injection_drop_blocked,
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
