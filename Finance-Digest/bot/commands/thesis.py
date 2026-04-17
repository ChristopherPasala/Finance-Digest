"""Slash command: /thesis"""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from data import database
from data.models import InvestmentThesis
from formatters.discord_formatter import error_embed, success_embed

log = logging.getLogger(__name__)


@app_commands.command(name="thesis", description="View or update your investment thesis for a stock")
@app_commands.describe(
    ticker="Stock ticker",
    moat="What is the competitive advantage?",
    entry_rationale="Why did you add this to your portfolio/watchlist?",
    strengths="Key strengths (SWOT)",
    weaknesses="Key weaknesses (SWOT)",
    opportunities="Key opportunities (SWOT)",
    threats="Key threats (SWOT)",
    target_price="Your personal price target (optional)",
    questions="Open questions to follow up on",
)
async def cmd_thesis(
    interaction: discord.Interaction,
    ticker: str,
    moat: str | None = None,
    entry_rationale: str | None = None,
    strengths: str | None = None,
    weaknesses: str | None = None,
    opportunities: str | None = None,
    threats: str | None = None,
    target_price: float | None = None,
    questions: str | None = None,
):
    await interaction.response.defer(thinking=True)
    ticker = ticker.upper().strip()

    # Check company exists
    company = await database.get_company(ticker)
    if not company:
        await interaction.followup.send(embed=error_embed(
            f"**{ticker}** is not being tracked. Add it first with `/add {ticker}`."
        ))
        return

    is_update = any([moat, entry_rationale, strengths, weaknesses, opportunities, threats,
                     target_price is not None, questions])

    if is_update:
        # Load existing thesis to merge with new values
        existing = await database.get_thesis(ticker) or InvestmentThesis(ticker=ticker)
        updated = InvestmentThesis(
            ticker=ticker,
            moat=moat or existing.moat,
            entry_rationale=entry_rationale or existing.entry_rationale,
            strengths=strengths or existing.strengths,
            weaknesses=weaknesses or existing.weaknesses,
            opportunities=opportunities or existing.opportunities,
            threats=threats or existing.threats,
            target_price=target_price if target_price is not None else existing.target_price,
            questions=questions or existing.questions,
        )
        await database.upsert_thesis(updated)
        await interaction.followup.send(embed=success_embed(
            f"Thesis for **{ticker}** ({company.name or ticker}) updated.",
            title="Thesis Updated",
        ))

    # Always show current thesis
    thesis = await database.get_thesis(ticker)
    if not thesis:
        await interaction.followup.send(embed=error_embed(
            f"No thesis recorded for **{ticker}**. Use the command parameters to add one.",
            title="No Thesis Found",
        ))
        return

    embed = discord.Embed(
        title=f"Investment Thesis — {ticker} ({company.name or ticker})",
        color=discord.Color.purple().value,
    )
    if thesis.moat:
        embed.add_field(name="🏰 Moat", value=thesis.moat[:1024], inline=False)
    if thesis.entry_rationale:
        embed.add_field(name="📌 Entry Rationale", value=thesis.entry_rationale[:1024], inline=False)
    if thesis.strengths:
        embed.add_field(name="💪 Strengths", value=thesis.strengths[:512], inline=True)
    if thesis.weaknesses:
        embed.add_field(name="⚠️ Weaknesses", value=thesis.weaknesses[:512], inline=True)
    if thesis.opportunities:
        embed.add_field(name="🚀 Opportunities", value=thesis.opportunities[:512], inline=True)
    if thesis.threats:
        embed.add_field(name="🚨 Threats", value=thesis.threats[:512], inline=True)
    if thesis.target_price:
        embed.add_field(name="🎯 Target Price", value=f"${thesis.target_price:.2f}", inline=True)
    if thesis.questions:
        embed.add_field(name="❓ Open Questions", value=thesis.questions[:512], inline=False)
    if thesis.updated_at:
        embed.set_footer(text=f"Last updated: {thesis.updated_at[:10]}")

    await interaction.followup.send(embed=embed)


STANDALONE_COMMANDS = [cmd_thesis]
