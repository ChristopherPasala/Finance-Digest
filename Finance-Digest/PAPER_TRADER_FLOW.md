# Paper Trader — Flow Breakdown

The paper trading system simulates a $10,000 portfolio using real market data and the same opportunity scores that power the daily briefing. No real money is involved.

---

## How It Fits Together

There are three distinct flows:

| Flow | Trigger | Purpose |
|------|---------|---------|
| **Daily trading session** | Runs automatically inside the morning briefing | Makes buy/sell decisions based on scored watchlist |
| **Daily portfolio snapshot** | Also runs inside the morning briefing (after trading) | Writes `portfolio.html` with current holdings and NAV history |
| **`/paper` command** | User runs `/paper` in Discord | Returns the URL to the portfolio page |

---

## Flow 1 — Daily Trading Session

### Trigger

Called from `run_morning_briefing()` inside the morning briefing scheduler. It receives the same `list[OpportunityScore]` already computed for the briefing — no extra API calls.

**File**: [analysis/paper_trader.py](analysis/paper_trader.py)
**Function**: `run_paper_trading_session(scores: list[OpportunityScore]) -> list[str]`

### Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `STARTING_CASH` | $10,000 | Initial portfolio value |
| `MAX_POSITIONS` | 10 | Hard cap on concurrent holdings |
| `BUY_SCORE_THRESHOLD` | 8 / 15 | Minimum rolling score to open a position (rebalance day only) |
| `SELL_SCORE_THRESHOLD` | 3 / 15 | Rolling avg score ≤ 3 → full exit on rebalance day |
| `TRIM_SCORE_THRESHOLD` | 6 / 15 | Rolling avg score 4–6 → trim to 50% on rebalance day |
| `POSITION_SIZE_PCT` | 10% | Target allocation per new position (% of NAV) |
| `STOP_LOSS_PCT` | 15% | Trailing stop: exit if down ≥ 15% from position high-water mark (daily) |
| `MAX_SINGLE_TICKER_PCT` | 20% | No single ticker can exceed 20% of NAV |
| `MIN_TRADE_CASH` | $50 | Minimum allocation to bother opening or trimming a position |
| `REBALANCE_INTERVAL_DAYS` | 14 (env) | Days between rebalances — set via `REBALANCE_INTERVAL_DAYS` in `.env` |

### Step-by-Step

#### 1. Load State

```
paper_get_state()        → cash balance, inception date
paper_get_positions()    → {ticker: shares}  (derived from trade history)
paper_get_entry_prices() → {ticker: weighted avg cost}
```

#### 2. Build Price & Score Lookups

- Prices are pulled from the `CompanySnapshot` objects already inside each `OpportunityScore`
- For any held ticker not in the current score run (e.g. removed from watchlist), a fresh price is fetched live from yfinance

#### 3. Stop-Loss Pass

For every open position:

```
if (current_price / avg_cost - 1) <= -0.15:
    SELL all shares at current price
    record trade (reason: "Stop-loss triggered")
    update cash balance
```

This runs before the regular sell pass so a stop-loss always takes priority.

#### 4. Sell Pass

For every open position that is present in the current score run:

```
if score <= 3:
    SELL all shares at current price
    record trade (reason: "Score dropped to X/15")
    update cash balance
```

#### 5. Buy Pass

All candidates with score ≥ 8 that aren't already held are collected first. LLM sizing decisions are then fetched **in parallel** for every candidate before any trades are placed.

**LLM sizing logic** (`_llm_buy_size`):

```
if llm_evaluation is None:
    → FULL (no analysis available, default to full size)

if llm_evaluation verdict contains "Pass":
    → SKIP (no second LLM call needed)

else:
    → Send focused sizing prompt to Ollama:
      "FULL / HALF / SKIP — one sentence reason"
      FULL  = 1.0×  (conviction is high)
      HALF  = 0.5×  (concerns exist but opportunity outweighs risk)
      SKIP  = 0.0   (risks outweigh opportunity)
    → Falls back to FULL if Ollama is unavailable or response unparseable
```

Then for each candidate in score order:

```
if positions >= MAX_POSITIONS → stop

size_mult, reason = size_map[ticker]   # from parallel LLM pre-pass

if size_mult == 0.0:
    log "SKIP {ticker} — LLM: {reason}"
    continue

alloc = min(NAV × 10%, cash × 95%, NAV × 20%) × size_mult

if alloc < $50 → skip

shares = alloc / price
BUY shares, deduct from cash, record trade (signals include LLM size + reason)
```

NAV is recomputed after each buy to account for the updated cash balance.

#### 6. End-of-Day Snapshot

Regardless of whether any trades occurred:

