"""In-memory TTL cache backed by SQLite for persistence across restarts."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

# In-memory store: {(ticker, data_type): (payload_dict, expires_at_monotonic)}
_memory: dict[tuple[str, str], tuple[Any, float]] = {}
_lock = asyncio.Lock()

# TTL presets (seconds)
TTL = {
    "quote":          15 * 60,       # 15 minutes
    "technicals":     15 * 60,
    "news":           60 * 60,       # 1 hour
    "financials":     24 * 60 * 60,  # 24 hours
    "fundamentals":   24 * 60 * 60,
    "earnings":       24 * 60 * 60,
    "analyst":        24 * 60 * 60,
    "sec_filing":      7 * 24 * 60 * 60,  # 7 days
    "sec_cik_map":    7 * 24 * 60 * 60,
    "analysis":        6 * 60 * 60,   # 6 hours (LLM results)
    "insider":        24 * 60 * 60,
    "peers":          24 * 60 * 60,
}


async def get(ticker: str, data_type: str) -> Any | None:
    """Return cached value or None if missing/expired."""
    key = (ticker.upper(), data_type)
    async with _lock:
        entry = _memory.get(key)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        if key in _memory:
            del _memory[key]

    # Fall back to SQLite cache
    try:
        from data.database import get_cache
        row = await get_cache(ticker, data_type)
        if row:
            payload = json.loads(row["payload"])
            ttl = TTL.get(data_type, 3600)
            async with _lock:
                _memory[key] = (payload, time.monotonic() + ttl)
            return payload
    except Exception as e:
        log.debug("Cache DB read failed for %s/%s: %s", ticker, data_type, e)

    return None


async def set(ticker: str, data_type: str, payload: Any, ttl_seconds: int | None = None) -> None:
    """Store a value in memory and SQLite cache."""
    if ttl_seconds is None:
        ttl_seconds = TTL.get(data_type, 3600)

    key = (ticker.upper(), data_type)
    expires_mono = time.monotonic() + ttl_seconds
    expires_dt = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    async with _lock:
        _memory[key] = (payload, expires_mono)

    try:
        from data.database import set_cache
        await set_cache(ticker, data_type, json.dumps(payload), expires_dt.isoformat())
    except Exception as e:
        log.debug("Cache DB write failed for %s/%s: %s", ticker, data_type, e)


async def invalidate(ticker: str) -> None:
    """Remove all cache entries for a ticker."""
    ticker_upper = ticker.upper()
    async with _lock:
        keys_to_remove = [k for k in _memory if k[0] == ticker_upper]
        for k in keys_to_remove:
            del _memory[k]

    try:
        from data.database import invalidate_cache
        await invalidate_cache(ticker)
    except Exception as e:
        log.debug("Cache DB invalidate failed for %s: %s", ticker, e)
