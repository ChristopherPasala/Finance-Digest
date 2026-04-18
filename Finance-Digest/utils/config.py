from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise ValueError(f"Required environment variable '{key}' is missing or empty. Check your .env file.")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass
class Config:
    # Discord
    discord_token: str
    discord_guild_id: int
    briefing_channel_id: int

    # Ollama / LLM
    ollama_api_url: str
    ollama_model: str

    # Financial APIs (optional — warn at startup if missing)
    alpha_vantage_key: str
    finnhub_key: str

    # Briefing schedule
    briefing_time: str           # "HH:MM" — daily watchlist briefing
    briefing_timezone: str       # e.g. "America/New_York"
    portfolio_briefing_day: str  # day of week for weekly portfolio deep dive, e.g. "mon"
    market_scan_day: str         # day of week for weekly autonomous market scan, e.g. "sun"
    market_scan_top_n: int       # how many top discoveries to include in the scan report

    # Web report server
    web_host: str
    web_port: int
    web_public_url: str          # e.g. "https://reports.yourdomain.com" (optional)
    web_secret_token: str        # leave blank to auto-generate on each restart

    # Static site (site-generator / Cloudflare Tunnel)
    site_public_url: str         # e.g. "https://finance.yourdomain.com" (optional)

    # Storage
    db_path: str
    log_path: str

    # SEC EDGAR
    sec_user_agent: str

    # Paper trading
    rebalance_interval_days: int = 14  # days between portfolio rebalances (14=bi-weekly, 30=monthly)

    # Limits
    max_discord_embeds_per_briefing: int = 20

    @property
    def scan_report_base_url(self) -> str:
        url = self.site_public_url or self.web_public_url
        if url:
            return url.rstrip("/")
        return "http://localhost:3000"

    @property
    def briefing_hour(self) -> int:
        return int(self.briefing_time.split(":")[0])

    @property
    def briefing_minute(self) -> int:
        return int(self.briefing_time.split(":")[1])


def load_config() -> Config:
    cfg = Config(
        discord_token=_require("DISCORD_TOKEN"),
        discord_guild_id=int(_require("DISCORD_GUILD_ID")),
        briefing_channel_id=int(_require("BRIEFING_CHANNEL_ID")),
        ollama_api_url=_optional("OLLAMA_API_URL", "http://localhost:11434/v1"),
        ollama_model=_optional("OLLAMA_MODEL", "qwen2.5:7b"),
        alpha_vantage_key=_optional("ALPHA_VANTAGE_KEY"),
        finnhub_key=_optional("FINNHUB_KEY"),
        briefing_time=_optional("BRIEFING_TIME", "07:00"),
        briefing_timezone=_optional("BRIEFING_TIMEZONE", "America/New_York"),
        portfolio_briefing_day=_optional("PORTFOLIO_BRIEFING_DAY", "mon"),
        market_scan_day=_optional("MARKET_SCAN_DAY", "sun"),
        market_scan_top_n=int(_optional("MARKET_SCAN_TOP_N", "10")),
        web_host=_optional("WEB_HOST", "127.0.0.1"),
        web_port=int(_optional("WEB_PORT", "8080")),
        web_public_url=_optional("WEB_PUBLIC_URL"),
        web_secret_token=_optional("WEB_SECRET_TOKEN"),
        site_public_url=_optional("SITE_PUBLIC_URL"),
        db_path=_optional("DB_PATH", "./finance_digest.db"),
        log_path=_optional("LOG_PATH", "./logs/finance_digest.log"),
        sec_user_agent=_optional("SEC_USER_AGENT", "FinanceDigestBot/1.0 contact@example.com"),
        max_discord_embeds_per_briefing=int(_optional("MAX_DISCORD_EMBEDS_PER_BRIEFING", "20")),
        rebalance_interval_days=int(_optional("REBALANCE_INTERVAL_DAYS", "14")),
    )

    # Warn about optional keys
    warnings = []
    if not cfg.alpha_vantage_key:
        warnings.append("ALPHA_VANTAGE_KEY not set — news sentiment analysis will be skipped")
    if not cfg.finnhub_key:
        warnings.append("FINNHUB_KEY not set — earnings calendar and analyst recommendations will be skipped")
    if warnings:
        for w in warnings:
            print(f"[CONFIG WARNING] {w}")

    # Ensure log directory exists
    Path(cfg.log_path).parent.mkdir(parents=True, exist_ok=True)

    return cfg


# Module-level singleton — imported by all other modules
config: Config = load_config()
