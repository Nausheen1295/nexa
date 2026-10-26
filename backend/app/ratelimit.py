"""In-memory sliding-window rate limiter (per client).

Fine for a single instance. For multiple instances, swap for Redis with the
same `check()` signature.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, clock=time.monotonic):
        self.windows = ((60.0, per_minute), (86400.0, per_day))
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> int | None:
        """Record a hit. Returns None if allowed, else seconds until the client may retry."""
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.windows[-1][0]:
                hits.popleft()
            for span, limit in self.windows:
                recent = [t for t in hits if now - t < span]
                if len(recent) >= limit:
                    return max(1, math.ceil(span - (now - recent[0])))
            hits.append(now)
            return None
