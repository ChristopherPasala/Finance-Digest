# `/analyze` Command — Data Flow Breakdown

## Overview

The `/analyze TICKER` Discord slash command performs a 6-step deep-dive investment research report on a given stock. It aggregates real-time data from 6+ financial sources concurrently, passes the data through a local LLM (Ollama) for analysis, then delivers the result as a PDF file in Discord and optionally as a web-hosted HTML report.

---

## High-Level Flow

```
User: /analyze AAPL
        ↓
  Discord API → cmd_analyze()
        ↓
  Cache check (4-hour TTL)
   ├─ HIT  → return existing URL and exit
   └─ MISS → continue
        ↓
  build_snapshot() — 16+ concurrent collectors
        ↓
  run_deep_dive() — steps 2-5 parallel, step 6 sequential
        ↓
  publish() — HTML report → web server
        ↓
  build_pdf() — markdown → PDF buffer
        ↓
  Discord followup — PDF file + optional URL
```

---

## Step-by-Step Breakdown

### Step 1 — Command Entry

**File**: [bot/commands/analyze.py](bot/commands/analyze.py)

The Discord slash command handler fires when a user runs `/analyze TICKER`:

1. Calls `interaction.response.defer(thinking=True)` — tells Discord "I'm working on it"
2. Normalizes the ticker to uppercase
3. Checks a 4-hour analysis cache via `get_existing_url(slug)` from `utils/site_publisher.py`
   - If a fresh analysis exists, sends the cached URL immediately and exits
   - If not, proceeds with a full analysis
4. Sends an initial message: `"Starting 6-step analysis for **TICKER**..."`

---

### Step 2 — Data Collection (`build_snapshot`)

**File**: [collectors/aggregator.py](collectors/aggregator.py)
**Function**: `build_snapshot(ticker, include_sec=True, include_av=True) -> CompanySnapshot`

All collectors run **concurrently** via `asyncio.gather()`. Blocking I/O (yfinance, finviz, SEC) runs in executor threads.

| Collector | Source | Data Retrieved |
|-----------|--------|---------------|
| `yfinance_collector.get_quote()` | Yahoo Finance | Price, volume, 52-week range, change % |
| `yfinance_collector.get_info()` | Yahoo Finance | Company description, sector, employees, market cap |
| `yfinance_collector.get_technicals()` | Yahoo Finance | RSI, SMA-50, SMA-200, MACD |
| `yfinance_collector.get_news()` | Yahoo Finance | Recent news articles |
| `yfinance_collector.get_financials_history()` | Yahoo Finance | Historical P/E, margins, debt ratios |
| `yfinance_collector.compute_cagr()` | Yahoo Finance | 5yr/10yr revenue & EPS CAGR |
| `yfinance_collector.compute_returns()` | Yahoo Finance | ROE, ROIC history |
| `yfinance_collector.compute_capex()` | Yahoo Finance | Capital expenditure trends |
| `yfinance_collector.compute_financial_health()` | Yahoo Finance | FCF, net debt, interest coverage |
| `finnhub_collector.get_earnings()` | Finnhub | Upcoming earnings dates, EPS surprises |
| `finnhub_collector.get_analyst_recommendations()` | Finnhub | Buy/hold/sell counts, price targets |
| `finnhub_collector.get_news()` | Finnhub | Financial news (merged with Yahoo news) |
| `finnhub_collector.get_insider_transactions()` | Finnhub | Insider buy/sell activity |
| `finnhub_collector.get_basic_financials()` | Finnhub | Key financial ratios |
| `finviz_collector.get_fundamentals()` | FinViz | Fundamentals snapshot |
| `finviz_collector.get_peers()` | FinViz | Peer comparison tickers |
| `alphavantage_collector.get_news_sentiment()` | Alpha Vantage | Aggregate news sentiment score |
| `sec_edgar_collector.get_mda_excerpt()` | SEC EDGAR | MD&A excerpt from latest 10-K |

**Post-collection**:
- News articles from Yahoo + Finnhub are merged and deduplicated (>85% title similarity threshold)
- All results are assembled into a `CompanySnapshot` dataclass ([data/models.py](data/models.py))
- Each collector is wrapped in a `safe()` function — failures log a warning but don't abort the run

---

### Step 3 — Snapshot Formatting

**File**: [analysis/company_analyzer.py](analysis/company_analyzer.py)
**Function**: `_format_snapshot_for_briefing(snapshot, thesis) -> dict`

The raw `CompanySnapshot` is flattened into 70+ named fields used to fill LLM prompt templates. Key field groups:

