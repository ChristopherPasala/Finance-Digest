# Integration & Data Flow

How Finance-Digest and site-generator work together.

## Full Data Flow

```
External APIs (yfinance, Finnhub, Alpha Vantage, FinViz, SEC EDGAR)
    ↓
Finance-Digest/collectors/aggregator.py   (16+ concurrent collectors)
    ↓
Finance-Digest/analysis/company_analyzer.py   (6-step LLM analysis via Ollama)
    ↓
Finance-Digest/formatters/html_formatter.py   (Markdown → HTML)
    ↓
Finance-Digest/utils/site_publisher.py
    ├─ Writes HTML to: site-generator/public/posts/<slug>.html
    ├─ Inserts post into: site-generator/data.db (posts table)
    └─ Calls: node src/build.js --slug=<slug>
                ↓
        site-generator/src/build.js
            ├─ Reads post from data.db
            ├─ Renders EJS templates
            ├─ Applies glossary auto-links
            └─ Writes: site-generator/public/posts/<slug>.html (final)
                ↓
        site-generator/src/server.js (Express on :3000)
            ├─ Serves static files from public/
            ├─ GET /api/portfolio       → reads finance_digest.db live
            └─ GET /api/portfolio/history → reads finance_digest.db + data.db (SPX)
```

## Portfolio Dashboard Data Flow

The portfolio page (`public/portfolio.html`) is **not** written by Python. It is a static
Alpine.js page that fetches live data from the Node API on every page load:

```
finance_digest.db (Python writes)
    ↓
GET /api/portfolio           → state + positions + trades
GET /api/portfolio/history   → daily NAV + SPX benchmark

data.db (Node writes)
    ↓  (market_benchmarks table — SPX closes auto-fetched on server startup)
GET /api/portfolio/history   → merged with NAV above
```

**Key rule**: `Finance-Digest/web/server.py:save_portfolio_page()` is a no-op.
Python no longer writes `portfolio.html`. Do not re-enable it.

## Cross-Project File Writes

Finance-Digest writes to these paths inside site-generator:

| What | Where | Notes |
|------|-------|-------|
| Analysis reports | `site-generator/public/posts/<ticker>.html` | Written by site_publisher.py |
| Daily briefings | `site-generator/public/posts/daily-YYYY-MM-DD.html` | Written by site_publisher.py |
| Market scan reports | `site-generator/public/posts/scan-YYYY-MM-DD.html` | Written by site_publisher.py |
| Post index entry | `site-generator/data.db` (posts table) | Written by site_publisher.py |

**Not written by Python**: `portfolio.html` — this is owned by the Node side.

## Database Access Pattern

```
finance_digest.db  ←→  Finance-Digest (read/write)
                   ←   site-generator/src/server.js (read-only, readonly: true)

data.db            ←→  site-generator (read/write: posts, market_benchmarks)
                   ←   Finance-Digest/utils/site_publisher.py (writes post slugs only)
```

**Important**: site-generator opens `finance_digest.db` with `readonly: true`. Never write to it from Node.

## Build Trigger Contract

Finance-Digest triggers a build by running:

```bash
node /srv/network-drive/projects/site-generator/src/build.js --slug=<slug>
```

This is synchronous from Finance-Digest's perspective (subprocess call).

The `--slug` flag rebuilds only that one post + its relevant index (briefings/scans/analyses).
No argument rebuilds all indexes.

## Opportunity Scoring → Web Display

```
analysis/opportunity_scanner.py
    → Scores each watchlist ticker (0–15 points, incl. Piotroski F-Score)
    → Adds data-score="N" attribute to each opp-card in briefing HTML

site-generator/src/build.js (extractTodayScores)
    → Parses latest daily-*.html for data-score attributes
    → Passes ranked list to templates/briefings.html
    → Displayed as "Today's Watchlist — Ranked by Opportunity" grid
```

Score thresholds (paper trader):
```
≥ 8 → Paper trader considers BUY (LLM confirms sizing: FULL/HALF/SKIP)
≤ 3 → Paper trader triggers SELL
−15% return → Stop-loss SELL (overrides score)
```

Score colour bands (briefing cards + briefings index):
```
≥ 9   → green  (#22c55e)
6–8   → amber  (#f59e0b)
3–5   → blue   (#3b82f6)
0–2   → slate  (#475569)
```

## Scheduled Tasks Timeline

```
Sunday         → Weekly market scan (market_scanner.py → scan-YYYY-MM-DD.html)
Monday 07:00   → Full portfolio deep-dive briefing
Daily 06:00    → Reset daily_discoveries table
Daily 07:00    → Watchlist briefing + paper trading session
On /analyze    → On-demand 6-step deep dive (cached 4 hours)
On server start → SPX benchmark auto-refresh (refreshSPX in seed-benchmarks.js)
```

## Environment & Paths

Both projects expect to be co-located in the same parent directory:

```
/srv/network-drive/projects/
├── Finance-Digest/
│   ├── finance_digest.db        ← Finance-Digest DB (portfolio, trades, NAV)
│   └── utils/site_publisher.py  ← hardcodes relative path to ../site-generator/
└── site-generator/
    ├── data.db                  ← site-generator DB (posts, market_benchmarks)
    ├── public/                  ← all served static files
    └── src/server.js            ← hardcodes relative path to ../Finance-Digest/finance_digest.db
```

If you move either project, update the cross-references in:
- `Finance-Digest/utils/site_publisher.py` (path to site-generator/public/)
- `site-generator/src/server.js` (path to finance_digest.db)
- `site-generator/src/seed-benchmarks.js` (path to finance_digest.db for inception date)

## Adding a New Report Type

1. Generate HTML in Finance-Digest (new formatter or extend existing)
2. Add publish call in `site_publisher.py` with a new slug pattern
3. Add a new template in `site-generator/templates/` if needed
4. Add a route or index page in `site-generator/src/build.js`
5. Add nav link in `templates/layout.html`
