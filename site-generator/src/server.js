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

  // Scoring grid — latest + previous score + 14d rolling avg + price per ticker
  const scoreRows = FD_DB.prepare(`
    SELECT
      ticker,
      score,
      price,
      piotroski_fscore,
      signals,
      score_date,
      ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY score_date DESC) AS rn
    FROM paper_score_history
  `).all();

  // Group into latest (rn=1) and previous (rn=2) per ticker
  const latestMap = {}, prevMap = {};
  for (const r of scoreRows) {
    if (r.rn === 1) latestMap[r.ticker] = r;
    else if (r.rn === 2) prevMap[r.ticker] = r;
  }

  const rolling = FD_DB.prepare(`
    SELECT ticker,
           ROUND(AVG(score), 1) AS avg_score,
           COUNT(*)             AS data_points
    FROM paper_score_history
    WHERE score_date >= date('now', '-14 days')
    GROUP BY ticker
  `).all();
  const rollingMap = {};
  for (const r of rolling) rollingMap[r.ticker] = r;

  const heldTickers = new Set(positions.map(p => p.ticker));

  const scores = Object.values(latestMap).map(s => {
    let signals = [];
    try { signals = JSON.parse(s.signals).slice(0, 3); } catch {}
    const r = rollingMap[s.ticker] || {};
    const prev = prevMap[s.ticker];
    const delta = prev != null ? s.score - prev.score : null;
    return {
      ticker: s.ticker,
      latest_score: s.score,
      prev_score: prev?.score ?? null,
      delta,
      avg_score: r.avg_score ?? s.score,
      data_points: r.data_points ?? 1,
      price: s.price ?? null,
      piotroski_fscore: s.piotroski_fscore,
      signals,
      held: heldTickers.has(s.ticker),
    };
  }).sort((a, b) => b.avg_score - a.avg_score);

  res.json({ state, positions, trades, scores });
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
