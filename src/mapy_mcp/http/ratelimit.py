"""Lokální hlídání rate limitů.

API Mapy.com nevrací X-RateLimit-* ani Retry-After, takže limity nejde odečíst z odpovědi —
musí se znát dopředu. Hodnoty pocházejí z popisů endpointů v OpenAPI specifikacích.
"""

from __future__ import annotations

import asyncio
import time

# Požadavků za sekundu podle skupiny endpointů.
# U rgeocode si specifikace protiřečí (200 i 100 v jedné větě) — bereme konzervativní 100.
LIMITS: dict[str, float] = {
    "geocode": 100.0,
    "routing": 30.0,
    "elevation": 30.0,
    "static": 30.0,
    "timezone": 300.0,
    "tiles": 500.0,
}


class TokenBucket:
    """Klasický token bucket. Kapacita = limit za sekundu, doplňování plynulé."""

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.capacity = rate
        self._tokens = rate
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / self.rate)


class RateLimiter:
    def __init__(self, limits: dict[str, float] | None = None) -> None:
        self._limits = limits or LIMITS
        self._buckets: dict[str, TokenBucket] = {}

    async def acquire(self, group: str) -> None:
        bucket = self._buckets.get(group)
        if bucket is None:
            bucket = TokenBucket(self._limits.get(group, 30.0))
            self._buckets[group] = bucket
        await bucket.acquire()
