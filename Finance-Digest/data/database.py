"""Async SQLite database layer using asyncio executor for non-blocking I/O."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from data.models import Company, InvestmentThesis

log = logging.getLogger(__name__)

_db_path: str = ""
_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name      TEXT,
    list_type TEXT NOT NULL CHECK(list_type IN ('portfolio','watchlist')),
    added_at  TEXT NOT NULL DEFAULT (datetime('now')),
    notes     TEXT
);

CREATE TABLE IF NOT EXISTS investment_thesis (
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

CREATE TABLE IF NOT EXISTS briefing_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    trigger_type    TEXT NOT NULL CHECK(trigger_type IN ('scheduled','manual')),
    channel_id      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('success','partial','failed')),
    tickers_covered TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     TEXT NOT NULL COLLATE NOCASE,
    data_type  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache ON analysis_cache(ticker, data_type, expires_at);

CREATE TABLE IF NOT EXISTS market_scan_log (
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

CREATE TABLE IF NOT EXISTS market_discoveries (
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

CREATE INDEX IF NOT EXISTS idx_discoveries_ticker ON market_discoveries(ticker, scanned_at);
CREATE INDEX IF NOT EXISTS idx_discoveries_scan   ON market_discoveries(scan_id);

CREATE TABLE IF NOT EXISTS paper_portfolio_state (
    id           INTEGER PRIMARY KEY CHECK(id = 1),
    cash         REAL    NOT NULL DEFAULT 10000.0,
    inception_at TEXT    NOT NULL DEFAULT (date('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS paper_trades (
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
CREATE INDEX IF NOT EXISTS idx_paper_trades_ticker ON paper_trades(ticker, traded_at);

CREATE TABLE IF NOT EXISTS paper_daily_value (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL UNIQUE,
    portfolio_value REAL    NOT NULL,
    cash            REAL    NOT NULL,
    invested        REAL    NOT NULL,
    recorded_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_paper_daily_value_date ON paper_daily_value(snapshot_date);

CREATE TABLE IF NOT EXISTS paper_daily_positions (
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
CREATE INDEX IF NOT EXISTS idx_paper_daily_positions_date ON paper_daily_positions(snapshot_date);

CREATE TABLE IF NOT EXISTS daily_discoveries (
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
CREATE INDEX IF NOT EXISTS idx_daily_disc_date ON daily_discoveries(date, score DESC);

CREATE TABLE IF NOT EXISTS paper_score_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker           TEXT    NOT NULL COLLATE NOCASE,
    score_date       TEXT    NOT NULL,
    score            INTEGER NOT NULL,
    price            REAL,
    piotroski_fscore INTEGER,
    signals          TEXT,
    recorded_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, score_date)
);
CREATE INDEX IF NOT EXISTS idx_score_history ON paper_score_history(ticker, score_date DESC);
"""


# ---------------------------------------------------------------------------
# Sync helpers (run in executor)
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_sync() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {result[0]}")
    log.info("Database initialized at %s", _db_path)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _init_sync)


async def backup_db() -> None:
    """Copy DB to .bak before each briefing."""
    loop = asyncio.get_event_loop()
    def _backup():
        src = Path(_db_path)
        if src.exists():
            shutil.copy2(src, src.with_suffix(".db.bak"))
    await loop.run_in_executor(None, _backup)


async def _run(fn, *args) -> Any:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


# --- Companies ---

async def add_company(ticker: str, list_type: str, name: str | None = None, notes: str | None = None) -> Company:
    def _add():
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO companies (ticker, name, list_type, notes) VALUES (?, ?, ?, ?)",
                (ticker.upper(), name, list_type, notes),
            )
            conn.execute(
                "UPDATE companies SET list_type=?, name=COALESCE(?, name), notes=COALESCE(?, notes) WHERE ticker=?",
                (list_type, name, notes, ticker.upper()),
            )
            row = conn.execute("SELECT * FROM companies WHERE ticker=?", (ticker.upper(),)).fetchone()
            return Company(ticker=row["ticker"], name=row["name"], list_type=row["list_type"],
                           added_at=row["added_at"], notes=row["notes"])
    return await _run(_add)


