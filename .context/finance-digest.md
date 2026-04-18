# Finance-Digest

**Python 3.12 Discord bot** for AI-powered stock analysis and portfolio management.

## Tech Stack

| Layer | Tool |
|-------|------|
| Discord | discord.py + app_commands (slash commands) |
| LLM | Ollama (local GPU, OpenAI-compatible API) |
| Default model | qwen2.5:7b (configurable via `OLLAMA_MODEL`) |
| Scheduling | APScheduler |
| Database | SQLite + WAL mode (better-sqlite3 compat) |
| HTTP clients | aiohttp, httpx (async) |
| Data | yfinance, finnhub-python, finviz, alpha-vantage |
| PDF | fpdf2 |

## Directory Map

```
Finance-Digest/
├── run.py                        # Entry point — startup validation + bot.start()
├── bot/
│   ├── client.py                 # FinanceBot class, command registration, scheduler setup
│   └── commands/
│       ├── analyze.py            # /analyze TICKER — triggers 6-step deep dive
│       ├── portfolio.py          # /add, /remove, /list
│       ├── opportunities.py      # /opportunities — scores watchlist
│       ├── scan.py               # /screen — market universe scan
│       ├── briefing.py           # /briefing — manual trigger
│       ├── thesis.py             # /thesis — investment thesis CRUD
│       └── paper.py              # /paper — paper trading dashboard link
├── analysis/
│   ├── company_analyzer.py       # Orchestrates 6-step LLM analysis
│   ├── llm_client.py             # Async Ollama client (timeout + retry)
│   ├── prompts.py                # All LLM system + user prompts (6 steps)
│   ├── paper_trader.py           # Paper trading simulator ($10k, score-driven)
│   ├── briefing_builder.py       # Composes Discord briefing embeds
│   ├── market_scanner.py         # Finnhub universe screen + LLM gate
│   └── opportunity_scanner.py    # Opportunity scoring engine (15-point scale, incl. Piotroski F-Score)
├── collectors/
│   ├── aggregator.py             # Runs 16+ collectors concurrently (asyncio.gather)
│   ├── base.py                   # Base collector class + safe() wrapper
│   ├── yfinance_collector.py     # quote, technicals, financials, CAGR, returns, CapEx, FCF, health
│   ├── finnhub_collector.py      # earnings, analysts, news, insider, basic financials
│   ├── finviz_collector.py       # fundamentals + peer comparison
│   ├── alphavantage_collector.py # news sentiment
│   └── sec_edgar_collector.py   # 10-K MD&A extraction
├── data/
│   ├── database.py               # SQLite layer — all queries, upserts, cache management
│   └── models.py                 # Dataclasses: Company, InvestmentThesis, CompanySnapshot, OpportunityScore
├── formatters/
│   ├── html_formatter.py         # Markdown → HTML with glossary auto-links
│   ├── pdf_formatter.py          # Markdown → PDF (fpdf2)
│   ├── discord_formatter.py      # Python dicts → Discord embeds
│   └── chart_formatter.py        # Chart generation (matplotlib)
├── utils/
│   ├── config.py                 # Loads .env, exposes typed config object
│   ├── logging_setup.py          # Structured logging
│   ├── rate_limiter.py           # Per-API async rate limiters
│   ├── cache.py                  # In-memory TTL cache
│   └── site_publisher.py         # Writes HTML to site-generator/public/ + triggers build
├── bot/tasks/
│   ├── morning_briefing.py       # Daily/weekly briefing scheduler
│   └── market_scan.py            # Weekly market scan scheduler
└── systemd/
    └── finance-digest.service    # Systemd unit file
```

## Key Workflows

### /analyze TICKER (6-Step Deep Dive)

```
cmd_analyze()
  ├─ Check 4-hour analysis_cache (skip if hit)
  ├─ build_snapshot() — 16+ concurrent collectors via asyncio.gather
  │   ├─ yfinance: quote, technicals, financials, CAGR, returns (incl. Piotroski inputs), CapEx, FCF health
  │   ├─ finnhub: earnings, analysts, news, insider, basic financials
  │   ├─ finviz: fundamentals, peer comparison
  │   ├─ alpha_vantage: news sentiment
  │   └─ sec_edgar: MD&A excerpt
  ├─ run_deep_dive() — 5-6 LLM calls; steps 2-5 run in parallel via asyncio.gather
  │   ├─ Steps 2-5: Business Understanding, Financial Analysis, Strategy Assessment, Valuation (parallel)
  │   └─ Step 6: Thesis Check (vs stored thesis, sequential after steps 2-5)
  ├─ publish() → site-generator/public/posts/<slug>.html
  ├─ build_pdf() → Discord attachment
  └─ interaction.followup.send() → Discord
```

**LLM**: 300s timeout per call, 3 retries with exponential backoff.

