"""Write HTML pages to site-generator/public/ so Express serves them at localhost:3000."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Path to the Express static-file directory (sibling project)
_PUBLIC_DIR = Path(__file__).parent.parent.parent / "site-generator" / "public"

# Track the most recent scan/briefing date for URL helpers
_latest_scan_date: str = ""
_latest_briefing_key: str = ""


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Scan reports
# ---------------------------------------------------------------------------

def save_report(html: str, date_str: str) -> None:
    global _latest_scan_date
    _write(_PUBLIC_DIR / "posts" / f"scan-{date_str}.html", html)
    _latest_scan_date = date_str
    log.info("[web] Scan report written for %s", date_str)


def report_url(base_url: str, date_str: str = "") -> str:
    key = date_str or _latest_scan_date or datetime.utcnow().strftime("%Y-%m-%d")
    return f"{base_url.rstrip('/')}/posts/scan-{key}.html"


# ---------------------------------------------------------------------------
# Daily briefings
# ---------------------------------------------------------------------------

def save_briefing(html: str, date_str: str) -> None:
    global _latest_briefing_key
    _write(_PUBLIC_DIR / f"briefing-{date_str}.html", html)
    _latest_briefing_key = date_str
    log.info("[web] Briefing written for %s", date_str)


def briefing_url(base_url: str, path: str = "latest") -> str:
    if path == "latest":
        key = _latest_briefing_key or datetime.utcnow().strftime("%Y-%m-%d")
    else:
        key = path
    return f"{base_url.rstrip('/')}/briefing-{key}.html"


# ---------------------------------------------------------------------------
# Portfolio dashboard
# ---------------------------------------------------------------------------

def save_portfolio_page(html: str) -> None:
    # portfolio.html is now a dynamic Alpine.js/Chart.js page served by the
    # Node site-generator; Python writes data to finance_digest.db instead.
    log.info("[web] Portfolio page skipped (dynamic page owns portfolio.html)")


def portfolio_page_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/portfolio.html"


# ---------------------------------------------------------------------------
# Analysis pages  (/analyze command)
# ---------------------------------------------------------------------------

def save_analysis(html: str, slug: str) -> None:
    _write(_PUBLIC_DIR / "posts" / f"{slug}.html", html)
    log.info("[web] Analysis written for %s", slug)


def analysis_url(base_url: str, slug: str) -> str:
    return f"{base_url.rstrip('/')}/posts/{slug}.html"


def get_existing_analysis_url(slug: str, max_age_hours: int, base_url: str) -> str | None:
    """Return the URL if a fresh analysis for this slug exists on disk, else None."""
    path = _PUBLIC_DIR / "posts" / f"{slug}.html"
    if not path.exists():
        return None
    age_hours = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600
    if age_hours <= max_age_hours:
        return analysis_url(base_url, slug)
    return None
