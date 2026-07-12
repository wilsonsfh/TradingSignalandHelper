"""A tiny in-process, per-key sliding-window rate limiter.

Used to backstop the /webhook endpoint. This is process-local (not shared across
workers); the durable edge limit is expected to live at the proxy (e.g. Cloudflare).
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Callable, Deque, Dict


class RateLimiter:
    def __init__(self, per_min: int, now: Callable[[], float] = time.monotonic) -> None:
        self.per_min = max(1, per_min)
        self._now = now
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = self._now()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= 60.0:
                hits.popleft()
            if len(hits) >= self.per_min:
                return False
            hits.append(now)
            return True