```
paper_record_daily_value(today, total_nav, cash, invested)
paper_record_daily_positions(today, [
    {ticker, shares, price, position_value, weight_pct},
    ...,
    {ticker: "CASH", position_value: cash, weight_pct: cash%},
])
```

This is what powers the portfolio page charts.

#### 7. Return

Returns a `list[str]` of human-readable lines (trades made, holdings summary) that get appended to the morning briefing message.

---

## Flow 2 — Daily Portfolio Page

Runs immediately after the daily trading session, still inside `run_morning_briefing()`.

**File**: [bot/tasks/morning_briefing.py](bot/tasks/morning_briefing.py)
**Function**: `run_morning_briefing()`

### Steps

1. Load today's positions, daily NAV history, recent trades, and entry prices from the DB
2. Call `build_portfolio_page_html(portfolio_data, updated_at=date_str)` → dark-themed HTML page
3. Write to `site-generator/public/portfolio.html` via `web_server.save_portfolio_page()`
4. Include the URL in the morning briefing Discord message alongside the briefing link

The portfolio page shows:
- Current NAV and cash/invested split
- Open positions with entry price and current weight
- Full NAV history chart (line chart vs SPY)
- Recent trade log

---

## Flow 3 — `/paper` Command

**File**: [bot/commands/paper.py](bot/commands/paper.py)

Triggered manually by the user. Simply returns the URL to the portfolio page.

```
/paper
  └─ portfolio_page_url(config.scan_report_base_url)
       └─ https://plebdigest.xyz/portfolio.html
```

The page is always the most recent version written by the daily briefing. If the portfolio page doesn't exist yet (first run before any briefing), the URL will 404 until the next briefing runs. Use `/briefing Weekly portfolio deep dive` to generate it on demand.

---

## How the LLM Feeds the Trader

The paper trader uses the LLM in two ways:

1. **Existing evaluation** (`OpportunityScore.llm_evaluation`) — generated during the scoring phase for any stock with score ≥ 4. The buy pass checks the VERDICT line: if it says "Pass", the stock is skipped without an additional LLM call.

2. **Buy-sizing call** — for candidates that pass the verdict check, a focused prompt (`PAPER_BUY_SIZE_USER`) asks Ollama to choose `FULL / HALF / SKIP` with a one-sentence reason. All sizing calls run in parallel to avoid adding latency per ticker.

**What appears in the briefing output:**
```
SKIP CMCSA: score=8/15 — LLM: prior analysis verdict was Pass
BUY NVDA: 0.0412 shares @ $890.00 score=10/15 size=full — $36.70 invested | LLM: Strong earnings momentum supports full allocation
BUY AMD: 0.0210 shares @ $142.00 score=9/15 size=50% — $14.91 invested | LLM: Upside is real but high debt warrants a smaller position
```

---

## How Scores Feed the Trader

The paper trader does not score stocks itself — it consumes scores produced by the opportunity scanner.

```
opportunity_scanner.score_snapshots(snapshots)
    │
    ├─ _score_snapshot()  →  score (0–15), signals[], piotroski_fscore
    │       ├─ RSI < 30 + price near/above 200d SMA (≥95%)  +2  (mean-reversion setup)
    │       ├─ RSI < 30 + price well below 200d SMA          +1  (possible falling knife)
    │       ├─ Earnings beat >5%                             +2  (miss >5% = -2)
    │       ├─ Analyst consensus bullish                     +2
    │       ├─ Below analyst target (≥15% upside required)   +2
    │       ├─ Revenue beat                                   +1
    │       ├─ Below 52w average                              +1
    │       ├─ Above 200d SMA (uptrend)                       +1
    │       ├─ Bullish sentiment                              +1
    │       ├─ Insider net buying                             +1  (heavy selling = -1)
    │       ├─ ROIC > 15%                                     +1
    │       ├─ High D/E > 2.0                                -1
    │       └─ Piotroski F-Score ≥ 7                         +2  (≤ 3 = -1, 4–6 = neutral)
    │
    └─ OpportunityScore(ticker, score, signals, piotroski_fscore, snapshot)
            │
            ├─ persisted daily to paper_score_history table
            │
            ▼
    run_paper_trading_session(scores)
            │
            ├─ STOP-LOSS PASS (every day — trailing stop from position high-water mark)
            │       └─ drawdown ≥ 15% from high → SELL full position
            │
            ├─ REBALANCE GATE: days since last rebalance < REBALANCE_INTERVAL_DAYS?
            │       └─ yes → skip buy/sell/trim, log "Next rebalance in N days"
            │
            └─ REBALANCE DAY (rolling avg score over interval period):
                    ├─ rolling avg ≤ 3  →  SELL full position
                    ├─ rolling avg 4–6  →  TRIM to 50%
                    └─ rolling avg ≥ 8  →  BUY (LLM sizing: FULL/HALF/SKIP)
```