| Group | Example Fields |
|-------|---------------|
| Price & Technicals | `price`, `change_pct`, `rsi`, `sma50`, `sma200`, `macd_signal` |
| Fundamentals | `pe`, `fwd_pe`, `eps`, `gross_margin`, `op_margin`, `net_margin`, `debt_equity` |
| Growth | `rev_cagr_5y`, `rev_cagr_10y`, `eps_cagr_5y`, `op_cagr_5y` |
| Returns | `roe_5y`, `roic`, `roa`, `fcf`, `fcf_yield` |
| Earnings & Analysts | `next_earnings_date`, `eps_surprise`, `strong_buy`, `target_mean`, `target_upside` |
| Strategic | `insider_summary`, `news_bullets`, `sec_excerpt`, `capex_history`, `roic_history` |
| Peers | `peer_table`, `peer_valuation_table` |
| Thesis (if set) | `thesis_block` — user's stored investment thesis from the database |

---

### Step 4 — 6-Step LLM Analysis (`run_deep_dive`)

**File**: [analysis/company_analyzer.py](analysis/company_analyzer.py)
**Function**: `run_deep_dive(ticker) -> list[str]`

**LLM Client**: [analysis/llm_client.py](analysis/llm_client.py)
- Backend: Ollama (`localhost:11434/v1`, OpenAI-compatible)
- Model: configurable via `OLLAMA_MODEL` (default: `qwen2.5:7b`)
- Temperature: `0.3` (low, for factual/consistent output)
- Concurrency: max 2 simultaneous LLM calls (asyncio semaphore)
- Timeout: 300s per call; up to 3 retries with exponential backoff

Each step injects the formatted snapshot fields into a prompt template from [analysis/prompts.py](analysis/prompts.py) and calls the LLM:

| Step | Prompt Template | `max_tokens` | Focus |
|------|----------------|-------------|-------|
| 1 | *(data collection — no LLM)* | — | Raw data aggregation |
| 2 | `BUSINESS_UNDERSTANDING_USER` | 65536 | SWOT, business model, competitive position |
| 3 | `FINANCIAL_ANALYSIS_USER` | 65536 | Growth, profitability, cash flow, balance sheet, peers |
| 4 | `STRATEGY_ASSESSMENT_USER` | 65536 | CapEx, buybacks, management priorities, ROIC trends. Outputs `GUIDANCE_CREDIBILITY: HIGH\|MEDIUM\|LOW` |
| 5 | `VALUATION_USER` | 65536 | Multiples, historical context, analyst consensus, insider signals |
| 6 | `THESIS_CHECK_USER` | 32000 | Compare stored thesis vs. current data *(only if thesis exists)* |

**Steps 2–5 run in parallel** via `asyncio.gather()` — they are all independent analyses of the same pre-built snapshot. Step 6 (thesis check) runs sequentially after. This cuts deep dive wall-clock time by ~50% compared to sequential execution.

All steps share `ANALYST_SYSTEM` as the system prompt — a persona that enforces factual, data-grounded analysis.

The function returns a `list[str]` — one markdown-formatted section per step.

---

### Step 5 — Web Publishing

**File**: [utils/site_publisher.py](utils/site_publisher.py)
**Function**: `publish(slug, title, sections) -> str`

- Converts the markdown sections into an HTML report via [formatters/html_formatter.py](formatters/html_formatter.py)
- Saves the report to the local web server directory
- Returns a public-facing URL (e.g. via Cloudflare tunnel configured as `WEB_PUBLIC_URL`)
- If no web server is configured, returns an empty string

---

### Step 6 — PDF Generation

**File**: [formatters/pdf_formatter.py](formatters/pdf_formatter.py)
**Function**: `build_pdf(title, sections, subtitle) -> BytesIO`

- Parses each markdown section
- Renders formatted content using `fpdf2`
- Returns a `BytesIO` buffer (no file written to disk)

---

### Step 7 — Discord Delivery

Back in [bot/commands/analyze.py](bot/commands/analyze.py):

```python
await interaction.followup.send(
    msg,                          # text message with optional URL
    file=discord.File(
        pdf_buffer,
        filename="analysis_AAPL_2026-04-04.pdf"
    )
)
```

The user receives:
- A PDF attached directly in the Discord channel
- A web link (if `WEB_PUBLIC_URL` is configured)

---

## Full Data Flow Diagram

