"""Finviz data collector — fills blind spots not covered by free-tier APIs.

Provides: P/S ratio, ROIC (via ROI), analyst recommendation/target,
insider transactions, and peer comparison tables via industry screener.
No API key required; finvizfinance scrapes Finviz directly.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


def _parse_pct(val) -> float | None:
    """Parse a Finviz percent string like '12.50%' or '-3.20%' to float."""
    if not val or val == '-':
        return None
    try:
        return float(str(val).replace('%', '').replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def _parse_float(val) -> float | None:
    """Parse a Finviz numeric string, handling B/M/K suffixes."""
    if not val or val == '-':
        return None
    try:
        s = str(val).replace(',', '').strip()
        if s.endswith('B'):
            return float(s[:-1]) * 1e9
        if s.endswith('M'):
            return float(s[:-1]) * 1e6
        if s.endswith('K'):
            return float(s[:-1]) * 1e3
        return float(s)
    except (ValueError, TypeError):
        return None


def _recom_label(val) -> str | None:
    """Convert Finviz numeric consensus (1=Strong Buy … 5=Strong Sell) to label."""
    v = _parse_float(val)
    if v is None:
        return None
    if v <= 1.5:
        return "Strong Buy"
    if v <= 2.5:
        return "Buy"
    if v <= 3.5:
        return "Hold"
    if v <= 4.5:
        return "Sell"
    return "Strong Sell"


class FinvizCollector:
    """Synchronous Finviz collector. Wrap calls with asyncio.to_thread in async code."""

    # ------------------------------------------------------------------
    # Core fundamentals
    # ------------------------------------------------------------------

    def get_fundamentals(self, ticker: str) -> dict:
        """Return a cleaned dict of supplemental fundamentals for one ticker."""
        try:
            from finvizfinance.quote import finvizfinance
            f = finvizfinance(ticker).ticker_fundament()
            return {
                'price_to_sales':      _parse_float(f.get('P/S')),
                'roic':                _parse_pct(f.get('ROI')),
                'recommendation':      _recom_label(f.get('Recom')),
                'analyst_target_mean': _parse_float(f.get('Target Price')),
                'insider_ownership':   _parse_pct(f.get('Insider Own')),
                'insider_trans_pct':   _parse_pct(f.get('Insider Trans')),
                'short_float':         _parse_pct(f.get('Short Float')),
                'inst_ownership':      _parse_pct(f.get('Inst Own')),
            }
        except Exception as e:
            log.warning("[finviz] get_fundamentals(%s) failed: %s", ticker, e)
            return {}

    # ------------------------------------------------------------------
    # Insider transactions
    # ------------------------------------------------------------------

    def get_insider_transactions(self, ticker: str) -> list[dict]:
        """Return recent insider buy/sell transactions as a list of dicts."""
        try:
            from finvizfinance.quote import finvizfinance
            df = finvizfinance(ticker).ticker_inside_trader()
            if df is None or df.empty:
                return []
            rows = []
            for _, row in df.iterrows():
                rows.append({
                    'owner':        str(row.get('Insider Trading', '')).strip(),
                    'relationship': str(row.get('Relationship', '')).strip(),
                    'date':         str(row.get('Date', '')).strip(),
                    'transaction':  str(row.get('Transaction', '')).strip(),
                    'shares':       int(row['#Shares']) if row.get('#Shares') else 0,
                    'value':        float(row['Value ($)']) if row.get('Value ($)') else 0.0,
                })
            return rows
        except Exception as e:
            log.warning("[finviz] get_insider_transactions(%s) failed: %s", ticker, e)
            return []

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    def get_news(self, ticker: str, limit: int = 20) -> list[dict]:
        """Return recent news articles from Finviz for the ticker."""
        try:
            from finvizfinance.quote import finvizfinance
            df = finvizfinance(ticker).ticker_news()
            if df is None or df.empty:
                return []
            articles = []
            for _, row in df.head(limit).iterrows():
                date_val = row.get('Date', '')
                try:
                    published_at = str(date_val)[:10] if date_val else ''
                except Exception:
                    published_at = ''
                articles.append({
                    'title':        str(row.get('Title', '')).strip(),
                    'url':          str(row.get('Link', '')).strip(),
                    'source':       str(row.get('Source', 'Finviz')).strip(),
                    'published_at': published_at,
                })
            return articles
        except Exception as e:
            log.warning("[finviz] get_news(%s) failed: %s", ticker, e)
            return []

    # ------------------------------------------------------------------
    # Peer comparison
    # ------------------------------------------------------------------

    def get_peers(self, ticker: str, sector: str = "", industry: str = "",
                  limit: int = 6) -> list[dict]:
        """
        Fetch Finviz's curated peer list for a ticker, then pull key
        fundamentals for each peer. Returns up to `limit` peers.
        """
        try:
            from finvizfinance.quote import finvizfinance as fvf

            peer_tickers = fvf(ticker).ticker_peer()
            if not peer_tickers:
                return []
            peer_tickers = [p for p in peer_tickers if p.upper() != ticker.upper()][:limit]

            peers: list[dict] = []
            for pt in peer_tickers:
                try:
                    time.sleep(0.4)   # respect Finviz rate limits
                    f = fvf(pt).ticker_fundament()
                    peers.append({
                        'ticker':       pt,
                        'name':         f.get('Company', pt),
                        'pe':           _parse_float(f.get('P/E')),
                        'ps':           _parse_float(f.get('P/S')),
                        'pb':           _parse_float(f.get('P/B')),
                        'roi':          _parse_pct(f.get('ROI')),
                        'gross_margin': _parse_pct(f.get('Gross Margin')),
                        'market_cap':   f.get('Market Cap', ''),
                    })
                except Exception as pe_err:
                    log.debug("[finviz] peer %s failed: %s", pt, pe_err)
            return peers
        except Exception as e:
            log.warning("[finviz] get_peers(%s) failed: %s", ticker, e)
            return []


finviz_collector = FinvizCollector()
