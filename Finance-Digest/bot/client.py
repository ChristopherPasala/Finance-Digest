"""Main Discord bot client with APScheduler for morning briefings."""
from __future__ import annotations

import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands

from bot.commands.portfolio import STANDALONE_COMMANDS as portfolio_cmds
from bot.commands.briefing import STANDALONE_COMMANDS as briefing_cmds
from bot.commands.analyze import STANDALONE_COMMANDS as analyze_cmds
from bot.commands.opportunities import STANDALONE_COMMANDS as opportunity_cmds
from bot.commands.thesis import STANDALONE_COMMANDS as thesis_cmds
from bot.commands.scan import STANDALONE_COMMANDS as scan_cmds
from bot.commands.paper import STANDALONE_COMMANDS as paper_cmds
from bot.tasks import morning_briefing as briefing_task
from bot.tasks import market_scan as scan_task
from utils.config import config

log = logging.getLogger(__name__)


class FinanceBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.scheduler = AsyncIOScheduler(timezone=config.briefing_timezone)

    async def setup_hook(self) -> None:
        # Register all slash commands
        all_commands = (
            portfolio_cmds + briefing_cmds + analyze_cmds + opportunity_cmds + thesis_cmds + scan_cmds + paper_cmds
        )
        guild = discord.Object(id=config.discord_guild_id)
        for cmd in all_commands:
            self.tree.add_command(cmd, guild=guild)

        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %d", config.discord_guild_id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)

        # Wire up tasks
        briefing_task.set_bot(self)
        scan_task.set_bot(self)

        # Daily watchlist briefing
        self.scheduler.add_job(
            briefing_task.run_morning_briefing,
            trigger=CronTrigger(
                hour=config.briefing_hour,
                minute=config.briefing_minute,
                timezone=config.briefing_timezone,
            ),
            id="daily_briefing",
            replace_existing=True,
        )

        # Weekly portfolio deep dive
        self.scheduler.add_job(
            briefing_task.run_portfolio_briefing,
            trigger=CronTrigger(
                day_of_week=config.portfolio_briefing_day,
                hour=config.briefing_hour,
                minute=config.briefing_minute,
                timezone=config.briefing_timezone,
            ),
            id="portfolio_briefing",
            replace_existing=True,
        )

        # Daily discovery initialization at 6am
        self.scheduler.add_job(
            scan_task.run_daily_init,
            trigger=CronTrigger(hour=6, minute=0, timezone=config.briefing_timezone),
            id="daily_discovery_init",
            replace_existing=True,
        )

        self.scheduler.start()
        log.info(
            "Scheduler started — daily briefing at %s %s | portfolio deep dive every %s | discovery init daily at 06:00",
            config.briefing_time,
            config.briefing_timezone,
            config.portfolio_briefing_day,
        )

    async def on_error(self, event: str, *args, **kwargs) -> None:
        log.error("Discord event error in %s", event, exc_info=True)


bot = FinanceBot()
