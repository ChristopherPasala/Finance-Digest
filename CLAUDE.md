# Project Knowledge Base

This is a **financial analysis platform** composed of two integrated projects. Read `.context/` files for deep documentation on each part.

## Projects

| Project | Lang | Purpose |
|---------|------|---------|
| `Finance-Digest/` | Python 3.12 | Discord bot — data collection, LLM analysis, paper trading |
| `site-generator/` | Node.js | Web server — renders HTML reports, serves portfolio dashboard |

## How They Connect

```
Finance-Digest (Python)
  → Writes HTML to site-generator/public/posts/
  → Triggers: node src/build.js --slug=<ticker>
  → Writes to finance_digest.db (SQLite)
  → Does NOT write portfolio.html (owned by Node side)

site-generator (Node.js)
  → Reads finance_digest.db (read-only) for live portfolio API
  → Reads/writes its own data.db (posts, SPX benchmarks)
  → Serves localhost:3000
  → Auto-fetches missing SPX closes on startup
```

## Shared Database Files

| File | Owner | Purpose |
|------|-------|---------|
| `Finance-Digest/finance_digest.db` | Finance-Digest | Portfolio, thesis, cache, paper trading |
| `site-generator/data.db` | site-generator | Posts index, benchmarks, portfolio snapshots |

## Entry Points

```bash
# Finance-Digest
cd Finance-Digest && .venv/bin/python run.py

# site-generator
cd site-generator && npm run dev   # builds then serves on :3000
```

## Context Files

- [.context/finance-digest.md](.context/finance-digest.md) — Architecture, workflows, DB schema, config
- [.context/site-generator.md](.context/site-generator.md) — Express server, build pipeline, templates
- [.context/integration.md](.context/integration.md) — Cross-project data flow and contracts
