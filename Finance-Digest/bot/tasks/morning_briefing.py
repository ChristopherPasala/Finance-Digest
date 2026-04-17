"""APScheduler tasks: daily watchlist briefing + weekly portfolio deep dive."""
from __future__ import annotations

import logging
from datetime import datetime

import discord

from analysis.briefing_builder import build_daily_briefing, build_portfolio_briefing
from data import database
from formatters.discord_formatter import error_embed
from formatters.html_formatter import build_briefing_html, build_portfolio_page_html
from utils.config import config
from web import server as web_server

log = logging.getLogger(__name__)

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


async def run_morning_briefing(trigger_type: str = "scheduled") -> None:
    """Daily watchlist briefing — runs every morning."""
    if _bot is None:
        log.error("[daily] Bot not set")
        return

    try:
        channel = await _get_channel()
    except Exception as e:
        log.error("[daily] Cannot find channel %d: %s", config.briefing_channel_id, e)
        return

    await database.backup_db()

    tickers_covered: list[str] = []
    status = "success"
    error_msg = None

    try:
        sections = await build_daily_briefing(trigger_type=trigger_type)

        date_str = datetime.utcnow().strftime("%B %d, %Y")
        companies = await database.get_all_companies()
        tickers_covered = [c.ticker for c in companies if c.list_type == "watchlist"]
        watchlist_count = len(tickers_covered)

        title = f"Daily Briefing — {date_str}"
        subtitle = f"Watchlist: {watchlist_count} companies"

        # Publish briefing as a web article
        today_key = datetime.utcnow().strftime("%Y-%m-%d")
        briefing_html = build_briefing_html(sections, title=title, subtitle=subtitle)
        web_server.save_briefing(briefing_html, today_key)
        briefing_url = web_server.briefing_url(config.scan_report_base_url)

        # Build and save the paper portfolio dashboard
        paper_state    = await database.paper_get_state()
        entry_prices   = await database.paper_get_entry_prices()
        daily_values   = await database.paper_get_daily_values()
        all_trades     = await database.paper_get_all_trades()
        all_pos_today  = await database.paper_get_daily_positions(since_date=today_key)
        positions_today = [p for p in all_pos_today if p["snapshot_date"] == today_key]
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
        portfolio_html = build_portfolio_page_html(
            portfolio_data, updated_at=date_str
        )
        web_server.save_portfolio_page(portfolio_html)
        portfolio_url = web_server.portfolio_page_url(config.scan_report_base_url)

        await channel.send(
            f"Good morning! Your **{date_str}** watchlist briefing is ready.\n"
            f"Briefing: {briefing_url}  |  Portfolio: {portfolio_url}"
        )

    except Exception as e:
        log.error("[daily] Fatal error: %s", e, exc_info=True)
        status = "failed"
        error_msg = str(e)
        try:
            await channel.send(embed=error_embed(
                f"Daily briefing failed: {e}", title="Briefing Error"
            ))
        except Exception:
            pass

    await database.log_briefing(
        channel_id=str(config.briefing_channel_id),
        trigger_type=trigger_type,
        status=status,
        tickers=tickers_covered,
        error=error_msg,
    )
    log.info("[daily] Completed — status: %s", status)


async def run_portfolio_briefing(trigger_type: str = "scheduled") -> None:
    """Weekly portfolio deep dive — runs once a week."""
    if _bot is None:
        log.error("[portfolio] Bot not set")
        return

    try:
        channel = await _get_channel()
    except Exception as e:
        log.error("[portfolio] Cannot find channel %d: %s", config.briefing_channel_id, e)
        return

    tickers_covered: list[str] = []
    status = "success"
    error_msg = None

    try:
        sections = await build_portfolio_briefing(trigger_type=trigger_type)

        date_str = datetime.utcnow().strftime("%B %d, %Y")
        companies = await database.get_all_companies()
        tickers_covered = [c.ticker for c in companies if c.list_type == "portfolio"]
        portfolio_count = len(tickers_covered)

        title = f"Weekly Portfolio Deep Dive — {date_str}"
        subtitle = f"Portfolio: {portfolio_count} companies"

        # Publish the deep-dive as a web article
        today_key = f"portfolio-{datetime.utcnow().strftime('%Y-%m-%d')}"
        briefing_html = build_briefing_html(sections, title=title, subtitle=subtitle)
        web_server.save_briefing(briefing_html, today_key)
        briefing_url = web_server.briefing_url(config.scan_report_base_url, today_key)
        portfolio_url = web_server.portfolio_page_url(config.scan_report_base_url)

        await channel.send(
            f"Your **weekly portfolio deep dive** for {date_str} is ready.\n"
            f"Deep dive: {briefing_url}  |  Portfolio: {portfolio_url}"
        )

    except Exception as e:
        log.error("[portfolio] Fatal error: %s", e, exc_info=True)
        status = "failed"
        error_msg = str(e)
        try:
            await channel.send(embed=error_embed(
                f"Portfolio briefing failed: {e}", title="Briefing Error"
            ))
        except Exception:
            pass

    await database.log_briefing(
        channel_id=str(config.briefing_channel_id),
        trigger_type=trigger_type,
        status=status,
        tickers=tickers_covered,
        error=error_msg,
    )
    log.info("[portfolio] Completed — status: %s", status)