async def remove_company(ticker: str) -> bool:
    def _remove():
        with _connect() as conn:
            cur = conn.execute("DELETE FROM companies WHERE ticker=?", (ticker.upper(),))
            return cur.rowcount > 0
    return await _run(_remove)


async def get_all_companies() -> list[Company]:
    def _get():
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM companies ORDER BY list_type, ticker").fetchall()
            return [Company(ticker=r["ticker"], name=r["name"], list_type=r["list_type"],
                            added_at=r["added_at"], notes=r["notes"]) for r in rows]
    return await _run(_get)


async def get_companies_by_type(list_type: str) -> list[Company]:
    def _get():
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM companies WHERE list_type=? ORDER BY ticker", (list_type,)).fetchall()
            return [Company(ticker=r["ticker"], name=r["name"], list_type=r["list_type"],
                            added_at=r["added_at"], notes=r["notes"]) for r in rows]
    return await _run(_get)


async def get_company(ticker: str) -> Company | None:
    def _get():
        with _connect() as conn:
            row = conn.execute("SELECT * FROM companies WHERE ticker=?", (ticker.upper(),)).fetchone()
            if row:
                return Company(ticker=row["ticker"], name=row["name"], list_type=row["list_type"],
                               added_at=row["added_at"], notes=row["notes"])
            return None
    return await _run(_get)


async def update_company_name(ticker: str, name: str) -> None:
    def _upd():
        with _connect() as conn:
            conn.execute("UPDATE companies SET name=? WHERE ticker=?", (name, ticker.upper()))
    await _run(_upd)


# --- Investment Thesis ---

async def get_thesis(ticker: str) -> InvestmentThesis | None:
    def _get():
        with _connect() as conn:
            row = conn.execute("SELECT * FROM investment_thesis WHERE ticker=?", (ticker.upper(),)).fetchone()
            if row:
                return InvestmentThesis(
                    ticker=row["ticker"], strengths=row["strengths"], weaknesses=row["weaknesses"],
                    opportunities=row["opportunities"], threats=row["threats"], moat=row["moat"],
                    entry_rationale=row["entry_rationale"], target_price=row["target_price"],
                    questions=row["questions"], updated_at=row["updated_at"],
                )
            return None
    return await _run(_get)


async def upsert_thesis(thesis: InvestmentThesis) -> None:
    def _upsert():
        with _connect() as conn:
            conn.execute(
                """INSERT INTO investment_thesis
                   (ticker, strengths, weaknesses, opportunities, threats, moat,
                    entry_rationale, target_price, questions, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(ticker) DO UPDATE SET
                     strengths=excluded.strengths,
                     weaknesses=excluded.weaknesses,
                     opportunities=excluded.opportunities,
                     threats=excluded.threats,
                     moat=excluded.moat,
                     entry_rationale=excluded.entry_rationale,
                     target_price=excluded.target_price,
                     questions=excluded.questions,
                     updated_at=datetime('now')""",
                (thesis.ticker.upper(), thesis.strengths, thesis.weaknesses,
                 thesis.opportunities, thesis.threats, thesis.moat,
                 thesis.entry_rationale, thesis.target_price, thesis.questions),
            )
    await _run(_upsert)


# --- Briefing Log ---

async def log_briefing(channel_id: str, trigger_type: str, status: str,
                        tickers: list[str] | None = None, error: str | None = None) -> None:
    def _log():
        with _connect() as conn:
            conn.execute(
                "INSERT INTO briefing_log (trigger_type, channel_id, status, tickers_covered, error_message) VALUES (?,?,?,?,?)",
                (trigger_type, channel_id, status, json.dumps(tickers or []), error),
            )
    await _run(_log)


async def get_last_briefing_of_type(trigger_type: str) -> dict | None:
    def _get():
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM briefing_log WHERE trigger_type=? ORDER BY triggered_at DESC LIMIT 1",
                (trigger_type,),
            ).fetchone()
            return dict(row) if row else None
    return await _run(_get)


# --- Analysis Cache ---

async def get_cache(ticker: str, data_type: str) -> dict | None:
    def _get():
        with _connect() as conn:
            row = conn.execute(
                "SELECT payload FROM analysis_cache WHERE ticker=? AND data_type=? AND expires_at > datetime('now') ORDER BY fetched_at DESC LIMIT 1",
                (ticker.upper(), data_type),
            ).fetchone()
            return dict(row) if row else None
    return await _run(_get)


