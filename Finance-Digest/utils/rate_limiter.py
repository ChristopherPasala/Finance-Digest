"""Token-bucket rate limiter with per-minute and per-day windows."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

log = logging.getLogger(__name__)


class RateLimiter:
    """Async token-bucket rate limiter.

    Enforces both calls_per_minute and calls_per_day limits.
    Callers `await limiter.acquire()` before making an API call.
    """

    def __init__(self, name: str, calls_per_minute: int = 60, calls_per_day: int = 10_000):
        self.name = name
        self.calls_per_minute = calls_per_minute
        self.calls_per_day = calls_per_day
        self._lock = asyncio.Lock()
        # Timestamps of recent calls (monotonic seconds)
        self._minute_window: deque[float] = deque()
        self._day_window: deque[float] = deque()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()

                # Purge old entries
                minute_cutoff = now - 60
                day_cutoff = now - 86_400
                while self._minute_window and self._minute_window[0] < minute_cutoff:
                    self._minute_window.popleft()
                while self._day_window and self._day_window[0] < day_cutoff:
                    self._day_window.popleft()

                # Check limits
                if len(self._day_window) >= self.calls_per_day:
                    wait = self._day_window[0] - day_cutoff
                    log.warning("[%s] Daily limit reached. Waiting %.1fs", self.name, wait)
                    await asyncio.sleep(wait + 0.1)
                    continue

                if len(self._minute_window) >= self.calls_per_minute:
                    wait = self._minute_window[0] - minute_cutoff
                    log.debug("[%s] Per-minute limit reached. Waiting %.1fs", self.name, wait)
                    await asyncio.sleep(wait + 0.1)
                    continue

                # Slot available
                self._minute_window.append(now)
                self._day_window.append(now)
                return

    @property
    def day_calls_used(self) -> int:
        now = time.monotonic()
        day_cutoff = now - 86_400
        return sum(1 for t in self._day_window if t >= day_cutoff)


# Pre-configured limiters for each data source
LIMITERS: dict[str, RateLimiter] = {
    "yfinance":      RateLimiter("yfinance",      calls_per_minute=60,  calls_per_day=1_000),
    "alphavantage":  RateLimiter("alphavantage",  calls_per_minute=5,   calls_per_day=25),
    "finnhub":       RateLimiter("finnhub",        calls_per_minute=55,  calls_per_day=5_000),
    "sec_edgar":     RateLimiter("sec_edgar",      calls_per_minute=10,  calls_per_day=1_000),
    "ollama":        RateLimiter("ollama",          calls_per_minute=60,  calls_per_day=10_000),
}
