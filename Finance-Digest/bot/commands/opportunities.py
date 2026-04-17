"""Slash commands: /opportunities, /screen"""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from analysis.opportunity_scanner import score_watchlist, suggest_new_tickers
from data import database
from formatters.discord_formatter import error_embed, opportunity_embed, split_to_chunks

log = logging.getLogger(__name__)


@app_commands.command(name="opportunities", description="Score watchlist companies and find investment opportunities")
async def cmd_opportunities(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send("Scanning opportunities... evaluating your watchlist.")

    try:
        scores = await score_watchlist()
        if not scores:
            await interaction.followup.send(embed=error_embed(
                "No watchlist companies found, or none passed the screener. "
                "Add companies with `/add TICKER watchlist`.",
                title="No Opportunities Found",
            ))
            return

        embed = opportunity_embed(scores)
        await interaction.followup.send(embed=embed)

        # Send LLM evaluations for high scores as separate messages
        for s in scores[:3]:
            if s.llm_evaluation:
                await interaction.followup.send(
                    f"**{s.ticker} Evaluation:**\n{s.llm_evaluation}"
                )
    except Exception as e:
        log.error("[/opportunities] Error: %s", e, exc_info=True)
        await interaction.followup.send(embed=error_embed(f"Scanner error: {e}"))


@app_commands.command(name="screen", description="Generate new investment ideas based on your portfolio themes")
async def cmd_screen(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        portfolio = await database.get_companies_by_type("portfolio")
        watchlist = await database.get_companies_by_type("watchlist")

        if not portfolio:
            await interaction.followup.send(embed=error_embed(
                "Add companies to your portfolio first with `/add TICKER portfolio`.",
                title="No Portfolio Found",
            ))
            return

        await interaction.followup.send("Generating new investment ideas based on your portfolio themes...")
        suggestions = await suggest_new_tickers(
            [c.ticker for c in portfolio],
            [c.ticker for c in watchlist],
        )
        chunks = split_to_chunks(f"**New Ideas to Research:**\n\n{suggestions}")
        for chunk in chunks:
            await interaction.followup.send(chunk)

    except Exception as e:
        log.error("[/screen] Error: %s", e, exc_info=True)
        await interaction.followup.send(embed=error_embed(f"Screen error: {e}"))


STANDALONE_COMMANDS = [cmd_opportunities, cmd_screen]
