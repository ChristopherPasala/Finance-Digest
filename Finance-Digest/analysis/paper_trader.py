"""Paper trading engine — daily buy/sell decisions based on opportunity scores."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any

from analysis import llm_client, prompts
from data import database
from data.models import OpportunityScore

log = logging.getLogger(__name__)

STARTING_CASH         = 10_000.0
MAX_POSITIONS         = 10
BUY_SCORE_THRESHOLD   = 8      # score >= 8/15
SELL_SCORE_THRESHOLD  = 3      # score <= 3/15
POSITION_SIZE_PCT     = 0.10   # 10% of total NAV per new position
STOP_LOSS_PCT         = 0.15   # auto-exit if down >= 15% from avg cost
MAX_SINGLE_TICKER_PCT = 0.20   # cap any ticker at 20% of NAV
MIN_TRADE_CASH        = 50.0   # minimum allocation to bother opening a position


# ---------------------------------------------------------------------------
# SPY benchmark helper
# ---------------------------------------------------------------------------

def _fetch_spy_sync(since_date: str) -> list[tuple[str, float]]:
    import yfinance as yf
    df = yf.Ticker("SPY").history(start=since_date, end=date.today().isoformat())
    if df.empty:
        return []
    df = df[["Close"]].dropna()
    return [(str(idx.date()), float(row["Close"])) for idx, row in df.iterrows()]


async def get_spy_history(since_date: str) -> list[tuple[str, float]]:
    """Fetch SPY daily Close prices from since_date to today."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_spy_sync, since_date)


# ---------------------------------------------------------------------------
# Price fallback for held tickers not in current scores
# ---------------------------------------------------------------------------

def _fetch_price_sync(ticker: str) -> float | None:
    try:
        import yfinance as yf
        return yf.Ticker(ticker).fast_info.last_price
    except Exception:
        return None


async def _fetch_price(ticker: str) -> float | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_price_sync, ticker)


# ---------------------------------------------------------------------------
# LLM buy-sizing
# ---------------------------------------------------------------------------

def _verdict_is_pass(llm_eval: str) -> bool:
    """Return True if the LLM's existing evaluation verdict is explicitly a pass."""
    # Look for the last VERDICT line and check for 'pass' (case-insensitive)
    match = re.search(r'VERDICT\s*:?\s*(.+)', llm_eval, re.IGNORECASE)
    if match:
        verdict_text = match.group(1).lower()
        return 'pass' in verdict_text and 'worth' not in verdict_text
    return False


async def _llm_buy_size(s: OpportunityScore, alloc: float, price: float) -> tuple[float, str]:
    """
    Ask the LLM how much of the standard allocation to deploy.
    Returns (size_multiplier, reason_string).
    Multipliers: 1.0 = full, 0.5 = half, 0.0 = skip.
    Falls back to 1.0 if LLM is unavailable.
    """
    if not s.llm_evaluation:
        return 1.0, "no prior analysis — defaulting to full size"

    # Pre-filter: if the existing verdict is already a pass, skip without a second call
    if _verdict_is_pass(s.llm_evaluation):
        return 0.0, "prior analysis verdict was Pass"

    try:
        prompt = prompts.PAPER_BUY_SIZE_USER.format(
            ticker=s.ticker,
            name=s.name or s.ticker,
            llm_evaluation=s.llm_evaluation,
            score=s.score,
            signals=", ".join(s.signals),
            price=f"{price:.2f}",
            alloc=alloc,
        )
        response = await llm_client.complete(
            system_prompt=prompts.ANALYST_SYSTEM,
            user_prompt=prompt,
            max_tokens=100,
            temperature=0.2,
        )
        size_match = re.search(r'SIZE\s*:\s*(FULL|HALF|SKIP)', response, re.IGNORECASE)
        reason_match = re.search(r'REASON\s*:\s*(.+)', response, re.IGNORECASE)
        reason = reason_match.group(1).strip() if reason_match else response.strip()[:120]
        if not size_match:
            log.warning("[paper] LLM sizing response unparseable for %s: %r", s.ticker, response[:80])
            return 1.0, "unparseable LLM response — defaulting to full size"
        decision = size_match.group(1).upper()
        mult = {"FULL": 1.0, "HALF": 0.5, "SKIP": 0.0}[decision]
        return mult, reason
    except Exception as e:
        log.warning("[paper] LLM sizing call failed for %s: %s", s.ticker, e)
        return 1.0, "LLM error — defaulting to full size"


