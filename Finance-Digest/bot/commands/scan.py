"""Slash commands: /viewTodaysDiscoveries and /refreshTodaysDiscoveries"""
from __future__ import annotations

import discord
from discord import app_commands


@app_commands.command(name="view-todays-discoveries", description="View today's best market discoveries")
async def cmd_view_discoveries(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    from bot.tasks.market_scan import run_view_discoveries
    await run_view_discoveries(interaction)


@app_commands.command(name="refresh-todays-discoveries", description="Run a fresh scan and merge into today's discoveries")
async def cmd_refresh_discoveries(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(
        "Refreshing discoveries — scanning 20 new tickers and merging into today's list..."
    )
    from bot.tasks.market_scan import run_refresh
    await run_refresh()
    await interaction.followup.send("Refresh complete. Check the briefing channel for the update.")


STANDALONE_COMMANDS = [cmd_view_discoveries, cmd_refresh_discoveries]
