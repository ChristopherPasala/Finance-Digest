"""Autonomous market scanner — LLM-generated universe from daily news + quantitative scoring."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from analysis import llm_client, prompts
from analysis.company_analyzer import _format_snapshot_for_briefing
from analysis.opportunity_scanner import _passes_screener, _score_snapshot
from collectors.aggregator import build_snapshot
from collectors.finnhub_collector import finnhub_collector
from collectors.yfinance_collector import yfinance_collector
from data import database
from data.models import OpportunityScore

log = logging.getLogger(__name__)

_LLM_SCORE_THRESHOLD = 2
_MAX_LLM_CALLS = 5
_UNIVERSE_SIZE = 20
_scan_sem = asyncio.Semaphore(3)   # max 3 concurrent full snapshot builds


# ---------------------------------------------------------------------------
# Universe generation
# ---------------------------------------------------------------------------

async def build_scan_universe(target: int = _UNIVERSE_SIZE) -> list[str]:
    """
    Ask the LLM to suggest `target` tickers to scan today, informed by
    today's general market news. Excludes tickers already tracked.
    Falls back to SPY news if Finnhub general news is unavailable.
    """
    # Fetch general news
    news = await finnhub_collector.get_general_news(limit=30)
    if not news:
        log.info("[market_scanner] Finnhub general news empty, falling back to SPY news")
        news = await yfinance_collector.get_news("SPY", days_back=2)

    headlines = "\n".join(
        f"- {a.get('title', '')} ({a.get('source', '')} {a.get('published_at', '')})"
        for a in news[:25]
        if a.get("title")
    ) or "No headlines available."

    # Tracked tickers to exclude
    companies = await database.get_all_companies()
    portfolio = [c.ticker for c in companies if c.list_type == "portfolio"]
    watchlist = [c.ticker for c in companies if c.list_type == "watchlist"]
    excluded: set[str] = {t.upper() for t in portfolio + watchlist}

    user_prompt = prompts.MARKET_UNIVERSE_USER.format(
        news_headlines=headlines,
        portfolio_tickers=", ".join(portfolio) if portfolio else "None",
        watchlist_tickers=", ".join(watchlist) if watchlist else "None",
        target_count=target,
    )

    log.info("[market_scanner] Asking LLM for %d tickers based on today's news...", target)
    response = await llm_client.complete(
        system_prompt=prompts.ANALYST_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=65536,
        temperature=0.5,
    )

    # Parse: extract 1-5 uppercase letter sequences (valid ticker format)
    raw_tickers = re.findall(r'\b[A-Z]{1,5}\b', response)

    # Deduplicate, exclude tracked, hard-cap
    seen: set[str] = set()
    universe: list[str] = []
    for t in raw_tickers:
        if t not in excluded and t not in seen and t not in {"AND", "OR", "THE", "FOR",
                                                              "IN", "OF", "TO", "A", "IS",
                                                              "BY", "AS", "AT", "BE", "NO",
                                                              "DO", "US", "IF", "ON", "UP"}:
            seen.add(t)
            universe.append(t)
            if len(universe) >= target:
                break

    log.info("[market_scanner] Universe built: %s", ", ".join(universe))
    return universe


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

async def scan_market(trigger_type: str = "scheduled") -> list[OpportunityScore]:
    """
    Full market scan:
      1. Build fresh 20-ticker universe from today's news via LLM
      2. Full build_snapshot for each ticker (no SEC, no AV to protect rate limits)
      3. _passes_screener + _score_snapshot for each
      4. LLM eval for top scorers (score >= 4, max 5 calls)
      5. Persist results to DB
    Returns scored discoveries sorted by score descending.
    """
    t_start = time.perf_counter()

    tickers = await build_scan_universe(target=_UNIVERSE_SIZE)
    if not tickers:
        log.warning("[market_scanner] Universe generation returned no tickers")
        return []

    log.info("[market_scanner] Scanning %d tickers: %s", len(tickers), ", ".join(tickers))

    # Build snapshots concurrently, gated by semaphore
    async def _fetch(ticker: str) -> OpportunityScore | None:
        async with _scan_sem:
            try:
                snap = await build_snapshot(
                    ticker, list_type="watchlist",
                    include_sec=False, include_av=False,
                )
                if not snap.has_data():
                    log.debug("[market_scanner] %s has no data, skipping", ticker)
                    return None

                # Screener used only for logging context — market scan shows all tickers
                # with data so the user can see the full ranked list, not just "profitable" ones.
                passes, reason = _passes_screener(snap)
                if not passes:
                    log.debug("[market_scanner] %s screener note: %s", ticker, reason)

                score, signals, p_score = _score_snapshot(snap)
                # Append screener note to signals if it failed, for transparency
                if not passes and reason:
                    signals = signals + [f"[Screener: {reason}]"]
                return OpportunityScore(
                    ticker=ticker,
                    name=snap.name,
                    score=score,
                    signals=signals,
                    piotroski_fscore=p_score,
                    llm_evaluation=None,
                    snapshot=snap,
                )
            except Exception as e:
                log.warning("[market_scanner] %s error: %s", ticker, e)
                return None

    raw_results = await asyncio.gather(*[_fetch(t) for t in tickers])
    scored = sorted(
        [r for r in raw_results if r is not None],
        key=lambda s: s.score,
        reverse=True,
    )
    log.info("[market_scanner] %d/%d tickers returned data", len(scored), len(tickers))

    # LLM eval for top scorers
    llm_count = 0
    for opp in scored:
        if llm_count >= _MAX_LLM_CALLS:
            break
        if opp.score >= _LLM_SCORE_THRESHOLD and opp.snapshot is not None:
            try:
                fv = _format_snapshot_for_briefing(opp.snapshot, None)
                fv["score"] = opp.score
                fv["signals_list"] = "\n".join(f"  + {s}" for s in opp.signals)
                opp.llm_evaluation = await llm_client.complete(
                    system_prompt=prompts.ANALYST_SYSTEM,
                    user_prompt=prompts.OPPORTUNITY_EVAL_USER.format(**fv),
                    max_tokens=65536,
                    temperature=0.3,
                )
                llm_count += 1
            except Exception as e:
                log.warning("[market_scanner] LLM eval failed for %s: %s", opp.ticker, e)

    duration = time.perf_counter() - t_start

    # Persist to DB
    scan_id = await database.log_market_scan(
        trigger_type=trigger_type,
        tickers_scanned=len(tickers),
        stage1_passed=len(scored),
        discoveries_found=len(scored),
        top_tickers=[o.ticker for o in scored[:10]],
        duration_seconds=duration,
    )
    if scored:
        await database.save_market_discoveries(
            scan_id=scan_id,
            discoveries=[
                {
                    "ticker": o.ticker,
                    "name": o.name,
                    "sector": None,
                    "score": o.score,
                    "signals": o.signals,
                    "llm_evaluation": o.llm_evaluation,
                }
                for o in scored
            ],
        )

    log.info(
        "[market_scanner] Scan complete in %.1fs — %d discoveries",
        duration, len(scored),
    )
    return scored


# ---------------------------------------------------------------------------
# Daily discoveries helpers
# ---------------------------------------------------------------------------

async def initialize_daily_discoveries(date: str) -> list[OpportunityScore]:
    """
    6am initializer: wipe today's list and run a full scan.
    All results are upserted into daily_discoveries for `date`.
    """
    await database.clear_daily_discoveries(date)
    discoveries = await scan_market(trigger_type="scheduled")
    for opp in discoveries:
        await database.upsert_daily_discovery(date, {
            "ticker": opp.ticker,
            "name": opp.name,
            "sector": None,
            "score": opp.score,
            "signals": opp.signals,
            "llm_evaluation": opp.llm_evaluation,
        })
    return discoveries


async def refresh_daily_discoveries(date: str) -> tuple[list[OpportunityScore], int]:
    """
    Manual refresh: run a new scan and merge results into today's list.
    New score >= existing score wins (ties go to new).
    Returns (new_scan_results, total_count_for_today).
    """
    new_results = await scan_market(trigger_type="manual")
    for opp in new_results:
        await database.upsert_daily_discovery(date, {
            "ticker": opp.ticker,
            "name": opp.name,
            "sector": None,
            "score": opp.score,
            "signals": opp.signals,
            "llm_evaluation": opp.llm_evaluation,
        })
    total = await database.get_daily_discovery_count(date)
    return new_results, total


# ---------------------------------------------------------------------------
# PDF report sections
# ---------------------------------------------------------------------------

def build_discovery_report_sections(
    discoveries: list[OpportunityScore],
    scan_stats: dict,
) -> list[str]:
    """Build text sections for the market discovery PDF."""
    sections: list[str] = []

    scanned_at = scan_stats.get("scanned_at", "N/A")
    tickers_scanned = scan_stats.get("tickers_scanned", "?")
    discoveries_found = scan_stats.get("discoveries_found", "?")
    duration = scan_stats.get("duration_seconds", "?")

    header = (
        f"# Market Discovery Report\n\n"
        f"Scan date: {scanned_at}\n"
        f"Tickers evaluated: {tickers_scanned}  |  "
        f"Passed screener: {discoveries_found}  |  "
        f"Scan duration: {duration}s\n\n"
        f"Universe generated fresh from today's market news headlines via LLM.\n"
        f"Each run produces a different set of tickers based on current events."
    )
    sections.append(header)

    if not discoveries:
        sections.append(
            "No discoveries passed the quantitative screener in this scan.\n\n"
            "This may mean today's LLM-suggested tickers did not meet the hard filters "
            "(profitability, revenue growth, debt/equity). Try `/scan` again tomorrow "
            "or add tickers manually with `/add TICKER watchlist`."
        )
    else:
        for rank, opp in enumerate(discoveries, start=1):
            score_filled = min(max(opp.score, 0), 15)
            score_bar = "*" * score_filled + "-" * (15 - score_filled)
            signals_text = (
                "\n".join(f"- {s}" for s in opp.signals)
                if opp.signals else "- No signals triggered"
            )
            block = (
                f"--- DISCOVERY #{rank}: {opp.ticker} ---\n\n"
                f"## {opp.ticker} — {opp.name or opp.ticker}\n\n"
                f"Score: {opp.score}/15  [{score_bar}]\n\n"
                f"### Triggered Signals\n\n"
                f"{signals_text}\n\n"
            )
            if opp.llm_evaluation:
                block += f"### LLM Evaluation\n\n{opp.llm_evaluation}\n\n"
            else:
                block += (
                    "### LLM Evaluation\n\n"
                    "Not evaluated (score below threshold or evaluation limit reached).\n\n"
                )
            sections.append(block)

    sections.append(
        "---\n\n"
        "IMPORTANT: This report is generated automatically using quantitative signals "
        "and an AI language model. It does not constitute financial advice. "
        "Always conduct your own research before making any investment decision. "
        "The system has no knowledge of your personal financial situation or risk tolerance."
    )
    return sections
