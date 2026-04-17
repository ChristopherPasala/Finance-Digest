"""Abstract base collector with retry logic."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all data collectors."""

    name: str = "base"

    async def _fetch_with_retry(self, fn, *args, retries: int = 3, backoff: float = 2.0, **kwargs) -> Any:
        """Execute an async or sync callable with exponential backoff retries."""
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                if asyncio.iscoroutinefunction(fn):
                    return await fn(*args, **kwargs)
                else:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
            except Exception as e:
                last_exc = e
                # 403 = premium endpoint — retrying won't help, skip immediately
                status = getattr(e, "status_code", None)
                if status == 403:
                    log.warning("[%s] Endpoint requires premium plan (403) — skipping: %s", self.name, e)
                    return None
                # TypeError = data structure mismatch (e.g. yfinance returning None for
                # invalid/delisted tickers). Retrying will produce the same result.
                if isinstance(e, TypeError):
                    log.debug("[%s] Non-retriable TypeError — skipping: %s", self.name, e)
                    return None
                wait = backoff ** attempt
                log.warning("[%s] Attempt %d/%d failed: %s. Retrying in %.1fs",
                            self.name, attempt + 1, retries, e, wait)
                await asyncio.sleep(wait)

        log.error("[%s] All %d retries failed: %s", self.name, retries, last_exc)
        return None
