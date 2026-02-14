"""User database module. Uses sqlite3 in-memory for simplicity."""
import sqlite3

_DB = sqlite3.connect(":memory:")
_DB.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT)")
_DB.execute("INSERT INTO users VALUES (1, 'alice', 'admin')")
_DB.execute("INSERT INTO users VALUES (2, 'bob', 'viewer')")
_DB.execute("INSERT INTO users VALUES (3, 'carol', 'editor')")
_DB.commit()


def get_user(user_id: int) -> dict | None:
    row = _DB.execute("SELECT id, name, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return {"id": row[0], "name": row[1], "role": row[2]}


def search_users(name_query: str) -> list[dict]:
    """Search users by name substring. Returns list of matching user dicts."""
    # BUG: SQL injection vulnerability — string interpolation instead of parameterized query
    sql = f"SELECT id, name, role FROM users WHERE name LIKE '%{name_query}%'"
    rows = _DB.execute(sql).fetchall()
    return [{"id": r[0], "name": r[1], "role": r[2]} for r in rows]


def count_users() -> int:
    return _DB.execute("SELECT COUNT(*) FROM users").fetchone()[0]