async def set_cache(ticker: str, data_type: str, payload_json: str, expires_at: str) -> None:
    def _set():
        with _connect() as conn:
            conn.execute(
                "INSERT INTO analysis_cache (ticker, data_type, payload, expires_at) VALUES (?,?,?,?)",
                (ticker.upper(), data_type, payload_json, expires_at),
            )
            # Clean up old entries for this ticker+type
            conn.execute(
                "DELETE FROM analysis_cache WHERE ticker=? AND data_type=? AND id NOT IN (SELECT id FROM analysis_cache WHERE ticker=? AND data_type=? ORDER BY fetched_at DESC LIMIT 3)",
                (ticker.upper(), data_type, ticker.upper(), data_type),
            )
    await _run(_set)


async def invalidate_cache(ticker: str) -> None:
    def _inv():
        with _connect() as conn:
            conn.execute("DELETE FROM analysis_cache WHERE ticker=?", (ticker.upper(),))
    await _run(_inv)


# --- Market Scanner ---

async def log_market_scan(
    trigger_type: str,
    tickers_scanned: int,
    stage1_passed: int,
    discoveries_found: int,
    top_tickers: list[str],
    duration_seconds: float,
    error: str | None = None,
) -> int:
    """Insert a scan log row and return the new row id."""
    def _log():
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO market_scan_log
                   (trigger_type, tickers_scanned, stage1_passed,
                    discoveries_found, top_tickers, duration_seconds, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trigger_type, tickers_scanned, stage1_passed,
                 discoveries_found, json.dumps(top_tickers),
                 round(duration_seconds, 1), error),
            )
            return cur.lastrowid
    return await _run(_log)


