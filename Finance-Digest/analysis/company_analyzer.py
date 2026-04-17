"""Company deep-dive analysis following the 6-step research framework."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from analysis import llm_client, prompts
from collectors.aggregator import build_snapshot
from data import database
from data.models import CompanySnapshot, InvestmentThesis

log = logging.getLogger(__name__)


def _strip_llm_echo(text: str, label: str) -> str:
    """
    Strip the first line of an LLM response if it echoes the step label back.
    The LLM inconsistently prepends lines like:
      '## Business Understanding', '**Step 2 — Business Understanding**',
      'Financial Analysis for AAPL', 'Step 3 — Financial Analysis', etc.
    We own the headers — we just want the content body.
    If the first line does not look like an echo, the full text is returned unchanged.
    """
    import re
    lines = text.lstrip("\n").split("\n", 1)
    first = re.sub(r"[#*\-_]+", "", lines[0]).strip().lower()
    if label.lower() in first or (first.startswith("step") and label.lower() in first):
        return lines[1].lstrip("\n") if len(lines) > 1 else ""
    return text


def _fmt(val: Any, suffix: str = "", fallback: str = "[UNAVAILABLE]", decimals: int = 2) -> str:
    if val is None:
        return fallback
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def _pct(val: Any) -> str:
    return _fmt(val, suffix="%") if val is not None else "[UNAVAILABLE]"


def _news_bullets(news: list[dict], limit: int = 8) -> str:
    if not news:
        return "• No recent news found"
    lines = []
    for a in news[:limit]:
        date = a.get("published_at", "")
        title = a.get("title", "")
        source = a.get("source", "")
        lines.append(f"• [{date}] {title} ({source})")
    return "\n".join(lines)


def _fmt_value(v: float) -> str:
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def _insider_summary(transactions: list[dict]) -> str:
    if not transactions:
        return "[UNAVAILABLE]"
    # finviz format: {owner, relationship, date, transaction, shares, value}
    if transactions and 'owner' in transactions[0]:
        lines = []
        for t in transactions[:5]:
            val_str = _fmt_value(t.get('value', 0)) if t.get('value') else ""
            val_part = f" ({val_str})" if val_str else ""
            lines.append(
                f"• {t.get('owner', '')} ({t.get('relationship', '')}) — "
                f"{t.get('transaction', '')} {t.get('shares', 0):,} shares"
                f"{val_part} on {t.get('date', '')}"
            )
        return "\n".join(lines)
    # Finnhub format: {change, ...}
    buys = sum(1 for t in transactions if (t.get("change") or 0) > 0)
    sells = sum(1 for t in transactions if (t.get("change") or 0) < 0)
    net = sum((t.get("change") or 0) for t in transactions)
    direction = "net BUYING" if net > 0 else "net SELLING" if net < 0 else "neutral"
    return f"{buys} buys, {sells} sells in last 90 days — {direction} ({net:+,.0f} shares)"


def _format_peer_table(peers: list[dict]) -> str:
    if not peers:
        return "[Peer comparison data not available]"

    def fv(v):
        return f"{v:.1f}" if v is not None else "N/A"

    def fp(v):
        return f"{v:.1f}%" if v is not None else "N/A"

    rows = ["Ticker  | P/E   | P/S   | P/B   | ROI    | Gross Margin | Mkt Cap",
            "--------|-------|-------|-------|--------|--------------|--------"]
    for p in peers:
        rows.append(
            f"{p['ticker']:<8}| {fv(p.get('pe')):<6}| {fv(p.get('ps')):<6}| "
            f"{fv(p.get('pb')):<6}| {fp(p.get('roi')):<7}| {fp(p.get('gross_margin')):<13}| "
            f"{p.get('market_cap', 'N/A')}"
        )
    return "\n".join(rows)


def _fmt_money_trend(d: dict, label: str = "") -> str:
    """Format a year→dollar dict as 'YYYY: $X.XB | ...' handling negative (net cash)."""
    if not d:
        return "[UNAVAILABLE]"
    parts = []
    for yr in sorted(d.keys(), reverse=True):
        val = d[yr]
        sign = "-" if val < 0 else ""
        abs_val = abs(val)
        if abs_val >= 1e9:
            parts.append(f"{yr}: {sign}${abs_val/1e9:.2f}B")
        elif abs_val >= 1e6:
            parts.append(f"{yr}: {sign}${abs_val/1e6:.1f}M")
        else:
            parts.append(f"{yr}: {sign}${abs_val:,.0f}")
    return " | ".join(parts)


def _fmt_ratio_trend(d: dict) -> str:
    if not d:
        return "[UNAVAILABLE]"
    return " | ".join(f"{yr}: {v:.2f}x" for yr, v in sorted(d.items(), reverse=True))


def _fmt_pct_trend(d: dict) -> str:
    if not d:
        return "[UNAVAILABLE]"
    return " | ".join(f"{yr}: {v:.1f}%" for yr, v in sorted(d.items(), reverse=True))


def _fmt_shares_trend(d: dict) -> str:
    if not d:
        return "[UNAVAILABLE]"
    parts = []
    for yr in sorted(d.keys(), reverse=True):
        v = d[yr]
        if v >= 1e9:
            parts.append(f"{yr}: {v/1e9:.2f}B")
        else:
            parts.append(f"{yr}: {v/1e6:.0f}M")
    return " | ".join(parts)


def _format_capex_history(history: dict) -> str:
    if not history:
        return "[UNAVAILABLE]"
    parts = []
    for year in sorted(history.keys(), reverse=True):
        val = history[year]
        if val >= 1e9:
            parts.append(f"{year}: ${val/1e9:.2f}B")
        elif val >= 1e6:
            parts.append(f"{year}: ${val/1e6:.1f}M")
        else:
            parts.append(f"{year}: ${val:,.0f}")
    return " | ".join(parts)


def _format_capex_pct(pct_rev: dict) -> str:
    if not pct_rev:
        return "[UNAVAILABLE]"
    parts = [f"{yr}: {pct:.1f}%" for yr, pct in sorted(pct_rev.items(), reverse=True)]
    return " | ".join(parts)


def _format_snapshot_for_briefing(snap: CompanySnapshot, thesis: InvestmentThesis | None) -> dict:
    q = snap.quote
    t = snap.technicals
    f = snap.financials
    e = snap.earnings
    a = snap.analyst_targets
    cagr = snap.cagr
    rets = snap.returns

    hist = e.get("history", [])
    last_q = hist[0] if hist else {}
    eps_actual = _fmt(last_q.get("actual_eps"))
    eps_estimate = _fmt(last_q.get("estimate_eps"))
    eps_surprise = _pct(last_q.get("surprise_pct"))

    price = q.get("price")
    target_mean = a.get("target_mean")
    target_upside = None
    if price and target_mean and price > 0:
        target_upside = round((target_mean - price) / price * 100, 2)

    low_52w = q.get("52w_low")
    high_52w = q.get("52w_high")
    avg_52w = None
    if low_52w and high_52w:
        avg_52w = (low_52w + high_52w) / 2

    vs_52w_avg = None
    if price and avg_52w and avg_52w > 0:
        vs_52w_avg = round((price - avg_52w) / avg_52w * 100, 2)

    fcf = f.get("free_cashflow")
    market_cap = q.get("market_cap")
    fcf_yield = None
    if fcf and market_cap and market_cap > 0:
        fcf_yield = round(fcf / market_cap * 100, 2)

    return {
        "ticker": snap.ticker,
        "name": snap.name,
        "list_type": snap.list_type,
        "price": _fmt(price, "$"),
        "change_pct": _pct(q.get("change_pct")),
        "change_1w_pct": _pct(q.get("change_1w_pct")),
        "low_52w": _fmt(low_52w, "$"),
        "high_52w": _fmt(high_52w, "$"),
        "rsi": _fmt(t.get("rsi_14")),
        "sma50": _fmt(t.get("sma_50"), "$"),
        "sma200": _fmt(t.get("sma_200"), "$"),
        "macd_signal": "Bullish" if t.get("macd_bullish") else "Bearish",
        "pe": _fmt(f.get("pe_ratio") or f.get("pe_ttm")),
        "fwd_pe": _fmt(f.get("forward_pe")),
        "eps": _fmt(f.get("eps") or f.get("eps_ttm")),
        "rev_growth": _pct(f.get("revenue_growth")),
        "rev_cagr_5y": _pct(cagr.get("revenue_cagr_5y")),
        "rev_cagr_10y": _pct(cagr.get("revenue_cagr_10y")),
        "eps_cagr_5y": _pct(cagr.get("eps_cagr_5y")),
        "eps_cagr_10y": _pct(cagr.get("eps_cagr_10y")),
        "op_cagr_5y": _pct(cagr.get("operating_income_cagr_5y")),
        "gross_margin": _pct(f.get("gross_margins") or f.get("gross_margin_annual")),
        "op_margin": _pct(f.get("operating_margins")),
        "net_margin": _pct(f.get("profit_margins") or f.get("net_margin_annual")),
        "debt_equity": _fmt(f.get("debt_to_equity")),
        "current_ratio": _fmt(f.get("current_ratio")),
        "roe_5y": _pct(rets.get("roe_avg_5y")),
        "roic": _pct(f.get("roic_annual")),
        "roa": _pct(f.get("return_on_assets")),
        "fcf": _fmt(fcf),
        "market_cap": _fmt(market_cap),
        "fcf_yield": _pct(fcf_yield),
        "price_to_book": _fmt(f.get("price_to_book")),
        "ev_ebitda": _fmt(f.get("ev_to_ebitda")),
        "price_to_sales": _fmt(f.get("price_to_sales")),
        "next_earnings_date": e.get("next_date", "[UNAVAILABLE]"),
        "next_eps_est": _fmt(e.get("next_eps_estimate")),
        "eps_actual": eps_actual,
        "eps_estimate": eps_estimate,
        "eps_surprise": eps_surprise,
        "strong_buy": a.get("strong_buy", 0),
        "buy": a.get("buy", 0),
        "hold": a.get("hold", 0),
        "sell": a.get("sell", 0),
        "target_mean": _fmt(target_mean, "$"),
        "target_high": _fmt(a.get("target_high"), "$"),
        "target_low": _fmt(a.get("target_low"), "$"),
        "target_upside": _pct(target_upside),
        "vs_52w_avg": _pct(vs_52w_avg),
        "recommendation": f.get("recommendation") or "[UNAVAILABLE]",
        "insider_summary": _insider_summary(snap.insider_transactions),
        "insider_signal": _insider_summary(snap.insider_transactions),
        "news_bullets": _news_bullets(snap.news),
        "thesis_block": thesis.to_prompt_block() if thesis else "[No thesis recorded — use /thesis to add one]",
        "thesis_rationale": thesis.entry_rationale if thesis else "[UNAVAILABLE]",
        "sec_excerpt": (snap.sec_summary or "[UNAVAILABLE]")[:1500],
        "description": f.get("description", "[UNAVAILABLE]"),
        "sector": f.get("sector", "[UNAVAILABLE]"),
        "industry": f.get("industry", "[UNAVAILABLE]"),
        "strategy_excerpt": (snap.strategy_excerpt or snap.sec_summary or "[UNAVAILABLE]")[:1200],
        "capex_history": _format_capex_history(snap.capex.get("history", {})),
        "capex_pct_rev": _format_capex_pct(snap.capex.get("pct_rev", {})),
        "roic_history": (f"Current ROI: {_pct(f.get('roic'))}" if f.get("roic") else "[UNAVAILABLE]"),
        # Financial health metrics
        "fcf_trend":          _fmt_money_trend(snap.financial_health.get("fcf_trend", {})),
        "cash_conversion":    _fmt_ratio_trend(snap.financial_health.get("cash_conversion", {})),
        "net_debt_trend":     _fmt_money_trend(snap.financial_health.get("net_debt_trend", {})),
        "interest_coverage":  _fmt_ratio_trend(snap.financial_health.get("interest_coverage", {})),
        "shares_trend":       _fmt_shares_trend(snap.financial_health.get("shares_trend", {})),
        "buyback_trend":      _fmt_money_trend(snap.financial_health.get("buyback_trend", {})),
        "rd_pct_rev":         _fmt_pct_trend(snap.financial_health.get("rd_pct_rev", {})),
        "sga_pct_rev":        _fmt_pct_trend(snap.financial_health.get("sga_pct_rev", {})),
        "goodwill_pct":       _fmt_pct_trend(snap.financial_health.get("goodwill_pct_assets", {})),
        "working_capital":    _fmt_money_trend(snap.financial_health.get("working_capital", {})),
        "strategic_news": _news_bullets(snap.news, limit=4),
        "gaap_vs_adj": "[Check 10-K for reconciliation]",
        "peer_table": _format_peer_table(snap.peers),
        "peer_valuation_table": _format_peer_table(snap.peers),
        "signals_list": "",
        "score": 0,
        "sentiment_desc": _describe_sentiment(snap.sentiment),
    }


def _describe_sentiment(sentiment: dict) -> str:
    score = sentiment.get("avg_sentiment_score")
    if score is None:
        return "[UNAVAILABLE]"
    if score > 0.2:
        return f"Bullish (score: {score:.2f})"
    elif score < -0.2:
        return f"Bearish (score: {score:.2f})"
    return f"Neutral (score: {score:.2f})"


async def run_portfolio_briefing_section(snap: CompanySnapshot) -> str:
    """Generate the morning briefing section for one portfolio company."""
    thesis = await database.get_thesis(snap.ticker)
    fv = _format_snapshot_for_briefing(snap, thesis)
    user_prompt = prompts.PORTFOLIO_BRIEFING_USER.format(**fv)
    return await llm_client.complete(
        system_prompt=prompts.PORTFOLIO_BRIEFING,
        user_prompt=user_prompt,
        max_tokens=65536,
        temperature=0.3,
    )


async def run_watchlist_brief(snap: CompanySnapshot) -> str:
    """Generate a short watchlist section."""
    thesis = await database.get_thesis(snap.ticker)
    fv = _format_snapshot_for_briefing(snap, thesis)
    user_prompt = prompts.WATCHLIST_BRIEF_USER.format(**fv)
    return await llm_client.complete(
        system_prompt=prompts.ANALYST_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=65536,
        temperature=0.3,
    )


async def run_deep_dive(ticker: str) -> list[str]:
    """Full 6-step analysis for /analyze command. Returns list of text sections."""
    import time
    ticker = ticker.upper()
    t_total = time.perf_counter()
    log.info("[%s] Starting 6-step deep dive", ticker)

    snap = await build_snapshot(ticker, include_sec=True)
    if not snap.has_data():
        return [f"Could not fetch data for **{ticker}**. Verify the ticker is valid."]

    company = await database.get_company(ticker)
    list_type = company.list_type if company else "untracked"
    snap.list_type = list_type

    thesis = await database.get_thesis(ticker)
    fv = _format_snapshot_for_briefing(snap, thesis)

    sections: list[str] = []
    errors_note = ""
    if snap.errors:
        errors_note = f"\n⚠️ Data gaps: {', '.join(snap.errors[:3])}"

    sections.append(
        f"**Deep Dive: {snap.name} ({ticker})**{errors_note}\n"
        f"Price: {fv['price']} | P/E: {fv['pe']} | Sector: {fv['sector']}"
    )

    async def _llm_step(step_num: int, label: str, system, user, max_tokens, temperature=0.3) -> str:
        log.info("[%s] Step %d/6 — %s: calling LLM...", ticker, step_num, label)
        t = time.perf_counter()
        result = await llm_client.complete(system_prompt=system, user_prompt=user,
                                           max_tokens=max_tokens, temperature=temperature)
        log.info("[%s] Step %d/6 — %s: done (%.1fs)", ticker, step_num, label, time.perf_counter() - t)
        return result

    # Steps 2–5 are fully independent — run in parallel, pipeline through the LLM semaphore
    log.info("[%s] Steps 2-5: launching in parallel", ticker)
    biz, fin, strat, val = await asyncio.gather(
        _llm_step(2, "Business Understanding", prompts.ANALYST_SYSTEM,
                  prompts.BUSINESS_UNDERSTANDING_USER.format(**fv), 65536),
        _llm_step(3, "Financial Analysis", prompts.ANALYST_SYSTEM,
                  prompts.FINANCIAL_ANALYSIS_USER.format(**fv), 65536),
        _llm_step(4, "Strategy Assessment", prompts.ANALYST_SYSTEM,
                  prompts.STRATEGY_ASSESSMENT_USER.format(**fv), 65536),
        _llm_step(5, "Valuation", prompts.ANALYST_SYSTEM,
                  prompts.VALUATION_USER.format(**fv), 65536),
    )
    sections.append(f"## Business Understanding\n\n{_strip_llm_echo(biz, 'Business Understanding')}")
    sections.append(f"## Financial Analysis\n\n{_strip_llm_echo(fin, 'Financial Analysis')}")
    sections.append(f"## Strategy Assessment\n\n{_strip_llm_echo(strat, 'Strategy Assessment')}")
    sections.append(f"## Valuation\n\n{_strip_llm_echo(val, 'Valuation')}")

    if thesis:
        tc = await _llm_step(6, "Thesis Check", prompts.ANALYST_SYSTEM,
                             prompts.THESIS_CHECK_USER.format(**fv), 32000, temperature=0.2)
        sections.append(f"## Thesis Check\n\n{_strip_llm_echo(tc, 'Thesis Check')}")
    else:
        log.info("[%s] Step 6 — Thesis Check: skipped (no thesis stored)", ticker)

    log.info("[%s] Deep dive complete in %.1fs", ticker, time.perf_counter() - t_total)
    return sections
