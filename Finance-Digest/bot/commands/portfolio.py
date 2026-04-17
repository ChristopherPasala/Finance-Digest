"""Slash commands: /add, /remove, /list."""
from __future__ import annotations

import logging
import re

import discord
from discord import app_commands

from data import database
from formatters.discord_formatter import error_embed, success_embed

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


class PortfolioCog(app_commands.Group):
    """Portfolio management commands."""

    def __init__(self):
        super().__init__(name="portfolio", description="Manage your tracked companies")

    @app_commands.command(name="add", description="Add a company to your portfolio or watchlist")
    @app_commands.describe(
        ticker="Stock ticker symbol (e.g. AAPL)",
        list_type="Add to portfolio or watchlist",
    )
    @app_commands.choices(list_type=[
        app_commands.Choice(name="Portfolio (I own this)", value="portfolio"),
        app_commands.Choice(name="Watchlist (monitoring)", value="watchlist"),
    ])
    async def add(self, interaction: discord.Interaction, ticker: str,
                  list_type: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)
        ticker = ticker.upper().strip()

        if not TICKER_RE.match(ticker):
            await interaction.followup.send(embed=error_embed(
                f"'{ticker}' is not a valid ticker. Use 1-5 uppercase letters (e.g. AAPL, NVDA)."
            ))
            return

        lt = list_type.value if list_type else "watchlist"

        # Validate ticker exists via yfinance
        name = None
        try:
            import yfinance as yf
            loop = __import__("asyncio").get_event_loop()
            info = await loop.run_in_executor(None, lambda: yf.Ticker(ticker).info)
            name = info.get("shortName") or info.get("longName")
            if not name:
                await interaction.followup.send(embed=error_embed(
                    f"Could not verify ticker **{ticker}**. Make sure it's a valid US stock symbol."
                ))
                return
        except Exception as e:
            log.warning("Could not verify ticker %s: %s", ticker, e)
            # Allow it through with a warning
            name = ticker

        company = await database.add_company(ticker, lt, name=name)
        emoji = "📈" if lt == "portfolio" else "👀"
        await interaction.followup.send(embed=success_embed(
            f"{emoji} **{ticker}** ({name}) added to your **{lt}**.",
            title="Company Added",
        ))
        log.info("Added %s to %s", ticker, lt)

    @app_commands.command(name="remove", description="Remove a company from tracking")
    @app_commands.describe(ticker="Stock ticker to remove")
    async def remove(self, interaction: discord.Interaction, ticker: str):
        await interaction.response.defer(thinking=True)
        ticker = ticker.upper().strip()
        company = await database.get_company(ticker)
        if not company:
            await interaction.followup.send(embed=error_embed(
                f"**{ticker}** is not in your portfolio or watchlist."
            ))
            return

        await database.remove_company(ticker)
        await interaction.followup.send(embed=success_embed(
            f"**{ticker}** ({company.name or ticker}) removed from your {company.list_type}.",
            title="Company Removed",
        ))

    @app_commands.command(name="list", description="Show all tracked companies")
    async def list_companies(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        companies = await database.get_all_companies()
        if not companies:
            await interaction.followup.send(embed=error_embed(
                "No companies tracked yet. Use `/portfolio add TICKER` to get started."
            ))
            return

        embed = discord.Embed(title="Tracked Companies", color=discord.Color.blurple().value)

        portfolio = [c for c in companies if c.list_type == "portfolio"]
        watchlist = [c for c in companies if c.list_type == "watchlist"]

        if portfolio:
            port_lines = "\n".join(
                f"• **{c.ticker}** — {c.name or 'Unknown'} (added {c.added_at[:10]})"
                for c in portfolio
            )
            embed.add_field(name="📈 Portfolio", value=port_lines[:1024], inline=False)

        if watchlist:
            watch_lines = "\n".join(
                f"• **{c.ticker}** — {c.name or 'Unknown'} (added {c.added_at[:10]})"
                for c in watchlist
            )
            embed.add_field(name="👀 Watchlist", value=watch_lines[:1024], inline=False)

        embed.set_footer(text=f"Total: {len(companies)} companies")
        await interaction.followup.send(embed=embed)


# Standalone slash commands (not in a group, for easier Discord access)

@app_commands.command(name="add", description="Add a stock to your portfolio or watchlist")
@app_commands.describe(
    ticker="Stock ticker symbol (e.g. AAPL)",
    list_type="Portfolio (owned) or Watchlist (monitoring)",
)
@app_commands.choices(list_type=[
    app_commands.Choice(name="Portfolio", value="portfolio"),
    app_commands.Choice(name="Watchlist", value="watchlist"),
])
async def cmd_add(interaction: discord.Interaction, ticker: str,
                   list_type: app_commands.Choice[str] = None):
    await _add_company(interaction, ticker, list_type.value if list_type else "watchlist")


@app_commands.command(name="remove", description="Remove a stock from tracking")
@app_commands.describe(ticker="Stock ticker to remove")
async def cmd_remove(interaction: discord.Interaction, ticker: str):
    await interaction.response.defer(thinking=True)
    ticker = ticker.upper().strip()
    company = await database.get_company(ticker)
    if not company:
        await interaction.followup.send(embed=error_embed(f"**{ticker}** is not being tracked."))
        return
    await database.remove_company(ticker)
    await interaction.followup.send(embed=success_embed(
        f"**{ticker}** removed from your {company.list_type}.", title="Removed"
    ))


@app_commands.command(name="list", description="Show tracked stocks")
@app_commands.describe(filter="Show only portfolio, only watchlist, or both (default)")
@app_commands.choices(filter=[
    app_commands.Choice(name="Portfolio", value="portfolio"),
    app_commands.Choice(name="Watchlist", value="watchlist"),
    app_commands.Choice(name="All", value="all"),
])
async def cmd_list(interaction: discord.Interaction, filter: app_commands.Choice[str] = None):
    await interaction.response.defer(thinking=True)
    companies = await database.get_all_companies()
    if not companies:
        await interaction.followup.send(embed=error_embed(
            "No companies tracked. Use `/add TICKER` to start."
        ))
        return

    scope = filter.value if filter else "all"
    portfolio = [c for c in companies if c.list_type == "portfolio"]
    watchlist = [c for c in companies if c.list_type == "watchlist"]

    if scope == "portfolio":
        title, color = "📈 Portfolio", discord.Color.green().value
    elif scope == "watchlist":
        title, color = "👀 Watchlist", discord.Color.blurple().value
    else:
        title, color = "Tracked Companies", discord.Color.blurple().value

    embed = discord.Embed(title=title, color=color)

    if scope in ("portfolio", "all") and portfolio:
        embed.add_field(
            name="📈 Portfolio",
            value="\n".join(f"• **{c.ticker}** — {c.name or '—'}" for c in portfolio)[:1024],
            inline=False,
        )
    if scope in ("watchlist", "all") and watchlist:
        embed.add_field(
            name="👀 Watchlist",
            value="\n".join(f"• **{c.ticker}** — {c.name or '—'}" for c in watchlist)[:1024],
            inline=False,
        )

    shown = portfolio if scope == "portfolio" else watchlist if scope == "watchlist" else companies
    embed.set_footer(text=f"{len(shown)} companies")
    await interaction.followup.send(embed=embed)


async def _add_company(interaction: discord.Interaction, ticker: str, list_type: str):
    await interaction.response.defer(thinking=True)
    ticker = ticker.upper().strip()
    if not TICKER_RE.match(ticker):
        await interaction.followup.send(embed=error_embed(
            f"'{ticker}' is not a valid ticker symbol."
        ))
        return

    name = None
    try:
        import yfinance as yf
        import asyncio
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: yf.Ticker(ticker).info)
        name = info.get("shortName") or info.get("longName")
        if not name:
            await interaction.followup.send(embed=error_embed(
                f"Could not verify **{ticker}** as a valid ticker."
            ))
            return
    except Exception as e:
        log.warning("Ticker validation failed for %s: %s", ticker, e)
        name = ticker

    await database.add_company(ticker, list_type, name=name)
    emoji = "📈" if list_type == "portfolio" else "👀"
    await interaction.followup.send(embed=success_embed(
        f"{emoji} **{ticker}** ({name}) added to **{list_type}**.", title="Added"
    ))


STANDALONE_COMMANDS = [cmd_add, cmd_remove, cmd_list]
