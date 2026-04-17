"""APScheduler task: autonomous market scan."""
from __future__ import annotations

import logging
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

import discord

import asyncio

from analysis.market_scanner import initialize_daily_discoveries, refresh_daily_discoveries
from analysis.paper_trader import run_paper_trading_session
from data import database
from formatters.discord_formatter import error_embed
from formatters.html_formatter import build_scan_html, build_portfolio_page_html
from utils.config import config
from web import server as web_server

log = logging.getLogger(__name__)

_SITE_DIR = Path(__file__).parent.parent.parent.parent / "site-generator"
_SITE_DB  = _SITE_DIR / "data.db"


def _register_scan(date_key: str) -> None:
    """Register the scan in data.db and trigger an index rebuild."""
    slug = f"scan-{date_key}"
    title = f"Market Scan — {datetime.utcnow().strftime('%B %d, %Y')}"
    try:
        conn = sqlite3.connect(_SITE_DB)
        conn.execute(
            """
            INSERT INTO posts (slug, title, body, updated_at)
            VALUES (?, ?, '', datetime('now'))
            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (slug, title),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[market_scan] DB register failed for %s: %s", slug, e)
        return
    try:
        subprocess.Popen(
            ["node", "src/build.js", f"--slug={slug}"],
            cwd=_SITE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("[market_scan] Triggered index rebuild for: %s", slug)
    except Exception as e:
        log.warning("[market_scan] Build trigger failed for %s: %s", slug, e)

# Injected by bot/client.py on startup
_bot: discord.Client | None = None


def set_bot(bot: discord.Client) -> None:
    global _bot
    _bot = bot


async def _get_channel():
    channel = _bot.get_channel(config.briefing_channel_id)
    if channel is None:
        channel = await _bot.fetch_channel(config.briefing_channel_id)
    return channel


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


async def _rebuild_portfolio_page() -> None:
    """Rebuild portfolio.html from current DB state. Called after any paper trading session."""
    try:
        date_key = _today()
        paper_state   = await database.paper_get_state()
        entry_prices  = await database.paper_get_entry_prices()
        daily_values  = await database.paper_get_daily_values()
        all_trades    = await database.paper_get_all_trades()
        all_pos_today = await database.paper_get_daily_positions(since_date=date_key)
        positions_today = [p for p in all_pos_today if p["snapshot_date"] == date_key]
        cash_pct = next(
            (p["weight_pct"] for p in positions_today if p["ticker"] == "CASH"), 100.0
        )
        portfolio_data = {
            "state":         paper_state,
            "positions":     [p for p in positions_today if p["ticker"] != "CASH"],
            "cash_pct":      cash_pct,
            "daily_values":  daily_values,
            "recent_trades": all_trades,
            "entry_prices":  entry_prices,
        }
        html = build_portfolio_page_html(
            portfolio_data, updated_at=datetime.utcnow().strftime("%B %d, %Y")
        )
        web_server.save_portfolio_page(html)
        log.info("[market_scan] Portfolio page rebuilt")
    except Exception as e:
        log.warning("[market_scan] Portfolio page rebuild failed: %s", e)


async def run_daily_init() -> None:
    """6am scheduler task: reset and initialize today's discoveries."""
    if _bot is None:
        log.error("[market_scan] Bot not set")
        return

    try:
        channel = await _get_channel()
    except Exception as e:
        log.error("[market_scan] Cannot find channel %d: %s", config.briefing_channel_id, e)
        return

    date_str = datetime.utcnow().strftime("%B %d, %Y")
    date_key = _today()

    try:
        discoveries = await initialize_daily_discoveries(date_key)

        scan = await database.get_last_scan()
        scan_stats = scan or {}

        top_n = config.market_scan_top_n
        top_discoveries = discoveries[:top_n]

        report_html = build_scan_html(top_discoveries, scan_stats)
        web_server.save_report(report_html, date_key)
        _register_scan(date_key)
        url = web_server.report_url(config.scan_report_base_url)

        await channel.send(
            f"**Daily Discoveries Initialized — {date_str}** — "
            f"{len(discoveries)} discovery(ies) found. "
            f"Use `/view-todays-discoveries` to see the list.\n{url}"
        )

        trading_lines = await run_paper_trading_session(discoveries)
        if trading_lines:
            await channel.send("**Paper Portfolio Update:**\n" + "\n".join(trading_lines))
        await _rebuild_portfolio_page()

    except Exception as e:
        log.error("[market_scan] Fatal error in daily init: %s", e, exc_info=True)
        try:
            await channel.send(embed=error_embed(
                f"Daily discovery init failed: {e}", title="Market Scan Error"
            ))
        except Exception:
            pass


async def run_refresh() -> None:
    """Manual refresh: scan new tickers and merge into today's discoveries."""
    if _bot is None:
        log.error("[market_scan] Bot not set")
        return

    try:
        channel = await _get_channel()
    except Exception as e:
        log.error("[market_scan] Cannot find channel %d: %s", config.briefing_channel_id, e)
        return

    date_str = datetime.utcnow().strftime("%B %d, %Y")
    date_key = _today()

    try:
        new_results, total = await refresh_daily_discoveries(date_key)

        scan = await database.get_last_scan()
        scan_stats = scan or {}

        top_n = config.market_scan_top_n
        all_today = await database.get_todays_discoveries(date_key)
        # Rebuild OpportunityScore-like view for HTML formatter using today's merged list
        top_discoveries = new_results[:top_n]

        report_html = build_scan_html(top_discoveries, scan_stats)
        web_server.save_report(report_html, date_key)
        _register_scan(date_key)
        url = web_server.report_url(config.scan_report_base_url)

        await channel.send(
            f"**Discoveries Refreshed — {date_str}** — "
            f"{len(new_results)} tickers scanned, today's list now has {total} total.\n{url}"
        )

        trading_lines = await run_paper_trading_session(new_results)
        if trading_lines:
            await channel.send("**Paper Portfolio Update:**\n" + "\n".join(trading_lines))
        await _rebuild_portfolio_page()

    except Exception as e:
        log.error("[market_scan] Fatal error in refresh: %s", e, exc_info=True)
        try:
            await channel.send(embed=error_embed(
                f"Discovery refresh failed: {e}", title="Market Scan Error"
            ))
        except Exception:
            pass


async def run_view_discoveries(interaction: discord.Interaction) -> None:
    """View-only: return today's merged discoveries list to the interaction."""
    date_key = _today()
    date_str = datetime.utcnow().strftime("%B %d, %Y")

    discoveries = await database.get_todays_discoveries(date_key)

    if not discoveries:
        await interaction.followup.send(
            f"No discoveries for today ({date_str}) yet. "
            "They initialize automatically at 6am, or use `/refresh-todays-discoveries` to run one now."
        )
        return

    # Format a compact text list for Discord
    lines = [f"**Today's Discoveries — {date_str}** ({len(discoveries)} total)\n"]
    for rank, d in enumerate(discoveries, start=1):
        score = d["score"]
        ticker = d["ticker"]
        name = d.get("name") or ticker
        lines.append(f"`#{rank}` **{ticker}** — {name} | Score: {score}/15")

    # Discord message limit is 2000 chars; chunk if needed
    message = "\n".join(lines)
    if len(message) <= 2000:
        await interaction.followup.send(message)
    else:
        # Send in chunks
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await interaction.followup.send(chunk)
                chunk = line
            else:
                chunk = chunk + "\n" + line if chunk else line
        if chunk:
            await interaction.followup.send(chunk)


# Keep legacy name for any external callers that may reference it
async def run_market_scan(trigger_type: str = "scheduled") -> None:
    """Deprecated shim — routes to run_daily_init or run_refresh."""
    if trigger_type == "scheduled":
        await run_daily_init()
    else:
        await run_refresh()