# ---------------------------------------------------------------------------
# Core session
# ---------------------------------------------------------------------------

async def run_paper_trading_session(scores: list[OpportunityScore]) -> list[str]:
    """
    Run one daily paper trading cycle against a pre-scored list.
    Called from build_daily_briefing() with the same snapshots already fetched.
    Returns human-readable lines for the briefing PAPER PORTFOLIO section.
    """
    today = date.today().isoformat()
    lines: list[str] = []

    await database.paper_ensure_initialized()

    state = await database.paper_get_state()
    cash: float = state["cash"]
    positions: dict[str, float] = await database.paper_get_positions()   # {ticker: shares}
    entry_prices: dict[str, float] = await database.paper_get_entry_prices()  # {ticker: avg_cost}

    # Build price lookup from scores
    price_lookup: dict[str, float] = {}
    score_lookup: dict[str, int] = {}
    signals_lookup: dict[str, list[str]] = {}
    for s in scores:
        if s.snapshot and s.snapshot.quote.get("price"):
            price_lookup[s.ticker] = float(s.snapshot.quote["price"])
        score_lookup[s.ticker] = s.score
        signals_lookup[s.ticker] = s.signals

    # Fetch prices for held tickers not in current score run (e.g. removed from watchlist)
    missing = [t for t in positions if t not in price_lookup]
    if missing:
        fetched = await asyncio.gather(*[_fetch_price(t) for t in missing])
        for ticker, price in zip(missing, fetched):
            if price:
                price_lookup[ticker] = price

    def _nav() -> float:
        invested = sum(positions.get(t, 0) * price_lookup.get(t, 0) for t in positions)
        return cash + invested

    # --- Stop-loss pass ---
    for ticker in list(positions.keys()):
        if ticker not in price_lookup:
            continue
        avg_cost = entry_prices.get(ticker)
        if avg_cost and avg_cost > 0:
            change = price_lookup[ticker] / avg_cost - 1
            if change <= -STOP_LOSS_PCT:
                shares = positions[ticker]
                proceeds = shares * price_lookup[ticker]
                cash += proceeds
                await database.paper_record_trade(
                    ticker, "SELL", shares, price_lookup[ticker],
                    [f"Stop-loss triggered ({change*100:.1f}% loss)"], score_lookup.get(ticker, 0)
                )
                await database.paper_update_cash(cash)
                del positions[ticker]
                lines.append(
                    f"STOP-LOSS SELL {ticker}: {shares:.4f} shares @ ${price_lookup[ticker]:.2f} "
                    f"({change*100:.1f}%) — proceeds ${proceeds:.2f}"
                )
                log.info("[paper] Stop-loss sell %s @ %.2f (%.1f%%)", ticker, price_lookup[ticker], change * 100)

    # --- Sell pass ---
    for ticker in list(positions.keys()):
        if ticker not in score_lookup:
            continue
        if score_lookup[ticker] <= SELL_SCORE_THRESHOLD and ticker in price_lookup:
            shares = positions[ticker]
            proceeds = shares * price_lookup[ticker]
            avg_cost = entry_prices.get(ticker, price_lookup[ticker])
            pnl = proceeds - shares * avg_cost
            cash += proceeds
            await database.paper_record_trade(
                ticker, "SELL", shares, price_lookup[ticker],
                [f"Score dropped to {score_lookup[ticker]}/15"], score_lookup[ticker]
            )
            await database.paper_update_cash(cash)
            del positions[ticker]
            lines.append(
                f"SELL {ticker}: {shares:.4f} shares @ ${price_lookup[ticker]:.2f} "
                f"score={score_lookup[ticker]}/15 — P&L ${pnl:+.2f}"
            )
            log.info("[paper] Sell %s score=%d", ticker, score_lookup[ticker])

    # --- Buy pass ---
    total_nav = _nav()

    # Identify candidates and run LLM sizing decisions in parallel
    buy_candidates = [
        s for s in sorted(scores, key=lambda x: x.score, reverse=True)
        if s.ticker not in positions and s.score >= BUY_SCORE_THRESHOLD
    ]
    if buy_candidates:
        # Compute a representative alloc for each candidate (uses current NAV/cash)
        def _candidate_alloc(s: OpportunityScore) -> float:
            price = price_lookup.get(s.ticker, 0)
            if not price:
                return 0.0
            return min(
                total_nav * POSITION_SIZE_PCT,
                cash * 0.95,
                total_nav * MAX_SINGLE_TICKER_PCT,
            )

        sizing_results = await asyncio.gather(*[
            _llm_buy_size(s, _candidate_alloc(s), price_lookup.get(s.ticker, 0))
            for s in buy_candidates
        ])
        size_map: dict[str, tuple[float, str]] = {
            s.ticker: result for s, result in zip(buy_candidates, sizing_results)
        }
    else:
        size_map = {}

    for s in buy_candidates:
        if len(positions) >= MAX_POSITIONS:
            break
        price = price_lookup.get(s.ticker)
        if not price or price <= 0:
            continue

        size_mult, size_reason = size_map.get(s.ticker, (1.0, ""))

        if size_mult == 0.0:
            lines.append(f"SKIP {s.ticker}: score={s.score}/15 — LLM: {size_reason}")
            log.info("[paper] LLM skipped buy %s score=%d: %s", s.ticker, s.score, size_reason)
            continue

        base_alloc = min(
            total_nav * POSITION_SIZE_PCT,
            cash * 0.95,
            total_nav * MAX_SINGLE_TICKER_PCT,
        )
        alloc = base_alloc * size_mult
        if alloc < MIN_TRADE_CASH:
            continue

        shares = round(alloc / price, 4)
        cost = shares * price
        cash -= cost
        positions[s.ticker] = shares
        size_label = "full" if size_mult == 1.0 else f"{int(size_mult * 100)}%"
        await database.paper_record_trade(
            s.ticker, "BUY", shares, price,
            s.signals[:5] + ([f"LLM size: {size_label} — {size_reason}"] if size_reason else []),
            s.score
        )
        await database.paper_update_cash(cash)
        lines.append(
            f"BUY {s.ticker}: {shares:.4f} shares @ ${price:.2f} "
            f"score={s.score}/15 size={size_label} — ${cost:.2f} invested"
            + (f" | LLM: {size_reason}" if size_reason else "")
        )
        log.info("[paper] Buy %s %.4f shares @ %.2f score=%d size=%s", s.ticker, shares, price, s.score, size_label)
        total_nav = _nav()  # recompute after buy

    # --- End-of-day snapshot ---
    total_nav = _nav()
    invested = total_nav - cash

    await database.paper_record_daily_value(today, total_nav, cash, invested)

    # Build daily positions list (including CASH row)
    pos_rows: list[dict] = []
    for ticker, shares in positions.items():
        price = price_lookup.get(ticker, 0)
        pos_val = shares * price
        pos_rows.append({
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "position_value": pos_val,
            "weight_pct": (pos_val / total_nav * 100) if total_nav > 0 else 0,
        })
    pos_rows.append({
        "ticker": "CASH",
        "shares": 0,
        "price": 1.0,
        "position_value": cash,
        "weight_pct": (cash / total_nav * 100) if total_nav > 0 else 100,
    })
    await database.paper_record_daily_positions(today, pos_rows)

    # Summary header
    inception = state.get("inception_at", today)
    total_return = (total_nav / STARTING_CASH - 1) * 100
    summary_lines: list[str] = [
        f"Portfolio value: ${total_nav:,.2f} ({total_return:+.1f}% since {inception})",
        f"Cash: ${cash:,.2f} ({cash/total_nav*100:.0f}% of NAV)  |  Invested: ${invested:,.2f}",
    ]
    if positions:
        holdings = []
        for ticker, shares in sorted(positions.items()):
            price = price_lookup.get(ticker, 0)
            avg_cost = entry_prices.get(ticker, price)
            pnl_pct = (price / avg_cost - 1) * 100 if avg_cost else 0
            holdings.append(f"{ticker} {shares:.2f}sh @ ${price:.2f} ({pnl_pct:+.1f}%)")
        summary_lines.append("Holdings: " + "  |  ".join(holdings))
    else:
        summary_lines.append("No open positions.")

    if lines:
        summary_lines.append("Today's trades:")
        summary_lines.extend(f"  {line}" for line in lines)
    else:
        summary_lines.append("No trades today.")

    return summary_lines
