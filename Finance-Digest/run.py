#!/usr/bin/env python3
"""Entry point for the Finance Digest Discord bot."""
import asyncio
import logging
import sys

from utils.logging_setup import setup_logging

setup_logging()
log = logging.getLogger(__name__)


async def validate_startup() -> bool:
    """Run all startup checks. Returns True if OK to start, False if fatal error."""
    ok = True

    # 1. Config already validated at import (raises ValueError on missing keys)
    from utils.config import config
    log.info("Config loaded — briefing at %s %s", config.briefing_time, config.briefing_timezone)

    # 2. Initialize SQLite
    from data import database
    try:
        await database.init_db(config.db_path)
    except Exception as e:
        log.error("Database init failed: %s", e)
        return False

    # 3. Ping Ollama
    from analysis.llm_client import ping
    if not await ping():
        log.warning("Ollama is not reachable at %s — LLM features will fail", config.ollama_api_url)
        log.warning("Start Ollama with: sudo systemctl start ollama")
        # Not fatal — bot can still manage companies even without LLM
    else:
        log.info("Ollama reachable")

    # 4. Warn about missing optional API keys
    if not config.alpha_vantage_key:
        log.warning("ALPHA_VANTAGE_KEY not set — news sentiment will be unavailable")
    if not config.finnhub_key:
        log.warning("FINNHUB_KEY not set — earnings/analyst data will be unavailable")

    return ok


async def main() -> None:
    try:
        ok = await validate_startup()
        if not ok:
            sys.exit(1)
    except ValueError as e:
        # Config validation failure
        log.error("Startup validation failed: %s", e)
        sys.exit(1)

    from utils.config import config
    from bot.client import bot

    log.info("Starting Finance Digest Discord bot...")
    async with bot:
        await bot.start(config.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
