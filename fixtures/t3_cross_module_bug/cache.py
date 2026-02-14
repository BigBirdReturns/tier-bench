"""Simple TTL cache. Entries expire after `ttl` seconds."""
import time


class Cache:
    def __init__(self, ttl: float = 5.0):
        self.ttl = ttl
        self._store: dict[str, tuple[float, object]] = {}  # key -> (expiry_timestamp, value)

    def get(self, key: str) -> object | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expiry, value = entry
        # BUG: comparison is backwards — returns expired entries, rejects valid ones
        if time.time() > expiry:
            return value  # Should return None (expired)
        del self._store[key]
        return None  # Should return value (still valid)

    def set(self, key: str, value: object) -> None:
        self._store[key] = (time.time() + self.ttl, value)

    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)
