const Database = require('better-sqlite3');
const path = require('path');

const DB_PATH = path.join(__dirname, '..', 'data.db');

let db;

function getDb() {
  if (!db) {
    db = new Database(DB_PATH);
    db.exec(`
      CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS paper_portfolio_state (
        id INTEGER PRIMARY KEY,
        nav REAL,
        total_return_pct REAL,
        invested REAL,
        cash REAL,
        start_date TEXT,
        updated_at TEXT
      );

      CREATE TABLE IF NOT EXISTS paper_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT UNIQUE,
        shares REAL,
        current_price REAL,
        cost_basis REAL,
        updated_at TEXT
      );

      CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        action TEXT,
        ticker TEXT,
        shares REAL,
        price REAL,
        total REAL,
        reason TEXT
      );

      CREATE TABLE IF NOT EXISTS paper_daily_value (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT UNIQUE,
        nav REAL
      );

      CREATE TABLE IF NOT EXISTS market_benchmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        close_price REAL NOT NULL,
        UNIQUE(ticker, snapshot_date)
      );
    `);
    seedPortfolioData(db);
  }
  return db;
}

function seedPortfolioData(db) {
  const existing = db.prepare('SELECT id FROM paper_portfolio_state WHERE id=1').get();
  if (existing) return;

  db.prepare(`
    INSERT INTO paper_portfolio_state (id, nav, total_return_pct, invested, cash, start_date, updated_at)
    VALUES (1, 10138.10, 1.4, 2135.83, 8002.27, '2026-03-30', '2026-04-10')
  `).run();

  const insertPosition = db.prepare(`
    INSERT OR IGNORE INTO paper_positions (ticker, shares, current_price, cost_basis, updated_at)
    VALUES (@ticker, @shares, @current_price, @cost_basis, '2026-04-10')
  `);
  insertPosition.run({ ticker: 'MU',   shares: 2.6424, current_price: 421.51, cost_basis: 997.72 });
  insertPosition.run({ ticker: 'AMGN', shares: 2.8741, current_price: 355.60, cost_basis: 1000.01 });

  const insertTrade = db.prepare(`
    INSERT INTO paper_trades (date, action, ticker, shares, price, total, reason)
    VALUES (@date, @action, @ticker, @shares, @price, @total, @reason)
  `);
  insertTrade.run({ date: '2026-04-08', action: 'BUY', ticker: 'MU',   shares: 2.6424, price: 377.58, total: 997.72,  reason: 'RSI oversold (29.3), Earnings beat +27.3%' });
  insertTrade.run({ date: '2026-04-04', action: 'BUY', ticker: 'AMGN', shares: 2.8741, price: 347.94, total: 1000.01, reason: 'RSI oversold (28.4), Earnings beat +9.6%' });

  const insertDay = db.prepare(`INSERT OR IGNORE INTO paper_daily_value (snapshot_date, nav) VALUES (@d, @n)`);
  const history = [
    { d: '2026-03-30', n: 10000.00 },
    { d: '2026-03-31', n: 10000.00 },
    { d: '2026-04-01', n: 10000.00 },
    { d: '2026-04-02', n: 10000.00 },
    { d: '2026-04-03', n: 10000.00 },
    { d: '2026-04-04', n: 10000.00 },
    { d: '2026-04-05', n: 10000.00 },
    { d: '2026-04-06', n: 10000.00 },
    { d: '2026-04-07', n:  9984.64 },
    { d: '2026-04-08', n:  9977.28 },
    { d: '2026-04-09', n: 10138.10 },
    { d: '2026-04-10', n: 10138.10 },
  ];
  for (const row of history) insertDay.run(row);
}

function getAllPosts() {
  return getDb().prepare('SELECT * FROM posts ORDER BY updated_at DESC').all();
}

function getPostBySlug(slug) {
  return getDb().prepare('SELECT * FROM posts WHERE slug = ?').get(slug);
}

function upsertPost({ slug, title, body }) {
  getDb().prepare(`
    INSERT INTO posts (slug, title, body, updated_at)
    VALUES (@slug, @title, @body, datetime('now'))
    ON CONFLICT(slug) DO UPDATE SET
      title = excluded.title,
      body = excluded.body,
      updated_at = excluded.updated_at
  `).run({ slug, title, body });
}

function getPortfolioState() {
  return getDb().prepare('SELECT * FROM paper_portfolio_state WHERE id=1').get();
}

function getPositions() {
  return getDb().prepare('SELECT * FROM paper_positions ORDER BY ticker').all();
}

function getTrades() {
  return getDb().prepare('SELECT * FROM paper_trades ORDER BY date DESC').all();
}

function getDailyHistory() {
  return getDb().prepare('SELECT snapshot_date, nav FROM paper_daily_value ORDER BY snapshot_date ASC').all();
}

function getBenchmarkHistory(ticker) {
  return getDb().prepare(
    'SELECT snapshot_date, close_price FROM market_benchmarks WHERE ticker = ? ORDER BY snapshot_date ASC'
  ).all(ticker);
}

function upsertBenchmark({ ticker, snapshot_date, close_price }) {
  getDb().prepare(`
    INSERT INTO market_benchmarks (ticker, snapshot_date, close_price)
    VALUES (@ticker, @snapshot_date, @close_price)
    ON CONFLICT(ticker, snapshot_date) DO UPDATE SET close_price = excluded.close_price
  `).run({ ticker, snapshot_date, close_price });
}

module.exports = { getAllPosts, getPostBySlug, upsertPost, getPortfolioState, getPositions, getTrades, getDailyHistory, getBenchmarkHistory, upsertBenchmark };