async def save_market_discoveries(scan_id: int, discoveries: list[dict]) -> None:
    def _save():
        with _connect() as conn:
            conn.executemany(
                """INSERT INTO market_discoveries
                   (scan_id, ticker, name, sector, score, signals, llm_evaluation)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (scan_id, d["ticker"], d.get("name"), d.get("sector"),
                     d["score"], json.dumps(d.get("signals", [])),
                     d.get("llm_evaluation"))
                    for d in discoveries
                ],
            )
    await _run(_save)


async def get_last_scan() -> dict | None:
    def _get():
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_scan_log ORDER BY scanned_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
    return await _run(_get)


async def get_scan_discoveries(scan_id: int) -> list[dict]:
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_discoveries WHERE scan_id=? ORDER BY score DESC",
                (scan_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    return await _run(_get)


async def mark_discovery_added(ticker: str) -> None:
    """Flag all discovery rows for this ticker as added to watchlist."""
    def _upd():
        with _connect() as conn:
            conn.execute(
                "UPDATE market_discoveries SET added_to_watchlist=1 WHERE ticker=?",
                (ticker.upper(),),
            )
    await _run(_upd)


# --- Daily Discoveries ---

async def clear_daily_discoveries(date: str) -> None:
    """Delete all daily_discoveries rows for the given date (YYYY-MM-DD). Used at 6am reset."""
    def _clear():
        with _connect() as conn:
            conn.execute("DELETE FROM daily_discoveries WHERE date=?", (date,))
    await _run(_clear)


async def upsert_daily_discovery(date: str, discovery: dict) -> None:
    """
    Insert or update a daily discovery. Merge rule: new score wins on tie-or-higher.
    If new_score < existing_score the row is left unchanged.
    llm_evaluation: keeps existing non-null value if new eval is null.
    """
    def _upsert():
        with _connect() as conn:
            conn.execute(
                """INSERT INTO daily_discoveries
                       (date, ticker, name, sector, score, signals, llm_evaluation)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date, ticker) DO UPDATE SET
                       score          = excluded.score,
                       signals        = excluded.signals,
                       llm_evaluation = COALESCE(excluded.llm_evaluation, daily_discoveries.llm_evaluation),
                       updated_at     = datetime('now')
                   WHERE excluded.score >= daily_discoveries.score""",
                (
                    date,
                    discovery["ticker"].upper(),
                    discovery.get("name"),
                    discovery.get("sector"),
                    discovery["score"],
                    json.dumps(discovery.get("signals", [])),
                    discovery.get("llm_evaluation"),
                ),
            )
    await _run(_upsert)


async def get_todays_discoveries(date: str) -> list[dict]:
    """Return all daily_discoveries for the given date, sorted by score descending."""
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_discoveries WHERE date=? ORDER BY score DESC",
                (date,),
            ).fetchall()
            return [dict(r) for r in rows]
    return await _run(_get)


async def get_daily_discovery_count(date: str) -> int:
    """Return number of discoveries stored for the given date."""
    def _count():
        with _connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM daily_discoveries WHERE date=?", (date,)
            ).fetchone()
            return row["cnt"] if row else 0
    return await _run(_count)


# --- Paper Trading ---

async def paper_ensure_initialized() -> None:
    """Create the singleton portfolio state row on first run. No-op thereafter."""
    def _init():
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO paper_portfolio_state (id, cash, inception_at) "
                "VALUES (1, 10000.0, date('now'))"
            )
            # Migration: add last_rebalance_at if not present
            try:
                conn.execute(
                    "ALTER TABLE paper_portfolio_state ADD COLUMN last_rebalance_at TEXT DEFAULT NULL"
                )
            except Exception:
                pass  # column already exists
            # Migration: add price to paper_score_history if not present
            try:
                conn.execute("ALTER TABLE paper_score_history ADD COLUMN price REAL")
            except Exception:
                pass  # column already exists
    await _run(_init)


async def paper_get_state() -> dict:
    """Return {cash, inception_at, updated_at}."""
    def _get():
        with _connect() as conn:
            row = conn.execute("SELECT * FROM paper_portfolio_state WHERE id=1").fetchone()
            return dict(row) if row else {"cash": 10000.0, "inception_at": "", "updated_at": ""}
    return await _run(_get)


async def paper_update_cash(new_cash: float) -> None:
    def _upd():
        with _connect() as conn:
            conn.execute(
                "UPDATE paper_portfolio_state SET cash=?, updated_at=datetime('now') WHERE id=1",
                (round(new_cash, 4),),
            )
    await _run(_upd)


async def paper_record_trade(
    ticker: str,
    action: str,
    shares: float,
    price: float,
    signals: list[str],
    score: int,
) -> None:
    def _rec():
        with _connect() as conn:
            conn.execute(
                "INSERT INTO paper_trades (ticker, action, shares, price, total_value, reason, score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker.upper(), action, round(shares, 4), round(price, 4),
                 round(shares * price, 4), json.dumps(signals), score),
            )
    await _run(_rec)


async def paper_get_positions() -> dict[str, float]:
    """Return {ticker: net_shares} for all currently open positions."""
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                """SELECT ticker,
                          SUM(CASE WHEN action='BUY' THEN shares ELSE -shares END) AS net_shares
                   FROM paper_trades
                   GROUP BY ticker
                   HAVING net_shares > 0.0001"""
            ).fetchall()
            return {r["ticker"]: r["net_shares"] for r in rows}
    return await _run(_get)


async def paper_get_entry_prices() -> dict[str, float]:
    """Return {ticker: weighted_avg_cost} for all tickers that have any BUY trades."""
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                """SELECT ticker,
                          SUM(shares * price) / SUM(shares) AS avg_cost
                   FROM paper_trades
                   WHERE action='BUY'
                   GROUP BY ticker"""
            ).fetchall()
            return {r["ticker"]: r["avg_cost"] for r in rows}
    return await _run(_get)


async def paper_record_daily_value(
    snapshot_date: str,
    portfolio_value: float,
    cash: float,
    invested: float,
) -> None:
    def _rec():
        with _connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO paper_daily_value
                   (snapshot_date, portfolio_value, cash, invested)
                   VALUES (?, ?, ?, ?)""",
                (snapshot_date, round(portfolio_value, 4),
                 round(cash, 4), round(invested, 4)),
            )
    await _run(_rec)