```
/analyze AAPL
    │
    ▼
cmd_analyze()                          [bot/commands/analyze.py]
    │
    ├─ get_existing_url("aapl")        [utils/site_publisher.py]
    │       └─ cache HIT? → send URL and return early
    │
    ├─ "Starting analysis..." message
    │
    ▼
build_snapshot("AAPL")                 [collectors/aggregator.py]
    │
    ├─ [concurrent via asyncio.gather]
    │       ├─ yfinance_collector (9 functions)
    │       ├─ finnhub_collector  (5 functions)
    │       ├─ finviz_collector   (3 functions)
    │       ├─ alphavantage_collector (1 function)
    │       └─ sec_edgar_collector    (1 function)
    │
    └─ CompanySnapshot (merged, deduplicated)
    │
    ▼
_format_snapshot_for_briefing()        [analysis/company_analyzer.py]
    │
    └─ dict with 70+ named fields
    │
    ▼
run_deep_dive("AAPL")                  [analysis/company_analyzer.py]
    │
    ├─ asyncio.gather (steps 2-5 run in parallel, pipelined through 2-slot LLM semaphore)
    │       ├─ Step 2: BUSINESS_UNDERSTANDING prompt → Ollama → SWOT section
    │       ├─ Step 3: FINANCIAL_ANALYSIS prompt     → Ollama → financials section
    │       ├─ Step 4: STRATEGY_ASSESSMENT prompt    → Ollama → strategy + GUIDANCE_CREDIBILITY line
    │       └─ Step 5: VALUATION prompt              → Ollama → valuation section
    └─ Step 6: THESIS_CHECK prompt → Ollama → thesis check section (if thesis set, sequential)
    │
    └─ list[str] of markdown sections
    │
    ▼
publish("aapl", title, sections)       [utils/site_publisher.py]
    │
    └─ HTML report saved + public URL returned
    │
    ▼
build_pdf(title, sections, subtitle)   [formatters/pdf_formatter.py]
    │
    └─ BytesIO PDF buffer
    │
    ▼
interaction.followup.send()            [discord.py]
    │
    └─ PDF file + optional URL → Discord channel
```

---

## Key Infrastructure

### Caching

- **Analysis cache**: SQLite `analysis_cache` table, 4-hour TTL per ticker
- **In-memory cache**: `utils/cache.py` — used by collectors for short-lived quotes/fundamentals

### Rate Limiting

- `utils/rate_limiter.py` — per-API async rate limiters (asyncio.Lock + timestamp tracking)
- Ollama calls are additionally gated by a semaphore (max 2 concurrent)

### Error Handling

- All collectors wrapped in `safe()` — logs failures, returns `None`, never crashes the run
- LLM client retries up to 3 times with exponential backoff on timeout or server error
- Startup (`run.py`) pings Ollama and warns if APIs keys are missing, but does not abort

### Configuration

All settings come from `.env` via `utils/config.py`. Key values for the analyze flow:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_API_URL` | `http://localhost:11434/v1` | LLM backend |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Model used for all analysis steps |
| `FINNHUB_KEY` | *(none)* | Enables earnings + analyst + insider data |
| `ALPHA_VANTAGE_KEY` | *(none)* | Enables news sentiment scoring |
| `WEB_PUBLIC_URL` | *(none)* | Enables web report links in Discord |
| `SEC_USER_AGENT` | *(required)* | Required by SEC EDGAR to fetch 10-K filings |

---

## Relevant Files

| File | Role |
|------|------|
| [bot/commands/analyze.py](bot/commands/analyze.py) | Command entry point and Discord output |
| [analysis/company_analyzer.py](analysis/company_analyzer.py) | 6-step orchestration, snapshot formatting |
| [analysis/prompts.py](analysis/prompts.py) | All LLM prompt templates |
| [analysis/llm_client.py](analysis/llm_client.py) | Ollama async client, retries, rate limiting |
| [collectors/aggregator.py](collectors/aggregator.py) | Concurrent collector orchestration |
| [collectors/yfinance_collector.py](collectors/yfinance_collector.py) | Yahoo Finance data (9 functions) |
| [collectors/finnhub_collector.py](collectors/finnhub_collector.py) | Finnhub API client |
| [collectors/finviz_collector.py](collectors/finviz_collector.py) | FinViz fundamentals + peers |
| [collectors/alphavantage_collector.py](collectors/alphavantage_collector.py) | News sentiment |
| [collectors/sec_edgar_collector.py](collectors/sec_edgar_collector.py) | SEC 10-K MD&A extraction |
| [formatters/pdf_formatter.py](formatters/pdf_formatter.py) | PDF generation (fpdf2) |
| [formatters/html_formatter.py](formatters/html_formatter.py) | HTML report generation |
| [utils/site_publisher.py](utils/site_publisher.py) | Web publishing + cache check |
| [utils/cache.py](utils/cache.py) | In-memory TTL cache |
| [utils/rate_limiter.py](utils/rate_limiter.py) | Per-API async rate limiters |
| [data/models.py](data/models.py) | `CompanySnapshot` and related dataclasses |
| [data/database.py](data/database.py) | SQLite layer — thesis + cache tables |