### Morning Briefing (Daily @ 07:00 EST)

```
run_morning_briefing()
  ├─ build_snapshot() for all portfolio + watchlist tickers (concurrent)
  ├─ Score watchlist → OpportunityScore (0–15, incl. Piotroski F-Score)
  ├─ Score watchlist → paper_score_history (persisted daily for rolling avg)
  ├─ run_paper_trading_session()
  │   ├─ Trailing stop-loss (−15% from position high → SELL, daily)
  │   ├─ Rebalance gate (every REBALANCE_INTERVAL_DAYS days, default 14):
  │   │   ├─ Sell pass (rolling avg score ≤ 3/15 → SELL)
  │   │   ├─ Trim pass (rolling avg score 4–6/15 → sell 50%)
  │   │   └─ Buy pass (rolling avg score ≥ 8/15 → LLM sizes: FULL/HALF/SKIP → BUY)
  │   └─ Daily NAV snapshot always recorded
  ├─ Compose Discord embeds
  ├─ Save briefing HTML → site-generator/public/posts/daily-YYYY-MM-DD.html
  ├─ save_portfolio_page() → NO-OP (portfolio.html is owned by the Node side)
  └─ Send to BRIEFING_CHANNEL_ID
```

**Note**: `web/server.py:save_portfolio_page()` is intentionally a no-op. The portfolio
dashboard (`public/portfolio.html`) is a dynamic Alpine.js page — Python writes data to
`finance_digest.db` and the Node API serves it live. Do not re-enable static page writing.

**Schedule**:
- `06:00` EST — Reset `daily_discoveries` table
- `07:00` EST daily — Watchlist briefing
- `07:00` EST Mondays — Full portfolio deep-dive

### Paper Trading Constants

| Parameter | Value |
|-----------|-------|
| Starting cash | $10,000 |
| Max positions | 10 |
| Buy threshold | score ≥ 8 / 15 |
| Sell threshold | score ≤ 3 / 15 |
| Stop-loss | −15% from avg cost |
| Position size | 10% of NAV (new position) |
| Min trade size | $50 |

## Database Schema (`finance_digest.db`)

| Table | Purpose |
|-------|---------|
| `companies` | Portfolio + watchlist tickers |
| `investment_thesis` | User SWOT + rationale per ticker |
| `briefing_log` | Audit trail of all briefings |
| `analysis_cache` | 4-hour TTL cache (max 3 per ticker) |
| `market_scan_log` | Scan run metadata + statistics |
| `market_discoveries` | Stocks found by market scans (scored) |
| `daily_discoveries` | Today's scored candidates (reset @ 06:00) |
| `paper_portfolio_state` | Singleton: cash balance + inception date |
| `paper_trades` | Full trade history (BUY/SELL) |
| `paper_daily_value` | Daily NAV snapshots |
| `paper_daily_positions` | Per-ticker position snapshots per day |

WAL mode enabled. Foreign keys enforced. Cascading deletes on company removal.

## Configuration (.env)

| Variable | Purpose |
|----------|---------|
| `DISCORD_TOKEN` | Bot token |
| `DISCORD_GUILD_ID` | Server ID |
| `BRIEFING_CHANNEL_ID` | Channel for daily briefings |
| `OLLAMA_API_URL` | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | e.g. `qwen2.5:7b` |
| `ALPHA_VANTAGE_KEY` | Free tier: 25 req/day |
| `FINNHUB_KEY` | Free tier: 60 req/min |
| `BRIEFING_TIME` | `07:00` (24-hour) |
| `BRIEFING_TIMEZONE` | `America/New_York` |
| `PORTFOLIO_BRIEFING_DAY` | `mon` |
| `DB_PATH` | `./finance_digest.db` |
| `SEC_USER_AGENT` | `Name/1.0 contact@email.com` |

## Key Design Patterns

- **Collector failures are isolated**: `safe()` wrapper catches exceptions per-collector so one failure doesn't abort the run
- **Concurrency**: `asyncio.gather` across all collectors; semaphore limits LLM to 2 simultaneous calls
- **Upsert-safe SQL**: `INSERT OR REPLACE` / `ON CONFLICT` throughout `database.py`
- **Rate limiting**: Per-API async limiters in `utils/rate_limiter.py` (yfinance: 60/min; Finviz: semaphore-3 in aggregator)
- **Type-safe models**: `dataclasses` for all domain objects in `data/models.py`

## Existing Documentation

- `SETUP.md` — 9-step deployment guide
- `DB_SCHEMA.md` — Full SQLite schema
- `ANALYZE_DATAFLOW.md` — Deep-dive on /analyze flow
- `PAPER_TRADER_FLOW.md` — Paper trading logic
- `COMMANDS.md` — Discord slash command reference
