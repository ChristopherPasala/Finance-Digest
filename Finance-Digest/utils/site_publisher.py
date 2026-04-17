"""HTML rendering helpers for analysis sections, shared by html_formatter and web routes."""
from __future__ import annotations

import logging
import re
import sqlite3
import subprocess
from pathlib import Path

import markdown as md

from utils.config import config

log = logging.getLogger(__name__)

_SITE_DIR = Path(__file__).parent.parent.parent / "site-generator"
_SITE_DB  = _SITE_DIR / "data.db"


def _register_and_rebuild(slug: str, title: str) -> None:
    """Write a DB record for the slug so build.js can update index.html."""
    try:
        conn = sqlite3.connect(_SITE_DB)
        conn.execute(
            """
            INSERT INTO posts (slug, title, body, updated_at)
            VALUES (?, ?, '', datetime('now'))
            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (slug, title),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[site_publisher] DB register failed for %s: %s", slug, e)
        return

    try:
        subprocess.Popen(
            ["node", "src/build.js", f"--slug={slug}"],
            cwd=_SITE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("[site_publisher] Triggered index rebuild for: %s", slug)
    except Exception as e:
        log.warning("[site_publisher] Build trigger failed for %s: %s", slug, e)


def _section_to_html(section: str) -> str:
    """Convert a single section string to HTML."""
    stripped = section.strip()
    if not stripped:
        return ""

    # ━━━ HEADER ━━━ lines → <h2> (these are separators, not markdown)
    if stripped.startswith("━"):
        label = re.sub(r"^━+\s*\*?\*?", "", stripped)
        label = re.sub(r"\*?\*?\s*━+$", "", label).strip()
        return f'<h2 class="section-header">{label}</h2>'

    # Everything else: render as markdown, then post-process for styling
    html_body = md.markdown(_strip_latex(stripped), extensions=["nl2br", "sane_lists"])
    html_body = _apply_label_styles(html_body)
    return f'<div class="section">{html_body}</div>'


# LaTeX math commands the LLM occasionally outputs → plain Unicode equivalents.
_LATEX_MAP: dict[str, str] = {
    r'\rightarrow': '→',  r'\to':        '→',
    r'\leftarrow':  '←',  r'\gets':      '←',
    r'\uparrow':    '↑',  r'\downarrow': '↓',
    r'\geq':        '≥',  r'\ge':        '≥',
    r'\leq':        '≤',  r'\le':        '≤',
    r'\approx':     '≈',  r'\neq':       '≠',
    r'\ne':         '≠',  r'\times':     '×',
    r'\pm':         '±',  r'\cdot':      '·',
    r'\infty':      '∞',  r'\Delta':     'Δ',
    r'\alpha':      'α',  r'\beta':      'β',
}
# Match $\command$ or $ \command $ (with optional spaces inside)
_LATEX_RE = re.compile(r'\$\s*(\\[A-Za-z]+)\s*\$')


def _strip_latex(text: str) -> str:
    """Replace $\\command$ LaTeX math with Unicode equivalents; unescape \\$."""
    def _replace(m: re.Match) -> str:
        return _LATEX_MAP.get(m.group(1), m.group(1))
    text = _LATEX_RE.sub(_replace, text)
    text = text.replace(r'\$', '$')
    return text


# Inline bold labels → coloured spans.
_LABEL_STYLES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'<strong>(Facts?):</strong>',            re.IGNORECASE), 'lbl-fact'),
    (re.compile(r'<strong>(Interpretation):</strong>',    re.IGNORECASE), 'lbl-interp'),
    (re.compile(r'<strong>(Summary Risk Flag):</strong>', re.IGNORECASE), 'lbl-fact'),
    (re.compile(r'<strong>(Summary Interpretation):</strong>', re.IGNORECASE), 'lbl-interp'),
    (re.compile(r'<strong>(Risk Flag):</strong>',         re.IGNORECASE), 'lbl-fact'),
    (re.compile(r'<strong>(Risk):</strong>',              re.IGNORECASE), 'lbl-fact'),
]

# Whole-paragraph callout blocks (verdict / summary).
# Handles both  **VERDICT:** text  and  **VERDICT**: text  from LLM output.
_CALLOUT_RE = re.compile(
    r'<p><strong>(VERDICT|CONCLUSION|Summary Risk Flag|Summary Interpretation|Risk Flag):?</strong>:?\s*',
    re.IGNORECASE,
)

# Numbered item headers inside paragraphs → styled span so they stand out
# e.g. <p><strong>1. Growth Trend</strong><br  →  <p><span class="item-num">1.</span> <span class="item-title">Growth Trend</span><br
_ITEM_HEADER_RE = re.compile(
    r'<p><strong>(\d+)\.\s+([^<]+?)</strong>(?:<br|</p>)',
    re.IGNORECASE,
)

# SWOT category blocks — matches the whole <p> from the SWOT header to </p>
# Handles optional parenthetical e.g. "STRENGTHS (Internal Advantages)"
_SWOT_CSS = {
    'strengths':    'swot-s',
    'weaknesses':   'swot-w',
    'opportunities':'swot-o',
    'threats':      'swot-t',
}
_SWOT_BLOCK_RE = re.compile(
    r'<p><strong>(STRENGTHS|WEAKNESSES|OPPORTUNITIES|THREATS)</strong>[^<]*<br[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)


def _swot_block(m: re.Match) -> str:
    category = m.group(1).capitalize()
    css = _SWOT_CSS[category.lower()]
    # Each item is separated by "* " after a <br />; split and clean up
    items_raw = re.split(r'\*\s+', m.group(2))
    lis = []
    for item in items_raw:
        item = re.sub(r'<br\s*/?>\s*$', '', item).strip()
        if item:
            lis.append(f'<li>{item}</li>')
    return (
        f'<div class="swot-block {css}">'
        f'<span class="swot-cat">{category}</span>'
        f'<ul>{"".join(lis)}</ul>'
        f'</div>'
    )


def _apply_label_styles(html: str) -> str:
    """Replace known bold labels with styled spans and wrap callout blocks."""
    # LaTeX math → Unicode (handles already-stored HTML that wasn't pre-processed)
    html = _strip_latex(html)
    # SWOT blocks first (restructures whole paragraphs)
    html = _SWOT_BLOCK_RE.sub(_swot_block, html)
    # Numbered item headers
    html = _ITEM_HEADER_RE.sub(
        lambda m: (
            f'<p><span class="item-num">{m.group(1)}.</span>'
            f' <span class="item-title">{m.group(2)}</span>'
            + ('<br' if '<br' in m.group(0) else '</p>')
        ),
        html,
    )
    for pattern, cls in _LABEL_STYLES:
        html = pattern.sub(rf'<span class="{cls}">\1:</span>', html)
    html = _CALLOUT_RE.sub(
        lambda m: f'<p class="callout"><strong>{m.group(1)}:</strong> ',
        html,
    )
    return html


def sections_to_html(sections: list[str]) -> str:
    return "\n".join(_section_to_html(s) for s in sections if s.strip())


def get_existing_url(slug: str, max_age_hours: int = 4) -> str | None:
    """Return the page URL if a fresh analysis for this slug exists (within max_age_hours), else None."""
    from web import server as web_server
    return web_server.get_existing_analysis_url(slug, max_age_hours, config.scan_report_base_url)


def publish(slug: str, title: str, sections: list[str], active_tab: str = "analyses") -> str | None:
    """
    Render sections as a rich HTML page, write to site-generator/public/posts/,
    register the slug in data.db (so the index rebuilds), and return the URL.
    Safe to call from an async context via asyncio.to_thread.
    """
    from formatters.html_formatter import build_briefing_html
    from web import server as web_server
    page_html = build_briefing_html(sections, title=title, active_tab=active_tab)
    web_server.save_analysis(page_html, slug)
    _register_and_rebuild(slug, title)
    return web_server.analysis_url(config.scan_report_base_url, slug)
