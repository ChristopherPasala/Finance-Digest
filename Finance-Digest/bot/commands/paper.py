"""Slash command: /paper — paper trading portfolio report."""
from __future__ import annotations

import logging

from discord import app_commands
import discord

log = logging.getLogger(__name__)


@app_commands.command(name="paper", description="Show paper trading portfolio performance and charts")
async def cmd_paper(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        from utils.config import config
        from web import server as web_server

        portfolio_url = web_server.portfolio_page_url(config.scan_report_base_url)
        await interaction.followup.send(portfolio_url)

    except Exception as e:
        log.error("[paper] Command failed: %s", e, exc_info=True)
        await interaction.followup.send(f"Paper portfolio error: {e}")


STANDALONE_COMMANDS = [cmd_paper]