---

## Full Data Flow Diagram

```
Morning briefing scheduler
    │
    ├─ score_snapshots(snapshots) → list[OpportunityScore]
    │
    ▼
run_paper_trading_session(scores)          [analysis/paper_trader.py]
    │
    ├─ paper_get_state()                   [data/database.py]
    ├─ paper_get_positions()
    ├─ paper_get_entry_prices()
    │
    ├─ build price_lookup from snapshots
    ├─ fetch missing prices via yfinance    (for de-listed / removed tickers)
    │
    ├─ STOP-LOSS PASS
    │       └─ down ≥ 15% → SELL → paper_record_trade() + paper_update_cash()
    │
    ├─ SELL PASS
    │       └─ score ≤ 3 → SELL → paper_record_trade() + paper_update_cash()
    │
    ├─ BUY PASS (sorted by score desc)
    │       ├─ collect all candidates (score ≥ 8, not held)
    │       ├─ asyncio.gather → _llm_buy_size() for each candidate in parallel
    │       │       ├─ verdict=Pass in existing eval  → SKIP (0.0×)
    │       │       ├─ Ollama sizing call              → FULL (1.0×) | HALF (0.5×) | SKIP (0.0×)
    │       │       └─ Ollama unavailable              → FULL fallback
    │       └─ for each candidate: apply size_mult → BUY → paper_record_trade() + paper_update_cash()
    │
    ├─ paper_record_daily_value()          [SQLite: paper_daily_value]
    ├─ paper_record_daily_positions()      [SQLite: paper_daily_positions]
    │
    └─ return summary lines → appended to briefing message


Morning briefing (continued, after trading session)
    │
    ├─ paper_get_state()                   [data/database.py]
    ├─ paper_get_entry_prices()
    ├─ paper_get_daily_values()
    ├─ paper_get_all_trades()
    ├─ paper_get_daily_positions(since_date=today)
    │
    ├─ build_portfolio_page_html()         [formatters/html_formatter.py]
    │       └─ dark-themed page with holdings, NAV chart, trade log
    │
    ├─ web_server.save_portfolio_page()    → site-generator/public/portfolio.html
    │
    └─ channel.send(briefing_url + portfolio_url)


/paper command
    │
    └─ portfolio_page_url(base_url)        → https://plebdigest.xyz/portfolio.html
```

---

## Weekly Portfolio Deep Dive

In addition to the daily session, there is a separate weekly briefing every Monday.

**File**: [bot/tasks/morning_briefing.py](bot/tasks/morning_briefing.py)
**Function**: `run_portfolio_briefing()`
**Discord trigger**: `/briefing Weekly portfolio deep dive`

This runs a deeper per-company analysis (`build_portfolio_briefing()`) on every company in your portfolio list and publishes it as a dated briefing article at `briefing-portfolio-{date}.html`. It is separate from the portfolio dashboard page.

---

## Relevant Files

| File | Role |
|------|------|
| [analysis/paper_trader.py](analysis/paper_trader.py) | Core trading engine — buy/sell logic, LLM sizing, stop-loss, daily snapshot |
| [bot/commands/paper.py](bot/commands/paper.py) | `/paper` command — returns portfolio page URL |
| [bot/tasks/morning_briefing.py](bot/tasks/morning_briefing.py) | Orchestrates trading session + portfolio page build |
| [analysis/opportunity_scanner.py](analysis/opportunity_scanner.py) | Scores each ticker (0–15, incl. Piotroski F-Score) and generates `llm_evaluation`; paper trader consumes both |
| [analysis/prompts.py](analysis/prompts.py) | `PAPER_BUY_SIZE_USER` — focused buy-sizing prompt (FULL/HALF/SKIP) |
| [formatters/html_formatter.py](formatters/html_formatter.py) | `build_portfolio_page_html()` — dark-themed portfolio dashboard |
| [web/server.py](web/server.py) | `save_portfolio_page()` — writes to `site-generator/public/portfolio.html` |
| [data/database.py](data/database.py) | All paper trading DB reads/writes |

## Relevant DB Tables

| Table | Purpose |
|-------|---------|
| `paper_portfolio_state` | Singleton cash balance, inception date, and `last_rebalance_at` |
| `paper_trades` | Full BUY/SELL/TRIM history — current positions derived from this |
| `paper_daily_value` | Daily NAV snapshots for the performance chart |
| `paper_daily_positions` | Daily per-ticker prices and weights (also source for trailing stop high-water mark) |
| `paper_score_history` | Daily opportunity scores per ticker — rolling average used on rebalance day |
