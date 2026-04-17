/**
 * Fetches SPX daily closes from Yahoo Finance and stores them in market_benchmarks.
 *
 * Called automatically by server.js on startup when today's data is stale.
 * Can also be run manually: node src/seed-benchmarks.js
 */

const { upsertBenchmark, getBenchmarkHistory } = require('./db');
const Database = require('better-sqlite3');
const path = require('path');

async function fetchSPX(fromDate, toDate) {
  const period1 = Math.floor(new Date(fromDate).getTime() / 1000);
  const period2 = Math.floor(new Date(toDate + 'T23:59:59Z').getTime() / 1000);
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d&period1=${period1}&period2=${period2}`;

  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' },
  });

  if (!res.ok) throw new Error(`Yahoo Finance returned ${res.status}`);

  const json = await res.json();
  const result = json.chart?.result?.[0];
  if (!result) throw new Error('Unexpected Yahoo Finance response shape');

  const timestamps = result.timestamp;
  const closes = result.indicators.quote[0].close;

  return timestamps.map((ts, i) => ({
    snapshot_date: new Date(ts * 1000).toISOString().slice(0, 10),
    close_price: closes[i],
  })).filter(r => r.close_price != null);
}

/**
 * Refreshes SPX data from the last known date up to today.
 * Safe to call on every server startup — skips fetch if already up to date.
 */
async function refreshSPX() {
  const today = new Date().toISOString().slice(0, 10);
  const existing = getBenchmarkHistory('SPX');
  const lastDate = existing.at(-1)?.snapshot_date;

  if (lastDate === today) return; // already current

  // Fetch from day after last known date (or portfolio inception if none)
  const fdDb = new Database(
    path.join(__dirname, '..', '..', 'Finance-Digest', 'finance_digest.db'),
    { readonly: true }
  );
  const inception = fdDb.prepare(
    'SELECT inception_at FROM paper_portfolio_state WHERE id=1'
  ).get()?.inception_at ?? '2026-01-01';
  fdDb.close();

  const fromDate = lastDate
    ? new Date(new Date(lastDate).getTime() + 86400000).toISOString().slice(0, 10)
    : inception;

  console.log(`[spx] Fetching SPX ${fromDate} → ${today}`);
  const rows = await fetchSPX(fromDate, today);
  for (const row of rows) upsertBenchmark({ ticker: 'SPX', ...row });
  console.log(`[spx] ${rows.length} new data point(s) stored`);
}

module.exports = { refreshSPX };

// Allow direct execution: node src/seed-benchmarks.js
if (require.main === module) {
  refreshSPX().catch(err => { console.error(err.message); process.exit(1); });
}
