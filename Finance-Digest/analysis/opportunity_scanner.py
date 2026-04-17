"""Opportunity scanner — quantitative scoring + LLM evaluation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from analysis import llm_client, prompts
from collectors.aggregator import build_snapshot
from data import database
from data.models import CompanySnapshot, OpportunityScore
from analysis.company_analyzer import _format_snapshot_for_briefing, _news_bullets

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate 1: Screener hard filters
# ---------------------------------------------------------------------------

NEGATIVE_KEYWORDS = {"fraud", "sec investigation", "restatement", "class action", "bankruptcy",
                     "indictment", "delisting", "accounting irregularities"}


def _passes_screener(snap: CompanySnapshot) -> tuple[bool, str | None]:
    """Return (passes, rejection_reason)."""
    f = snap.financials

    # Revenue growth > 5% YoY (relaxed to > -10% to allow brief dips)
    rev_growth = f.get("revenue_growth")
    if rev_growth is not None and rev_growth < -0.10:
        return False, f"Declining revenue ({rev_growth*100:.1f}% YoY)"

    # Must be profitable (net margin > 0)
    net_margin = f.get("profit_margins") or f.get("net_margin_annual")
    if net_margin is not None and net_margin < 0:
        return False, f"Unprofitable (net margin: {net_margin*100:.1f}%)"

    # Debt/equity < 2.5
    de = f.get("debt_to_equity")
    if de is not None and de > 2.5:
        return False, f"High debt/equity ({de:.1f})"

    # Check news for red flags
    news_text = " ".join(a.get("title", "").lower() for a in snap.news)
    for kw in NEGATIVE_KEYWORDS:
        if kw in news_text:
            return False, f"Negative keyword in news: '{kw}'"

    return True, None


# ---------------------------------------------------------------------------
# Piotroski F-Score (9-point fundamental strength signal)
# ---------------------------------------------------------------------------

def _calculate_piotroski(snap: CompanySnapshot) -> tuple[int | None, list[str]]:
    """
    Compute the 9-point Piotroski F-Score across profitability, leverage, and efficiency.
    Returns (score, breakdown_list) or (None, []) if fewer than 5 criteria had data.
    """
    f   = snap.financials
    ret = snap.returns
    fh  = snap.financial_health

    score = 0
    passed: list[str] = []
    checks_attempted = 0

    def _check(condition: bool | None, label: str) -> None:
        nonlocal score, checks_attempted
        if condition is None:
            return  # skip — data unavailable
        checks_attempted += 1
        if condition:
            score += 1
            passed.append(label)

    # ── Profitability (F1–F4) ────────────────────────────────────────────────
    roa_current = f.get("return_on_assets")
    _check(None if roa_current is None else roa_current > 0, "F1: ROA positive")

    ocf_hist  = ret.get("ocf_history", {})
    ocf_years = sorted(ocf_hist.keys(), reverse=True)
    ocf_latest = ocf_hist.get(ocf_years[0]) if ocf_years else None
    _check(None if ocf_latest is None else ocf_latest > 0, "F2: Operating cash flow positive")

    roa_hist  = ret.get("roa_history", {})
    roa_years = sorted(roa_hist.keys(), reverse=True)
    if len(roa_years) >= 2:
        _check(roa_hist[roa_years[0]] > roa_hist[roa_years[1]], "F3: ROA improving YoY")

    # F4: Accruals — OCF > Net Income proxy via cash conversion ratio
    cc_hist  = fh.get("cash_conversion", {})
    cc_years = sorted(cc_hist.keys(), reverse=True)
    cc_latest = cc_hist.get(cc_years[0]) if cc_years else None
    _check(None if cc_latest is None else cc_latest > 1.0, "F4: Accruals quality (OCF > net income)")

    # ── Leverage / Liquidity (F5–F7) ────────────────────────────────────────
    net_debt = fh.get("net_debt_trend", {})
    nd_years = sorted(net_debt.keys(), reverse=True)
    if len(nd_years) >= 2:
        _check(net_debt[nd_years[0]] < net_debt[nd_years[1]], "F5: Leverage decreasing")

    cr_hist  = ret.get("current_ratio_history", {})
    cr_years = sorted(cr_hist.keys(), reverse=True)
    if len(cr_years) >= 2:
        _check(cr_hist[cr_years[0]] > cr_hist[cr_years[1]], "F6: Current ratio improving")

    shares   = fh.get("shares_trend", {})
    sh_years = sorted(shares.keys(), reverse=True)
    if len(sh_years) >= 2:
        _check(shares[sh_years[0]] <= shares[sh_years[1]], "F7: No share dilution")

    # ── Operating Efficiency (F8–F9) ─────────────────────────────────────────
    gm_hist  = ret.get("gross_margin_history", {})
    gm_years = sorted(gm_hist.keys(), reverse=True)
    if len(gm_years) >= 2:
        _check(gm_hist[gm_years[0]] > gm_hist[gm_years[1]], "F8: Gross margin improving")

    at_hist  = ret.get("asset_turnover_history", {})
    at_years = sorted(at_hist.keys(), reverse=True)
    if len(at_years) >= 2:
        _check(at_hist[at_years[0]] > at_hist[at_years[1]], "F9: Asset turnover improving")

    if checks_attempted < 5:
        return None, []

    return score, passed


# ---------------------------------------------------------------------------
# Gate 2: Quantitative scoring
# ---------------------------------------------------------------------------

def _score_snapshot(snap: CompanySnapshot) -> tuple[int, list[str], int | None]:
    score = 0
    signals: list[str] = []
    t = snap.technicals
    f = snap.financials
    q = snap.quote
    a = snap.analyst_targets
    e = snap.earnings
    sentiment = snap.sentiment

    price = q.get("price")
    low_52w = q.get("52w_low")
    high_52w = q.get("52w_high")

    # RSI < 30 (oversold) — tiered by SMA200 context to avoid falling knives
    rsi = t.get("rsi_14")
    sma200_rsi = t.get("sma_200")
    if rsi is not None and rsi < 30:
        if price and sma200_rsi and price >= sma200_rsi * 0.95:
            score += 2
            signals.append(f"RSI oversold ({rsi:.1f}) near/above 200d SMA (strong mean-reversion setup)")
        else:
            score += 1
            signals.append(f"RSI oversold ({rsi:.1f}) but below 200d SMA (possible falling knife)")

    # Positive earnings surprise > 5%
    hist = e.get("history", [])
    if hist:
        surprise = hist[0].get("surprise_pct")
        if surprise is not None and surprise > 5:
            score += 2
            signals.append(f"Earnings beat +{surprise:.1f}%")
        elif surprise is not None and surprise < -5:
            score -= 2
            signals.append(f"Earnings miss {surprise:.1f}%")

    # Analyst buy consensus
    sb = a.get("strong_buy", 0)
    b = a.get("buy", 0)
    h = a.get("hold", 0)
    s = a.get("sell", 0)
    ss = a.get("strong_sell", 0)
    if (sb + b) > (h + s + ss):
        score += 2
        signals.append(f"Analyst consensus bullish ({sb+b} buy vs {h+s+ss} hold/sell)")

    # Price below analyst mean target (≥15% upside required to filter noise)
    target_mean = a.get("target_mean")
    if price and target_mean and price < target_mean:
        upside = (target_mean - price) / price * 100
        if upside >= 15:
            score += 2
            signals.append(f"Price below analyst target ({upside:.1f}% upside)")

    # Revenue beat (last quarter)
    if hist and hist[0].get("surprise_pct") is not None and hist[0]["surprise_pct"] > 0:
        score += 1
        signals.append("Revenue beat last quarter")

    # Price below 52-week average
    if price and low_52w and high_52w:
        avg = (low_52w + high_52w) / 2
        if price < avg:
            score += 1
            signals.append(f"Price below 52-week average ({(price-avg)/avg*100:.1f}% below mid)")

    # Price above 200-day SMA (uptrend)
    sma200 = t.get("sma_200")
    if price and sma200 and price > sma200:
        score += 1
        signals.append("Price above 200-day SMA (uptrend)")

    # News sentiment bullish
    sentiment_score = sentiment.get("avg_sentiment_score")
    if sentiment_score is not None and sentiment_score > 0.15:
        score += 1
        signals.append(f"Bullish news sentiment ({sentiment_score:.2f})")

    # Insider buying
    insiders = snap.insider_transactions
    net_insider = sum((t.get("change") or 0) for t in insiders)
    if net_insider > 0:
        score += 1
        signals.append(f"Insider net buying ({net_insider:+,.0f} shares)")
    elif net_insider < -10000:
        score -= 1
        signals.append(f"Insider net selling ({net_insider:+,.0f} shares)")

    # ROIC > 15%
    roic = f.get("roic_annual")
    if roic is not None and roic > 0.15:
        score += 1
        signals.append(f"High ROIC ({roic*100:.1f}%)")

    # High debt penalty
    de = f.get("debt_to_equity")
    if de is not None and de > 2.0:
        score -= 1
        signals.append(f"High debt/equity ({de:.1f})")

    # Piotroski F-Score
    p_score, _ = _calculate_piotroski(snap)
    if p_score is not None:
        if p_score >= 7:
            score += 2
            signals.append(f"Piotroski F-Score: {p_score}/9 (Strong fundamentals)")
        elif p_score <= 3:
            score -= 1
            signals.append(f"Piotroski F-Score: {p_score}/9 (Weak fundamentals)")
        else:
            signals.append(f"Piotroski F-Score: {p_score}/9")

    return score, signals, p_score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def score_snapshots(snapshots: list[CompanySnapshot]) -> list[OpportunityScore]:
    """
    Score pre-built snapshots (no screener, no extra API calls).
    Used by the daily briefing to score watchlist companies that were already fetched.
    """
    results: list[OpportunityScore] = []

    async def _process(snap: CompanySnapshot):
        try:
            score, signals, p_score = _score_snapshot(snap)

            llm_eval = None
            if score >= 4:
                fv = _format_snapshot_for_briefing(snap, None)
                fv["score"] = score
                fv["signals_list"] = "\n".join(f"  + {s}" for s in signals)
                llm_eval = await llm_client.complete(
                    system_prompt=prompts.ANALYST_SYSTEM,
                    user_prompt=prompts.OPPORTUNITY_EVAL_USER.format(**fv),
                    max_tokens=65536,
                    temperature=0.3,
                )

            results.append(OpportunityScore(
                ticker=snap.ticker,
                name=snap.name or snap.ticker,
                score=score,
                signals=signals,
                piotroski_fscore=p_score,
                llm_evaluation=llm_eval,
                snapshot=snap,
            ))
        except Exception as e:
            log.warning("[scanner] Error scoring %s: %s", snap.ticker, e)

    await asyncio.gather(*[_process(s) for s in snapshots])
    return sorted(results, key=lambda x: x.score, reverse=True)


async def score_watchlist() -> list[OpportunityScore]:
    """Score all watchlist companies by building fresh snapshots. Applies hard screener."""
    companies = await database.get_companies_by_type("watchlist")
    if not companies:
        return []

    results: list[OpportunityScore] = []

    async def _process(company):
        try:
            snap = await build_snapshot(company.ticker, list_type="watchlist", include_sec=False)
            passes, reason = _passes_screener(snap)
            if not passes:
                log.debug("[scanner] %s failed screener: %s", company.ticker, reason)
                return

            score, signals, p_score = _score_snapshot(snap)

            llm_eval = None
            if score >= 4:
                fv = _format_snapshot_for_briefing(snap, None)
                fv["score"] = score
                fv["signals_list"] = "\n".join(f"  + {s}" for s in signals)
                llm_eval = await llm_client.complete(
                    system_prompt=prompts.ANALYST_SYSTEM,
                    user_prompt=prompts.OPPORTUNITY_EVAL_USER.format(**fv),
                    max_tokens=65536,
                    temperature=0.3,
                )

            results.append(OpportunityScore(
                ticker=company.ticker,
                name=company.name or company.ticker,
                score=score,
                signals=signals,
                piotroski_fscore=p_score,
                llm_evaluation=llm_eval,
                snapshot=snap,
            ))
        except Exception as e:
            log.warning("[scanner] Error scoring %s: %s", company.ticker, e)

    await asyncio.gather(*[_process(c) for c in companies])
    return sorted(results, key=lambda x: x.score, reverse=True)


async def suggest_new_tickers(portfolio_tickers: list[str], watchlist_tickers: list[str]) -> str:
    """Weekly: ask LLM to suggest new tickers based on portfolio themes."""
    if not portfolio_tickers:
        return "Add companies to your portfolio first with `/add TICKER portfolio`."

    user_prompt = prompts.OPPORTUNITY_SCAN_USER.format(
        portfolio_tickers=", ".join(portfolio_tickers),
        watchlist_tickers=", ".join(watchlist_tickers) if watchlist_tickers else "None",
    )
    return await llm_client.complete(
        system_prompt=prompts.ANALYST_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=65536,
        temperature=0.5,
    )
