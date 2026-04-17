"""Aggregates all data sources into a unified CompanySnapshot."""
from __future__ import annotations

import asyncio
import difflib
import logging
from typing import Any

from collectors.alphavantage_collector import alphavantage_collector
from collectors.finnhub_collector import finnhub_collector
from collectors.finviz_collector import finviz_collector
from collectors.sec_edgar_collector import sec_edgar_collector
from collectors.yfinance_collector import yfinance_collector
from data.models import CompanySnapshot

log = logging.getLogger(__name__)

# Finviz has no official rate limit but 429s appear above ~3 concurrent requests.
# All finviz calls must go through this semaphore.
_FINVIZ_SEM = asyncio.Semaphore(3)


async def _finviz(fn, *args):
    """Run a synchronous finviz call in a thread, serialised by _FINVIZ_SEM."""
    async with _FINVIZ_SEM:
        return await asyncio.to_thread(fn, *args)


def _deduplicate_news(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles based on title similarity."""
    seen_titles: list[str] = []
    unique: list[dict] = []
    for article in articles:
        title = article.get("title", "").lower()
        is_dup = any(
            difflib.SequenceMatcher(None, title, seen).ratio() > 0.85
            for seen in seen_titles
        )
        if not is_dup and title:
            seen_titles.append(title)
            unique.append(article)
    return unique


async def build_snapshot(ticker: str, list_type: str = "watchlist",
                          include_sec: bool = True,
                          include_av: bool = True) -> CompanySnapshot:
    """Build a CompanySnapshot by running all collectors concurrently."""
    import time
    ticker = ticker.upper()
    errors: list[str] = []
    t0 = time.perf_counter()

    sources = ["yfinance", "finnhub", "finviz", "alpha_vantage"]
    if include_sec:
        sources.append("SEC EDGAR")
    log.info("[%s] Fetching data from: %s", ticker, ", ".join(sources))

    async def safe(name: str, coro):
        t = time.perf_counter()
        try:
            result = await coro
            log.info("[%s] %s done (%.1fs)", ticker, name, time.perf_counter() - t)
            return result
        except Exception as e:
            log.warning("[%s] %s failed (%.1fs): %s", ticker, name, time.perf_counter() - t, e)
            errors.append(f"{name}: {e}")
            return None

    # Run all collectors concurrently
    tasks = {
        "quote":       safe("yf_quote",       yfinance_collector.get_quote(ticker)),
        "info":        safe("yf_info",         yfinance_collector.get_info(ticker)),
        "technicals":  safe("yf_technicals",   yfinance_collector.get_technicals(ticker)),
        "news_yf":     safe("yf_news",         yfinance_collector.get_news(ticker)),
        "financials":  safe("yf_financials",   yfinance_collector.get_financials_history(ticker)),
        "cagr":        safe("yf_cagr",         yfinance_collector.compute_cagr(ticker)),
        "returns":     safe("yf_returns",      yfinance_collector.compute_returns(ticker)),
        "capex":       safe("yf_capex",        yfinance_collector.compute_capex(ticker)),
        "fin_health":  safe("yf_fin_health",   yfinance_collector.compute_financial_health(ticker)),
        "earnings":    safe("fh_earnings",     finnhub_collector.get_earnings(ticker)),
        "analyst":     safe("fh_analyst",      finnhub_collector.get_analyst_recommendations(ticker)),
        "news_fh":     safe("fh_news",         finnhub_collector.get_news(ticker)),
        "insider":     safe("fh_insider",      finnhub_collector.get_insider_transactions(ticker)),
        "fh_fin":      safe("fh_financials",   finnhub_collector.get_basic_financials(ticker)),
        "fv_fund":     safe("fv_fundamentals", _finviz(finviz_collector.get_fundamentals, ticker)),
        "news_fv":     safe("fv_news",         _finviz(finviz_collector.get_news, ticker)),
    }
    if include_av:
        tasks["sentiment"] = safe("av_sentiment", alphavantage_collector.get_news_sentiment(ticker))
    if include_sec:
        tasks["sec_mda"] = safe("sec_mda", sec_edgar_collector.get_mda_excerpt(ticker))

    results = await asyncio.gather(*tasks.values(), return_exceptions=False)
    res = dict(zip(tasks.keys(), results))
    log.info("[%s] All collectors finished in %.1fs", ticker, time.perf_counter() - t0)

    # Merge news from multiple sources and deduplicate
    all_news: list[dict] = []
    for source in ("news_yf", "news_fh", "news_fv"):
        news = res.get(source) or []
        all_news.extend(news)
    # Add Alpha Vantage articles
    av_articles = (res.get("sentiment") or {}).get("articles", [])
    all_news.extend(av_articles)
    deduped_news = _deduplicate_news(all_news)[:25]

    # Resolve company name
    info = res.get("info") or {}
    name = info.get("name") or ticker

    # Merge financials — finviz fills gaps, yfinance/finnhub take priority where present
    fh_fin = res.get("fh_fin") or {}
    fv_fund = res.get("fv_fund") or {}
    # Order: finviz as base → yfinance info → finnhub (highest priority)
    financials = {**fv_fund, **info, **fh_fin}

    # Fill analyst_targets from finviz if not provided by finnhub
    analyst = res.get("analyst") or {}
    if not analyst.get("target_mean") and fv_fund.get("analyst_target_mean"):
        analyst = {**analyst,
                   "target_mean": fv_fund["analyst_target_mean"],
                   "recommendation": fv_fund.get("recommendation")}

    # Fill insider_transactions from finviz if finnhub returned nothing
    insider = res.get("insider") or []
    if not insider:
        insider = await _finviz(finviz_collector.get_insider_transactions, ticker)

    # Fetch peers via Finviz's curated peer list
    peers: list[dict] = await _finviz(finviz_collector.get_peers, ticker)

    # SEC data
    sec_text, sec_form = None, None
    if include_sec and res.get("sec_mda"):
        sec_text, sec_form = res["sec_mda"]

    snapshot = CompanySnapshot(
        ticker=ticker,
        name=name,
        list_type=list_type,
        quote=res.get("quote") or {},
        technicals=res.get("technicals") or {},
        financials=financials,
        cagr=res.get("cagr") or {},
        returns=res.get("returns") or {},
        capex=res.get("capex") or {},
        financial_health=res.get("fin_health") or {},
        news=deduped_news,
        sentiment=res.get("sentiment") or {},
        earnings=res.get("earnings") or {},
        analyst_targets=analyst,
        insider_transactions=insider,
        peers=peers,
        sec_summary=sec_text,
        sec_form_type=sec_form,
        errors=errors,
    )

    # Update company name in DB if resolved
    if name != ticker:
        try:
            from data.database import update_company_name
            await update_company_name(ticker, name)
        except Exception:
            pass

    return snapshot
