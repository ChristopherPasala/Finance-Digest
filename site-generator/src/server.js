const express = require('express');
const path = require('path');
const Database = require('better-sqlite3');
const { getBenchmarkHistory } = require('./db');
const { refreshSPX } = require('./seed-benchmarks');

const FD_DB = new Database(
  path.join(__dirname, '..', '..', 'Finance-Digest', 'finance_digest.db'),
  { readonly: true }
);

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

app.get('/api/portfolio', (req, res) => {
  const latest = FD_DB.prepare(
    'SELECT portfolio_value, cash, invested FROM paper_daily_value ORDER BY snapshot_date DESC LIMIT 1'
  ).get();
  const ps = FD_DB.prepare('SELECT inception_at, updated_at FROM paper_portfolio_state WHERE id=1').get();

  const state = {
    nav: latest?.portfolio_value ?? 0,
    total_return_pct: latest ? ((latest.portfolio_value - 10000) / 10000 * 100) : 0,
    invested: latest?.invested ?? 0,
    cash: latest?.cash ?? 0,
    start_date: ps?.inception_at ?? '',
    updated_at: ps?.updated_at?.slice(0, 10) ?? '',
  };

  const positions = FD_DB.prepare(`
    SELECT ticker, shares, price AS current_price,
      (SELECT SUM(total_value) FROM paper_trades t WHERE t.ticker = dp.ticker AND t.action = 'BUY') AS cost_basis
    FROM paper_daily_positions dp
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM paper_daily_positions)
      AND ticker != 'CASH'
  `).all();

  const rawTrades = FD_DB.prepare(
    'SELECT id, ticker, action, shares, price, total_value AS total, reason, traded_at AS date FROM paper_trades ORDER BY traded_at DESC'
  ).all();
  const trades = rawTrades.map(t => {
    try {
      t.reason = JSON.parse(t.reason)
        .filter(s => !s.startsWith('LLM size:'))
        .join(', ');
    } catch {}
    t.date = t.date?.slice(0, 10);
    return t;
  });

  res.json({ state, positions, trades });
});

app.get('/api/portfolio/history', (req, res) => {
  const nav = FD_DB.prepare(
    'SELECT snapshot_date, portfolio_value AS nav FROM paper_daily_value ORDER BY snapshot_date ASC'
  ).all();
  res.json({ nav, spx: getBenchmarkHistory('SPX') });
});

app.use(express.static(path.join(__dirname, '..', 'public')));

app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
  refreshSPX().catch(err => console.warn('[spx] refresh failed:', err.message));
});
