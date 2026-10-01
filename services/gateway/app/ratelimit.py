"""Per-tenant token-bucket rate limiter.

Single-replica in-memory implementation. With HPA scaling the effective limit is
`rpm * replicas`; ADR-0001 documents moving this to Azure Cache for Redis or
Azure API Management in front of the gateway for a hard global limit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._buckets: dict[str, _Bucket] = {}
        self._clock = clock

    def allow(self, key: str, per_minute: int) -> bool:
        now = self._clock()
        b = self._buckets.get(key)
        if b is None:
            b = self._buckets[key] = _Bucket(tokens=float(per_minute), updated=now)
        b.tokens = min(per_minute, b.tokens + (now - b.updated) * per_minute / 60.0)
        b.updated = now
        if b.tokens >= 1:
            b.tokens -= 1
            return True
        return False


class BudgetTracker:
    """Monthly spend per tenant (in-memory; production reads the audit stream)."""

    def __init__(self) -> None:
        self._spent: dict[tuple[str, str], float] = {}

    @staticmethod
    def _month() -> str:
        return time.strftime("%Y-%m", time.gmtime())

    def spent(self, tenant: str) -> float:
        return self._spent.get((tenant, self._month()), 0.0)

    def add(self, tenant: str, eur: float) -> None:
        k = (tenant, self._month())
        self._spent[k] = self._spent.get(k, 0.0) + eur
