"""Finnhub collector — earnings, analyst recommendations, insider transactions."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import finnhub

from collectors.base import BaseCollector
from utils import cache, rate_limiter
from utils.config import config

log = logging.getLogger(__name__)
_limiter = rate_limiter.LIMITERS["finnhub"]


class FinnhubCollector(BaseCollector):
    name = "finnhub"

    def _client(self) -> finnhub.Client | None:
        if not config.finnhub_key:
            return None
        return finnhub.Client(api_key=config.finnhub_key)

    def _enabled(self) -> bool:
        return bool(config.finnhub_key)

    async def get_earnings(self, ticker: str) -> dict:
        if not self._enabled():
            return {}
        cached = await cache.get(ticker, "earnings")
        if cached:
            return cached

        await _limiter.acquire()

        def _fetch():
            client = self._client()
            if not client:
                return {}

            # Historical earnings
            earnings_hist = []
            try:
                hist = client.company_earnings(ticker, limit=8) or []
                for e in hist:
                    actual = _safe_float(e.get("actual"))
                    estimate = _safe_float(e.get("estimate"))
                    surprise_pct = None
                    if actual is not None and estimate is not None and estimate != 0:
                        surprise_pct = round((actual - estimate) / abs(estimate) * 100, 2)
                    earnings_hist.append({
                        "period": e.get("period", ""),
                        "actual_eps": actual,
                        "estimate_eps": estimate,
                        "surprise_pct": surprise_pct,
                    })
            except Exception as e:
                log.warning("[finnhub] company_earnings unavailable: %s", e)

            # Next earnings date
            next_date = None
            next_estimate = None
            try:
                today = datetime.utcnow()
                future = today + timedelta(days=90)
                calendar_data = client.earnings_calendar(
                    _from=today.strftime("%Y-%m-%d"),
                    to=future.strftime("%Y-%m-%d"),
                    symbol=ticker,
                )
                cal_items = (calendar_data or {}).get("earningsCalendar", [])
                next_date = cal_items[0].get("date") if cal_items else None
                next_estimate = _safe_float(cal_items[0].get("epsEstimate")) if cal_items else None
            except Exception as e:
                log.warning("[finnhub] earnings_calendar unavailable: %s", e)

            return {
                "history": earnings_hist,
                "next_date": next_date,
                "next_eps_estimate": next_estimate,
            }

        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "earnings", result)
        return result or {}

    async def get_analyst_recommendations(self, ticker: str) -> dict:
        # recommendation_trends and price_target require Finnhub premium — not available on free tier
        return {}

    async def get_news(self, ticker: str, days_back: int = 7) -> list[dict]:
        if not self._enabled():
            return []
        cached = await cache.get(ticker, "fh_news")
        if cached is not None:
            return cached

        await _limiter.acquire()

        def _fetch():
            client = self._client()
            if not client:
                return []
            end = datetime.utcnow()
            start = end - timedelta(days=days_back)
            articles = client.company_news(
                ticker,
                _from=start.strftime("%Y-%m-%d"),
                to=end.strftime("%Y-%m-%d"),
            ) or []
            return [
                {
                    "title": a.get("headline", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", ""),
                    "published_at": datetime.utcfromtimestamp(a.get("datetime", 0)).strftime("%Y-%m-%d"),
                    "sentiment": a.get("sentiment", ""),
                }
                for a in articles[:20]
            ]

        result = await self._fetch_with_retry(_fetch)
        if result is not None:
            await cache.set(ticker, "fh_news", result)
        return result or []

    async def get_insider_transactions(self, ticker: str) -> list[dict]:
        # stock_insider_transactions (Ownership) requires Finnhub premium — not available on free tier
        return []

    async def get_basic_financials(self, ticker: str) -> dict:
        # company_basic_financials (Key Metrics) requires Finnhub premium — not available on free tier
        return {}

    async def get_general_news(self, limit: int = 30) -> list[dict]:
        """Fetch general market news headlines (not company-specific). Free tier."""
        if not self._enabled():
            return []
        cached = await cache.get("__market__", "general_news")
        if cached is not None:
            return cached

        await _limiter.acquire()

        def _fetch():
            client = self._client()
            if not client:
                return []
            articles = client.general_news("general", min_id=0) or []
            return [
                {
                    "title": a.get("headline", ""),
                    "source": a.get("source", ""),
                    "published_at": datetime.utcfromtimestamp(
                        a.get("datetime", 0)
                    ).strftime("%Y-%m-%d"),
                }
                for a in articles[:limit]
                if a.get("headline")
            ]

        result = await self._fetch_with_retry(_fetch)
        if result is not None:
            await cache.set("__market__", "general_news", result, ttl_seconds=3600)
        return result or []


def _safe_float(val: Any) -> float | None:
    try:
        f = float(val)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


finnhub_collector = FinnhubCollector()
