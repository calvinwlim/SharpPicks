"""A tiny in-process TTL cache with per-key locks.

Avoids stampedes: if two requests ask for the same (expired) key at once,
only one of them runs the fetch function while the other waits for it.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Tuple


class TTLCache:
    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def get_or_set(self, key: str, ttl: float, fn: Callable[[], Awaitable[Any]]) -> Any:
        now = time.monotonic()
        hit = self._store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]

        async with self._lock(key):
            now = time.monotonic()
            hit = self._store.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]
            value = await fn()
            self._store[key] = (now + ttl, value)
            return value

    def clear(self) -> None:
        self._store.clear()


cache = TTLCache()
