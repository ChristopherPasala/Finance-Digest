"""Slash command: /briefing"""
from __future__ import annotations

import discord
from discord import app_commands


@app_commands.command(name="briefing", description="Trigger a briefing now")
@app_commands.describe(type="Which briefing to run")
@app_commands.choices(type=[
    app_commands.Choice(name="Daily watchlist (default)", value="daily"),
    app_commands.Choice(name="Weekly portfolio deep dive", value="portfolio"),
])
async def cmd_briefing(interaction: discord.Interaction,
                       type: app_commands.Choice[str] = None):
    await interaction.response.defer(thinking=True)

    briefing_type = type.value if type else "daily"

    from bot.tasks.morning_briefing import run_morning_briefing, run_portfolio_briefing

    if briefing_type == "portfolio":
        await interaction.followup.send(
            "Starting portfolio deep dive... this may take several minutes per company."
        )
        await run_portfolio_briefing(trigger_type="manual")
        await interaction.followup.send("Portfolio deep dive complete. Check the briefing channel.")
    else:
        await interaction.followup.send(
            "Starting daily watchlist briefing..."
        )
        await run_morning_briefing(trigger_type="manual")
        await interaction.followup.send("Daily briefing complete. Check the briefing channel.")


STANDALONE_COMMANDS = [cmd_briefing]