async def paper_get_daily_values(since_date: str | None = None) -> list[dict]:
    def _get():
        with _connect() as conn:
            if since_date:
                rows = conn.execute(
                    "SELECT * FROM paper_daily_value WHERE snapshot_date >= ? ORDER BY snapshot_date ASC",
                    (since_date,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM paper_daily_value ORDER BY snapshot_date ASC"
                ).fetchall()
            return [dict(r) for r in rows]
    return await _run(_get)


async def paper_record_daily_positions(
    snapshot_date: str,
    positions: list[dict],
) -> None:
    """Upsert per-ticker weights for one day. `positions` includes a 'CASH' entry."""
    def _rec():
        with _connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO paper_daily_positions
                   (snapshot_date, ticker, shares, price, position_value, weight_pct)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (snapshot_date, p["ticker"], p.get("shares", 0),
                     p.get("price", 0), round(p["position_value"], 4),
                     round(p["weight_pct"], 4))
                    for p in positions
                ],
            )
    await _run(_rec)


async def paper_get_all_trades() -> list[dict]:
    """Return full paper trade history sorted oldest first."""
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_trades ORDER BY traded_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]
    return await _run(_get)


async def paper_get_daily_positions(since_date: str | None = None) -> list[dict]:
    def _get():
        with _connect() as conn:
            if since_date:
                rows = conn.execute(
                    "SELECT * FROM paper_daily_positions WHERE snapshot_date >= ? ORDER BY snapshot_date ASC, weight_pct DESC",
                    (since_date,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM paper_daily_positions ORDER BY snapshot_date ASC, weight_pct DESC"
                ).fetchall()
            return [dict(r) for r in rows]
    return await _run(_get)


async def paper_get_position_highs() -> dict[str, float]:
    """Return {ticker: max_price_ever} from paper_daily_positions for all non-cash tickers."""
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                """SELECT ticker, MAX(price) AS high_price
                   FROM paper_daily_positions
                   WHERE ticker != 'CASH'
                   GROUP BY ticker"""
            ).fetchall()
            return {r["ticker"]: r["high_price"] for r in rows}
    return await _run(_get)


async def paper_update_rebalance_date(date_str: str) -> None:
    """Record the date of the most recent rebalance."""
    def _upd():
        with _connect() as conn:
            conn.execute(
                "UPDATE paper_portfolio_state SET last_rebalance_at=?, updated_at=datetime('now') WHERE id=1",
                (date_str,),
            )
    await _run(_upd)


async def paper_save_scores(date_str: str, scores: list) -> None:
    """Persist today's opportunity scores for all watchlist tickers to score history."""
    def _save():
        with _connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO paper_score_history
                   (ticker, score_date, score, price, piotroski_fscore, signals)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        s.ticker.upper(),
                        date_str,
                        s.score,
                        float(s.snapshot.quote.get("price")) if s.snapshot and s.snapshot.quote.get("price") else None,
                        s.piotroski_fscore,
                        json.dumps(s.signals),
                    )
                    for s in scores
                ],
            )
    await _run(_save)


async def paper_get_rolling_scores(days: int = 14) -> dict[str, dict]:
    """
    Return {ticker: {avg_score, data_points, trend, latest_score}} over the last N days.
    trend = latest score minus oldest score in the window (positive = improving).
    """
    def _get():
        with _connect() as conn:
            rows = conn.execute(
                """SELECT
                       ticker,
                       AVG(score)                                     AS avg_score,
                       COUNT(*)                                       AS data_points,
                       MAX(CASE WHEN score_date = (
                               SELECT MAX(score_date) FROM paper_score_history sh2
                               WHERE sh2.ticker = sh.ticker
                                 AND sh2.score_date >= date('now', ?)
                           ) THEN score END)                          AS latest_score,
                       MIN(CASE WHEN score_date = (
                               SELECT MIN(score_date) FROM paper_score_history sh3
                               WHERE sh3.ticker = sh.ticker
                                 AND sh3.score_date >= date('now', ?)
                           ) THEN score END)                          AS oldest_score
                   FROM paper_score_history sh
                   WHERE score_date >= date('now', ?)
                   GROUP BY ticker""",
                (f"-{days} days", f"-{days} days", f"-{days} days"),
            ).fetchall()
            result = {}
            for r in rows:
                latest = r["latest_score"] or 0
                oldest = r["oldest_score"] or latest
                result[r["ticker"]] = {
                    "avg_score":   r["avg_score"],
                    "data_points": r["data_points"],
                    "latest_score": latest,
                    "trend":       latest - oldest,
                }
            return result
    return await _run(_get)
