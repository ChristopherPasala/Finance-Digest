"""Slash command: /analyze"""
from __future__ import annotations

import logging

import asyncio

import discord
from discord import app_commands

from analysis.company_analyzer import run_deep_dive
from formatters.discord_formatter import error_embed
from utils.site_publisher import get_existing_url, publish

log = logging.getLogger(__name__)


@app_commands.command(name="analyze", description="Full 6-step deep-dive analysis of a stock")
@app_commands.describe(ticker="Stock ticker to analyze (e.g. AAPL)")
async def cmd_analyze(interaction: discord.Interaction, ticker: str):
    await interaction.response.defer(thinking=True)
    ticker = ticker.upper().strip()

    # Return cached page if a fresh analysis already exists (within 4 hours)
    slug = ticker.lower()
    cached_url = await asyncio.to_thread(get_existing_url, slug)
    if cached_url:
        await interaction.followup.send(
            f"A fresh analysis for **{ticker}** was already generated in the last 4 hours.\n{cached_url}"
        )
        return

    await interaction.followup.send(
        f"Starting 6-step analysis of **{ticker}**. This runs multiple LLM calls and may take 2-5 minutes..."
    )

    try:
        sections = await run_deep_dive(ticker)
    except Exception as e:
        log.error("[/analyze] Error for %s: %s", ticker, e, exc_info=True)
        await interaction.followup.send(embed=error_embed(f"Analysis failed: {e}"))
        return

    # Publish to site and get URL (awaited so link is ready before we respond)
    page_url = await asyncio.to_thread(publish, slug, f"{ticker} — Deep Dive Analysis", sections)

    msg = f"Analysis complete for **{ticker}**."
    if page_url:
        msg += f"\n{page_url}"
    await interaction.followup.send(msg)


STANDALONE_COMMANDS = [cmd_analyze]
