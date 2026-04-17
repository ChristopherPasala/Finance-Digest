# Database Schema

SQLite database (`finance_digest.db`). WAL mode enabled. Foreign keys enforced.

---

## Tables Overview

| Table | Purpose |
|-------|---------|
| [companies](#companies) | Portfolio and watchlist tickers |
| [investment_thesis](#investment_thesis) | Per-ticker SWOT + thesis notes |
| [briefing_log](#briefing_log) | Record of every briefing run |
| [analysis_cache](#analysis_cache) | 4-hour cache for analysis results |
| [market_scan_log](#market_scan_log) | Log of each market scan run |
| [market_discoveries](#market_discoveries) | Stocks discovered during scans |
| [daily_discoveries](#daily_discoveries) | Today's scored discovery candidates |
| [paper_portfolio_state](#paper_portfolio_state) | Singleton cash balance for paper trading |
| [paper_trades](#paper_trades) | Full paper trade history |
| [paper_daily_value](#paper_daily_value) | Daily portfolio value snapshots |
| [paper_daily_positions](#paper_daily_positions) | Daily per-ticker position snapshots |

---

## companies

Tracks every ticker the user has added via `/add`.

```sql
CREATE TABLE companies (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name      TEXT,
    list_type TEXT NOT NULL CHECK(list_type IN ('portfolio','watchlist')),
    added_at  TEXT NOT NULL DEFAULT (datetime('now')),
    notes     TEXT
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `ticker` | TEXT | Unique, case-insensitive |
| `name` | TEXT | Company display name |
| `list_type` | TEXT | `'portfolio'` or `'watchlist'` |
| `added_at` | TEXT | ISO datetime, auto-set |
| `notes` | TEXT | Optional user notes |

**Used by**: `/add`, `/remove`, `/list`, briefing scheduler, analysis commands

---

## investment_thesis

Stores the user's investment thesis for a ticker (SWOT breakdown, moat, price target, open questions).

```sql
CREATE TABLE investment_thesis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL COLLATE NOCASE,
    strengths       TEXT,
    weaknesses      TEXT,
    opportunities   TEXT,
    threats         TEXT,
    moat            TEXT,
    entry_rationale TEXT,
    target_price    REAL,
    questions       TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(ticker) REFERENCES companies(ticker) ON DELETE CASCADE
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `ticker` | TEXT | FK → `companies.ticker`, cascades on delete |
| `strengths` | TEXT | SWOT: S |
| `weaknesses` | TEXT | SWOT: W |
| `opportunities` | TEXT | SWOT: O |
| `threats` | TEXT | SWOT: T |
| `moat` | TEXT | Competitive advantage description |
| `entry_rationale` | TEXT | Why this position was entered |
| `target_price` | REAL | User's price target |
| `questions` | TEXT | Open questions to monitor |
| `updated_at` | TEXT | ISO datetime, updated on every upsert |

**Used by**: `/thesis` command, Step 6 of `/analyze` (thesis check)

---

## briefing_log

Audit trail of every briefing that was triggered (scheduled or manual).

```sql
CREATE TABLE briefing_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    trigger_type    TEXT NOT NULL CHECK(trigger_type IN ('scheduled','manual')),
    channel_id      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('success','partial','failed')),
    tickers_covered TEXT,
    error_message   TEXT
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `triggered_at` | TEXT | ISO datetime |
| `trigger_type` | TEXT | `'scheduled'` or `'manual'` |
| `channel_id` | TEXT | Discord channel the briefing was sent to |
| `status` | TEXT | `'success'`, `'partial'`, or `'failed'` |
| `tickers_covered` | TEXT | JSON array of tickers in the briefing |
| `error_message` | TEXT | Populated on failure |

**Used by**: `/briefing`, scheduler

---

## analysis_cache

Caches analysis payloads to avoid redundant LLM + data-collection runs. Entries expire after 4 hours. Max 3 entries retained per `(ticker, data_type)` pair.

```sql
CREATE TABLE analysis_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     TEXT NOT NULL COLLATE NOCASE,
    data_type  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE INDEX idx_cache ON analysis_cache(ticker, data_type, expires_at);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `ticker` | TEXT | Case-insensitive |
| `data_type` | TEXT | Category of cached data (e.g. `'analysis'`) |
| `payload` | TEXT | JSON-serialized cache content |
| `fetched_at` | TEXT | When the data was fetched |
| `expires_at` | TEXT | Expiry datetime — entries older than this are ignored |

**Indexes**: `(ticker, data_type, expires_at)`

**Used by**: `/analyze` cache check, `set_cache()` / `get_cache()` / `invalidate_cache()`

---

## market_scan_log

One row per market scan run. Records scan statistics and outcome.

```sql
CREATE TABLE market_scan_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at        TEXT NOT NULL DEFAULT (datetime('now')),
    trigger_type      TEXT NOT NULL DEFAULT 'scheduled',
    tickers_scanned   INTEGER NOT NULL DEFAULT 0,
    stage1_passed     INTEGER NOT NULL DEFAULT 0,
    discoveries_found INTEGER NOT NULL DEFAULT 0,
    top_tickers       TEXT,
    duration_seconds  REAL,
    error_message     TEXT
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK, referenced by `market_discoveries.scan_id` |
| `scanned_at` | TEXT | ISO datetime |
| `trigger_type` | TEXT | `'scheduled'` or `'manual'` |
| `tickers_scanned` | INTEGER | Total tickers evaluated in this scan |
| `stage1_passed` | INTEGER | Tickers that passed the initial filter |
| `discoveries_found` | INTEGER | Final discoveries after LLM gate |
| `top_tickers` | TEXT | JSON array of top-scoring ticker symbols |
| `duration_seconds` | REAL | Total scan runtime |
| `error_message` | TEXT | Populated on failure |

**Used by**: `/screen` command, scheduled market scan

---

## market_discoveries

Stocks discovered during a scan, with scoring and LLM evaluation.

```sql
CREATE TABLE market_discoveries (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id            INTEGER REFERENCES market_scan_log(id) ON DELETE CASCADE,
    ticker             TEXT NOT NULL COLLATE NOCASE,
    name               TEXT,
    sector             TEXT,
    score              INTEGER NOT NULL,
    signals            TEXT NOT NULL,
    llm_evaluation     TEXT,
    scanned_at         TEXT NOT NULL DEFAULT (datetime('now')),
    added_to_watchlist INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_discoveries_ticker ON market_discoveries(ticker, scanned_at);
CREATE INDEX idx_discoveries_scan   ON market_discoveries(scan_id);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `scan_id` | INTEGER | FK → `market_scan_log.id`, cascades on delete |
| `ticker` | TEXT | Case-insensitive |
| `name` | TEXT | Company name |
| `sector` | TEXT | Market sector |
| `score` | INTEGER | Opportunity score (higher = stronger signal) |
| `signals` | TEXT | JSON array of signal strings |
| `llm_evaluation` | TEXT | LLM's narrative evaluation of the opportunity |
| `scanned_at` | TEXT | ISO datetime of discovery |
| `added_to_watchlist` | INTEGER | `1` if user added this to their watchlist |

**Indexes**: `(ticker, scanned_at)`, `(scan_id)`

**Used by**: `/screen`, `mark_discovery_added()`

---

## daily_discoveries

Today's scored candidates, reset each morning at 06:00. Upsert-safe — keeps the higher score on conflict.

```sql
CREATE TABLE daily_discoveries (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    date               TEXT NOT NULL,
    ticker             TEXT NOT NULL COLLATE NOCASE,
    name               TEXT,
    sector             TEXT,
    score              INTEGER NOT NULL,
    signals            TEXT NOT NULL,
    llm_evaluation     TEXT,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    added_to_watchlist INTEGER NOT NULL DEFAULT 0,
    UNIQUE(date, ticker)
);

CREATE INDEX idx_daily_disc_date ON daily_discoveries(date, score DESC);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `date` | TEXT | `YYYY-MM-DD` — partition key |
| `ticker` | TEXT | Case-insensitive, unique per date |
| `name` | TEXT | Company name |
| `sector` | TEXT | Market sector |
| `score` | INTEGER | Opportunity score |
| `signals` | TEXT | JSON array of signal strings |
| `llm_evaluation` | TEXT | LLM narrative; preserved if new value is null |
| `updated_at` | TEXT | Updated on upsert |
| `added_to_watchlist` | INTEGER | `1` if promoted to watchlist |

**Constraints**: `UNIQUE(date, ticker)` — upsert updates only if new score ≥ existing score

**Indexes**: `(date, score DESC)`

**Used by**: daily discovery init (06:00), `/opportunities` command

---

## paper_portfolio_state

Singleton table (always exactly 1 row, `id = 1`). Tracks the current cash balance for the paper trading simulator.

```sql
CREATE TABLE paper_portfolio_state (
    id           INTEGER PRIMARY KEY CHECK(id = 1),
    cash         REAL    NOT NULL DEFAULT 10000.0,
    inception_at TEXT    NOT NULL DEFAULT (date('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Always `1` (enforced by CHECK constraint) |
| `cash` | REAL | Current available cash (starts at $10,000) |
| `inception_at` | TEXT | Date the portfolio was initialized |
| `updated_at` | TEXT | Updated on every cash change |

**Used by**: `/paper` command, paper trade execution

---

## paper_trades

Full history of every paper buy and sell.

```sql
CREATE TABLE paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL COLLATE NOCASE,
    action      TEXT    NOT NULL CHECK(action IN ('BUY','SELL')),
    shares      REAL    NOT NULL,
    price       REAL    NOT NULL,
    total_value REAL    NOT NULL,
    reason      TEXT,
    score       INTEGER,
    traded_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_paper_trades_ticker ON paper_trades(ticker, traded_at);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `ticker` | TEXT | Case-insensitive |
| `action` | TEXT | `'BUY'` or `'SELL'` |
| `shares` | REAL | Number of shares traded |
| `price` | REAL | Price per share at time of trade |
| `total_value` | REAL | `shares × price` |
| `reason` | TEXT | JSON array of signals that triggered the trade |
| `score` | INTEGER | Opportunity score at time of trade |
| `traded_at` | TEXT | ISO datetime |

**Note**: Current positions are computed by summing `BUY` minus `SELL` shares per ticker at query time — no separate positions table.

**Indexes**: `(ticker, traded_at)`

**Used by**: `/paper`, `paper_get_positions()`, `paper_get_entry_prices()`

---

## paper_daily_value

One row per day. Records the total portfolio value snapshot for P&L tracking.

```sql
CREATE TABLE paper_daily_value (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL UNIQUE,
    portfolio_value REAL    NOT NULL,
    cash            REAL    NOT NULL,
    invested        REAL    NOT NULL,
    recorded_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_paper_daily_value_date ON paper_daily_value(snapshot_date);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `snapshot_date` | TEXT | `YYYY-MM-DD`, unique per day |
| `portfolio_value` | REAL | Total value (cash + invested) |
| `cash` | REAL | Uninvested cash at close of day |
| `invested` | REAL | Market value of all open positions |
| `recorded_at` | TEXT | ISO datetime of snapshot |

**Indexes**: `(snapshot_date)`

**Used by**: `/paper performance`, P&L chart generation

---

## paper_daily_positions

Per-ticker position snapshot for each day. Includes a `CASH` pseudo-ticker for cash allocation.

```sql
CREATE TABLE paper_daily_positions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date  TEXT    NOT NULL,
    ticker         TEXT    NOT NULL COLLATE NOCASE,
    shares         REAL    NOT NULL,
    price          REAL    NOT NULL,
    position_value REAL    NOT NULL,
    weight_pct     REAL    NOT NULL,
    recorded_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(snapshot_date, ticker)
);

CREATE INDEX idx_paper_daily_positions_date ON paper_daily_positions(snapshot_date);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | PK |
| `snapshot_date` | TEXT | `YYYY-MM-DD` |
| `ticker` | TEXT | Ticker symbol, or `'CASH'` for uninvested cash |
| `shares` | REAL | Shares held (0 for CASH row) |
| `price` | REAL | Price per share at snapshot (0 for CASH row) |
| `position_value` | REAL | Total value of this position |
| `weight_pct` | REAL | Portfolio weight as a percentage |
| `recorded_at` | TEXT | ISO datetime |

**Constraints**: `UNIQUE(snapshot_date, ticker)` — upsert-safe

**Indexes**: `(snapshot_date)`

**Used by**: `/paper holdings`, daily position snapshots

---

## Relationships

```
companies
    │
    └─── investment_thesis  (ticker FK, CASCADE DELETE)

market_scan_log
    │
    └─── market_discoveries (scan_id FK, CASCADE DELETE)

paper_portfolio_state  (singleton)
paper_trades           (positions derived at query time)
paper_daily_value      (1 row per day)
paper_daily_positions  (N rows per day, 1 per ticker + CASH)

analysis_cache         (standalone, TTL-based expiry)
briefing_log           (standalone, append-only)
daily_discoveries      (standalone, reset daily)
```
