"""Utilities for splitting long text into Discord-safe chunks and building embeds."""
from __future__ import annotations

import discord


MAX_CHUNK = 1900   # Discord message limit is 2000; leave headroom
MAX_EMBED_DESC = 4000  # Discord embed description limit


def split_to_chunks(text: str, max_length: int = MAX_CHUNK) -> list[str]:
    """Split text into chunks of max_length, breaking on paragraph or sentence boundaries."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Try to break on double-newline (paragraph boundary)
        split_at = text.rfind("\n\n", 0, max_length)
        if split_at == -1:
            # Try single newline
            split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            # Try sentence boundary
            split_at = text.rfind(". ", 0, max_length)
        if split_at == -1:
            split_at = max_length

        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return [c for c in chunks if c]


def analysis_embed(ticker: str, name: str, text: str, list_type: str = "portfolio",
                   color: int | None = None) -> discord.Embed:
    """Create a styled embed for a company analysis section."""
    if color is None:
        color = discord.Color.green().value if list_type == "portfolio" else discord.Color.blue().value

    embed = discord.Embed(
        title=f"{ticker} — {name}",
        description=text[:MAX_EMBED_DESC],
        color=color,
    )
    return embed


def opportunity_embed(scores: list) -> discord.Embed:
    """Create an embed showing ranked opportunity scores."""
    embed = discord.Embed(
        title="Investment Opportunities",
        color=discord.Color.gold().value,
    )
    if not scores:
        embed.description = "No high-scoring opportunities found today."
        return embed

    for score_obj in scores[:8]:
        signal_str = "\n".join(f"  • {s}" for s in score_obj.signals[:4]) if score_obj.signals else "No signals"
        value = f"Score: **{score_obj.score}**\n{signal_str}"
        if score_obj.llm_evaluation:
            value += f"\n> {score_obj.llm_evaluation[:200]}"
        embed.add_field(name=f"{score_obj.ticker} — {score_obj.name or score_obj.ticker}",
                        value=value[:1024], inline=False)
    return embed


def error_embed(message: str, title: str = "Error") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=discord.Color.red().value)


def success_embed(message: str, title: str = "Done") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=discord.Color.green().value)
