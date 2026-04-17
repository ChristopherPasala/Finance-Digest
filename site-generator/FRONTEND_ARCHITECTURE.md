# Frontend Architecture

---

## Current Stack

The site-generator is a Node/Express + EJS project. It is **not** React or any SPA framework.

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Server | Express (`src/server.js`) | Serves `public/` as static files |
| Templates | EJS (`templates/*.html`) | HTML layout and page templates |
| Build | Node (`src/build.js`) | Reads SQLite, renders EJS → static HTML files |
| Database | better-sqlite3 (`data.db`) | Written by the Python bot, read by the build script |
| Styling | Inline CSS in `layout.html` | No build step, no preprocessor |

### How a page gets generated

```
Python bot
    │
    └─ writes analysis/scan/briefing data → data.db
            │
            ▼
    node src/build.js --slug=aapl
            │
            ├─ reads post from data.db via db.js
            ├─ renders templates/article.html (EJS)
            ├─ wraps in templates/layout.html (nav, footer)
            ├─ applies glossary auto-links (build.js: applyGlossaryLinks)
            └─ writes public/posts/aapl.html
                        │
                        ▼
            Express serves public/ as static files
```

### Current pages

| Route | Template | Content |
|-------|----------|---------|
| `/` | `templates/index.html` | List of all company analyses |
| `/posts/:slug.html` | `templates/article.html` | Individual analysis / briefing / scan |
| `/scans.html` | `templates/scans.html` | Market scan index |
| `/briefings.html` | `templates/briefings.html` | Briefing index |
| `/glossary.html` | `templates/glossary.html` | Financial terms, auto-linked from articles |

---

## Why Not React Yet

The current output is **read-only, pre-generated HTML**. There is no user interaction, no real-time data, and no auth. A React/Next.js framework would add a full build pipeline with no meaningful benefit at this stage.

The architecture is already well-separated:
- Python owns all data and analysis logic
- Node owns rendering and serving
- That boundary carries forward cleanly into any future stack

---

## Path to a Live Dashboard

When ready to expand into a live portfolio dashboard (real-time NAV, trade history, interactive charts), the right progression is:

### Stage 1 — Add live API routes to Express (no framework needed)

`server.js` currently only serves static files. Adding API routes is a one-file change:

```js
const Database = require('better-sqlite3');
const db = new Database(path.join(__dirname, '..', 'data.db'), { readonly: true });

app.use(express.json());

app.get('/api/portfolio', (req, res) => {
  const state = db.prepare('SELECT * FROM paper_portfolio_state WHERE id=1').get();
  const positions = db.prepare(`
    SELECT ticker, SUM(CASE WHEN action='BUY' THEN shares ELSE -shares END) AS net_shares
    FROM paper_trades GROUP BY ticker HAVING net_shares > 0.0001
  `).all();
  res.json({ state, positions });
});

app.get('/api/portfolio/history', (req, res) => {
  const rows = db.prepare('SELECT * FROM paper_daily_value ORDER BY snapshot_date ASC').all();
  res.json(rows);
});
```

These read from the **same `data.db`** the Python bot writes to — no extra infrastructure.

### Stage 2 — Add Alpine.js for reactive UI (no build step)

Add to `layout.html` via CDN:

```html
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
```

Then any EJS template can have live-fetching widgets:

```html
<div x-data="{ nav: null }" x-init="fetch('/api/portfolio').then(r=>r.json()).then(d=>nav=d)">
  <span x-text="nav ? '$' + nav.state.cash.toFixed(2) : 'Loading...'"></span>
</div>
```

This gives reactive, live-updating UI without any build tooling or framework.

For charts, add Chart.js via CDN alongside Alpine:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### Stage 3 — Migrate to Next.js (only if needed)

Only worth doing if you need:
- Server-side auth / per-user views
- A full SPA with client-side routing
- Complex component state across many pages
- A proper component library (shadcn/ui, etc.)

If you reach this point, the migration is straightforward because the data layer stays identical — Next.js API routes just replace the Express API routes, reading from the same SQLite DB.

**Recommended stack at that point:**
- Next.js (App Router)
- Tailwind CSS + shadcn/ui
- Recharts or Tremor for financial charts
- better-sqlite3 (same as today) in API routes

---

## Recommended Stack by Stage

| Stage | What you need | Stack |
|-------|--------------|-------|
| Now | Static reports, read-only | Express + EJS (current) |
| Soon | Live portfolio numbers, basic charts | Express + EJS + Alpine.js + Chart.js (CDN) |
| Later | Full dashboard, auth, complex UI | Next.js + Tailwind + shadcn/ui + Recharts |

---

## The One Change to Make Now

`server.js` is currently 4 lines and only serves static files. Adding `express.json()` and preparing it for API routes costs nothing and means future routes slot in cleanly:

```js
const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

// Future API routes go here
// app.get('/api/portfolio', ...)

app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
```

---

## File Reference

| File | Role |
|------|------|
| [src/server.js](src/server.js) | Express server — static file serving, future API routes |
| [src/build.js](src/build.js) | Static site generator — EJS rendering, glossary linking |
| [src/db.js](src/db.js) | SQLite reader (better-sqlite3) |
| [src/glossary.json](src/glossary.json) | Financial terms auto-linked into article HTML |
| [templates/layout.html](templates/layout.html) | Shared nav, CSS, footer wrapper for all pages |
| [templates/article.html](templates/article.html) | Individual analysis/briefing/scan page |
| [templates/index.html](templates/index.html) | Analyses listing page |
| [templates/scans.html](templates/scans.html) | Market scans index |
| [templates/briefings.html](templates/briefings.html) | Briefings index |
| [templates/glossary.html](templates/glossary.html) | Glossary page |
| [public/](public/) | Generated static output — served directly by Express |
