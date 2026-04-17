"""Alpha Vantage collector — news sentiment and fundamentals overview."""
from __future__ import annotations

import logging
from typing import Any

import requests

from collectors.base import BaseCollector
from utils import cache, rate_limiter
from utils.config import config

log = logging.getLogger(__name__)
_limiter = rate_limiter.LIMITERS["alphavantage"]

AV_BASE = "https://www.alphavantage.co/query"


class AlphaVantageCollector(BaseCollector):
    name = "alphavantage"

    def _enabled(self) -> bool:
        return bool(config.alpha_vantage_key)

    def _get(self, params: dict) -> dict | None:
        if not self._enabled():
            return None
        params["apikey"] = config.alpha_vantage_key
        resp = requests.get(AV_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if "Note" in data or "Information" in data:
            raise RuntimeError(f"Alpha Vantage rate limit hit: {data.get('Note') or data.get('Information')}")
        return data

    async def get_news_sentiment(self, ticker: str) -> dict:
        if not self._enabled():
            return {}
        cached = await cache.get(ticker, "av_sentiment")
        if cached:
            return cached

        await _limiter.acquire()

        def _fetch():
            data = self._get({"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": "20"})
            if not data:
                return {}
            feed = data.get("feed", [])
            overall_scores = [float(a.get("overall_sentiment_score", 0)) for a in feed]
            bullish = sum(1 for s in overall_scores if s > 0.15)
            bearish = sum(1 for s in overall_scores if s < -0.15)
            avg_score = sum(overall_scores) / len(overall_scores) if overall_scores else 0

            articles = []
            for a in feed[:10]:
                ticker_sentiments = a.get("ticker_sentiment", [])
                ticker_score = next(
                    (float(ts["ticker_sentiment_score"]) for ts in ticker_sentiments if ts["ticker"] == ticker), None
                )
                articles.append({
                    "title": a.get("title", ""),
                    "source": a.get("source", ""),
                    "published_at": a.get("time_published", "")[:8],
                    "sentiment_score": ticker_score,
                    "url": a.get("url", ""),
                })
            return {
                "avg_sentiment_score": round(avg_score, 4),
                "bullish_count": bullish,
                "bearish_count": bearish,
                "total_articles": len(feed),
                "articles": articles,
            }

        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "av_sentiment", result)
        return result or {}

    async def get_overview(self, ticker: str) -> dict:
        """Fundamental overview — supplemental to yfinance."""
        if not self._enabled():
            return {}
        cached = await cache.get(ticker, "av_overview")
        if cached:
            return cached

        await _limiter.acquire()

        def _fetch():
            data = self._get({"function": "OVERVIEW", "symbol": ticker})
            if not data or "Symbol" not in data:
                return {}
            return {
                "sector": data.get("Sector"),
                "industry": data.get("Industry"),
                "pe_ratio": _safe_float(data.get("PERatio")),
                "peg_ratio": _safe_float(data.get("PEGRatio")),
                "price_to_book": _safe_float(data.get("PriceToBookRatio")),
                "ev_to_ebitda": _safe_float(data.get("EVToEBITDA")),
                "dividend_yield": _safe_float(data.get("DividendYield")),
                "eps": _safe_float(data.get("EPS")),
                "revenue_per_share": _safe_float(data.get("RevenuePerShareTTM")),
                "analyst_target": _safe_float(data.get("AnalystTargetPrice")),
                "52w_high": _safe_float(data.get("52WeekHigh")),
                "52w_low": _safe_float(data.get("52WeekLow")),
                "description": (data.get("Description", "") or "")[:400],
            }

        result = await self._fetch_with_retry(_fetch)
        if result:
            await cache.set(ticker, "av_overview", result, ttl_seconds=24 * 3600)
        return result or {}


def _safe_float(val: Any) -> float | None:
    try:
        f = float(val)
        return None if f != f else f  # NaN check
    except (TypeError, ValueError):
        return None


alphavantage_collector = AlphaVantageCollector()
