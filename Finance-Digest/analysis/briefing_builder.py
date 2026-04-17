"""Briefing orchestration — daily watchlist + weekly portfolio deep dive."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from analysis import llm_client, prompts
from utils.site_publisher import publish
from analysis.company_analyzer import run_portfolio_briefing_section, run_watchlist_brief
from analysis.opportunity_scanner import score_snapshots, suggest_new_tickers, _score_snapshot
from collectors.aggregator import build_snapshot
from collectors.finnhub_collector import finnhub_collector
from collectors.yfinance_collector import yfinance_collector
from data import database
from data.models import CompanySnapshot

log = logging.getLogger(__name__)


async def build_daily_briefing(trigger_type: str = "scheduled") -> list[str]:
    """
    Daily briefing: watchlist entry-point checks + opportunity scores.
    Excludes portfolio companies (covered in the weekly deep dive).
    """
    companies = await database.get_all_companies()
    portfolio = [c for c in companies if c.list_type == "portfolio"]
    watchlist = [c for c in companies if c.list_type == "watchlist"]

    if not companies:
        return ["No companies tracked. Use `/add TICKER watchlist` to get started."]

    sections: list[str] = []

    now = datetime.utcnow().strftime("%A, %B %d, %Y")
    sections.append(
        f"**Daily Watchlist Briefing — {now}**\n"
        f"Watchlist: {len(watchlist)} companies  |  "
        f"Portfolio deep dive runs weekly (see separate report)"
    )

    # General market news summary
    sections.append("━━━ **MARKET OVERVIEW** ━━━")
    try:
        news = await finnhub_collector.get_general_news(limit=25)
        if not news:
            news = await yfinance_collector.get_news("SPY", days_back=2)
        if news:
            headlines = "\n".join(
                f"- {a.get('title', '')} ({a.get('source', '')})"
                for a in news[:20]
                if a.get("title")
            )
            summary = await llm_client.complete(
                system_prompt=prompts.ANALYST_SYSTEM,
                user_prompt=prompts.MARKET_NEWS_SUMMARY_USER.format(news_headlines=headlines),
                max_tokens=65536,
                temperature=0.3,
            )
            sections.append(summary)
        else:
            sections.append("No general market news available today.")
    except Exception as e:
        log.warning("[daily] Market news summary failed: %s", e)
        sections.append(f"Market overview unavailable: {e}")

    # Watchlist companies — build snapshots, then run briefings + scoring from the same snaps
    built_snaps: list[CompanySnapshot] = []

    if watchlist:
        sections.append("━━━ **WATCHLIST** ━━━")
        batch_size = 3
        for i in range(0, len(watchlist), batch_size):
            batch = watchlist[i:i + batch_size]
            tickers = [c.ticker for c in batch]
            log.info("[daily] Watchlist batch %d-%d: %s",
                     i + 1, min(i + batch_size, len(watchlist)), ", ".join(tickers))
            batch_results = await asyncio.gather(
                *[_build_watchlist_company(c) for c in batch],
                return_exceptions=True,
            )
            for result in batch_results:
                if isinstance(result, Exception):
                    sections.append(f"⚠️ Watchlist company failed: {result}")
                elif result is not None:
                    snap, brief = result
                    built_snaps.append(snap)
                    sections.append(brief)
    else:
        sections.append("No watchlist companies tracked. Use `/add TICKER watchlist` to add some.")

    # Score snapshots for paper trader — runs silently, no separate section rendered
    try:
        scores = await score_snapshots(built_snaps) if built_snaps else []
    except Exception as e:
        log.error("[daily] Opportunity scoring failed: %s", e)
        scores = []

    # Paper trading session — reuses the same scores, no extra API calls
    sections.append("━━━ **PAPER PORTFOLIO** ━━━")
    try:
        from analysis.paper_trader import run_paper_trading_session
        paper_lines = await run_paper_trading_session(scores if built_snaps else [])
        sections.append("\n".join(paper_lines) if paper_lines else "No activity today.")
    except Exception as e:
        log.warning("[daily] Paper trading session failed: %s", e)
        sections.append(f"Paper trading unavailable: {e}")

    # Weekly new ticker suggestions (once per 7 days)
    try:
        last_suggestion = await database.get_last_briefing_of_type("weekly_suggestions")
        cutoff = datetime.utcnow() - timedelta(days=7)
        should_suggest = (
            last_suggestion is None
            or datetime.fromisoformat(last_suggestion["triggered_at"]) < cutoff
        )
        if should_suggest and portfolio:
            port_tickers = [c.ticker for c in portfolio]
            watch_tickers = [c.ticker for c in watchlist]
            suggestions = await suggest_new_tickers(port_tickers, watch_tickers)
            sections.append(f"━━━ **WEEKLY NEW IDEAS** ━━━\n{suggestions}")
            await database.log_briefing(
                channel_id="weekly",
                trigger_type="weekly_suggestions",
                status="success",
                tickers=port_tickers,
            )
    except Exception as e:
        log.warning("[daily] Weekly suggestion failed: %s", e)

    # Publish to static site in the background
    slug = f"daily-{datetime.utcnow().strftime('%Y-%m-%d')}"
    title = f"Daily Briefing — {datetime.utcnow().strftime('%B %d, %Y')}"
    asyncio.get_event_loop().run_in_executor(None, publish, slug, title, sections, "briefings")

    return sections


async def build_portfolio_briefing(trigger_type: str = "scheduled") -> list[str]:
    """
    Weekly portfolio deep dive: full briefing section for each portfolio company,
    including thesis integrity checks. SEC filings included.
    """
    companies = await database.get_all_companies()
    portfolio = [c for c in companies if c.list_type == "portfolio"]

    if not portfolio:
        return ["No portfolio companies tracked. Use `/add TICKER portfolio` to add some."]

    sections: list[str] = []

    now = datetime.utcnow().strftime("%A, %B %d, %Y")
    sections.append(
        f"**Weekly Portfolio Deep Dive — {now}**\n"
        f"{len(portfolio)} portfolio companies"
    )

    sections.append("━━━ **PORTFOLIO** ━━━")
    for idx, company in enumerate(portfolio, 1):
        log.info("[portfolio] %d/%d: %s", idx, len(portfolio), company.ticker)
        try:
            snap = await build_snapshot(company.ticker, list_type="portfolio", include_sec=True)
            analysis = await run_portfolio_briefing_section(snap)
            sections.append(analysis)
            log.info("[portfolio] %d/%d: %s done", idx, len(portfolio), company.ticker)
        except Exception as e:
            log.error("[portfolio] %s failed: %s", company.ticker, e)
            sections.append(f"⚠️ **{company.ticker}**: Data unavailable ({e})")

    # Publish to static site in the background
    slug = f"portfolio-{datetime.utcnow().strftime('%Y-%m-%d')}"
    title = f"Portfolio Deep Dive — {datetime.utcnow().strftime('%B %d, %Y')}"
    asyncio.get_event_loop().run_in_executor(None, publish, slug, title, sections, "briefings")

    return sections


# Keep the old name as an alias so /briefing (manual, no type arg) still works
async def build_morning_briefing(trigger_type: str = "scheduled") -> list[str]:
    """Legacy alias — triggers the daily watchlist briefing."""
    return await build_daily_briefing(trigger_type=trigger_type)


async def _build_watchlist_company(company) -> tuple[CompanySnapshot, str] | None:
    """Build snapshot and generate watchlist brief. Returns (snap, text) for reuse in scoring."""
    try:
        snap = await build_snapshot(company.ticker, list_type="watchlist", include_sec=False)
        brief = await run_watchlist_brief(snap)
        score, signals, _ = _score_snapshot(snap)
        filled = min(max(score, 0), 15)
        bar = "█" * filled + "░" * (15 - filled)
        signal_str = " | ".join(signals[:3]) if signals else "No signals triggered"
        header = (
            f"**{snap.ticker}** — {snap.name} | **{score}/15** `{bar}`\n"
            f"> {signal_str}"
        )
        return snap, f"{header}\n{brief}"
    except Exception as e:
        log.error("[briefing] Watchlist company %s failed: %s", company.ticker, e)
        raise
