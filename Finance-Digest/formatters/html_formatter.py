"""Build self-contained HTML reports for market scan discoveries and daily briefings."""
from __future__ import annotations

import html
import re
from datetime import datetime

import markdown as md

from data.models import OpportunityScore

_MAX_SCORE = 13


def _score_color(score: int) -> str:
    if score >= 9:
        return "#22c55e"   # green
    if score >= 6:
        return "#f59e0b"   # amber
    if score >= 3:
        return "#3b82f6"   # blue
    return "#475569"       # slate (weak / negative signals)


def _score_bar(score: int) -> str:
    filled = min(max(score, 0), _MAX_SCORE)
    pct = round(filled / _MAX_SCORE * 100)
    color = _score_color(score)
    return (
        f'<div class="score-bar-bg">'
        f'<div class="score-bar-fill" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
    )


def _pill(text: str, color: str = "#334155") -> str:
    safe = html.escape(text)
    return f'<span class="pill" style="background:{color};">{safe}</span>'


def _discovery_card(opp: OpportunityScore, rank: int) -> str:
    color = _score_color(opp.score)
    name = html.escape(opp.name or opp.ticker)
    ticker = html.escape(opp.ticker)
    signals_html = "".join(_pill(s) for s in opp.signals) if opp.signals else _pill("No signals", "#64748b")
    eval_html = (
        f'<div class="llm-eval">{md.markdown(opp.llm_evaluation, extensions=["sane_lists"])}</div>'
        if opp.llm_evaluation
        else '<p class="llm-eval muted">Not evaluated (score below threshold or evaluation limit reached).</p>'
    )
    return f"""
    <div class="card" style="border-left:4px solid {color};">
      <div class="card-header">
        <span class="rank" style="background:{color};">#{rank}</span>
        <span class="ticker">{ticker}</span>
        <span class="name">{name}</span>
        <span class="score-label" style="color:{color};">{opp.score}/{_MAX_SCORE}</span>
      </div>
      {_score_bar(opp.score)}
      <div class="signals">{signals_html}</div>
      {eval_html}
    </div>
"""


_NAV_LINK = '<link rel="stylesheet" href="/nav.css">'

_NAV_LINKS = [
    ("analyses", "/",              "Analyses"),
    ("scans",    "/scans.html",    "Market Scans"),
    ("briefings","/briefings.html","Briefings"),
    ("portfolio","/portfolio.html","Portfolio"),
    ("glossary", "/glossary.html", "Glossary"),
]


def _site_nav(active: str = "") -> str:
    tabs = "".join(
        f'<a class="tab{" active" if key == active else ""}" href="{href}">{label}</a>'
        for key, href, label in _NAV_LINKS
    )
    return f'<nav class="top-nav"><a class="brand" href="/">Finance Digest</a>{tabs}</nav>'


def build_scan_html(
    discoveries: list[OpportunityScore],
    scan_stats: dict,
) -> str:
    """Return a complete, self-contained HTML page for a market scan report."""
    date_str = datetime.utcnow().strftime("%B %d, %Y")
    tickers_scanned = scan_stats.get("tickers_scanned", "?")
    discoveries_found = scan_stats.get("discoveries_found", len(discoveries))
    raw_duration = scan_stats.get("duration_seconds")
    duration_str = f"{raw_duration:.1f}s" if isinstance(raw_duration, (int, float)) else "?"
    scanned_at = scan_stats.get("scanned_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

    if discoveries:
        cards_html = "".join(_discovery_card(opp, i + 1) for i, opp in enumerate(discoveries))
    else:
        cards_html = (
            '<div class="empty">No discoveries passed the quantitative screener in this scan. '
            'Try <code>/scan</code> again tomorrow or add tickers manually with '
            '<code>/add TICKER watchlist</code>.</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Market Scan — {html.escape(date_str)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
    }}
    header {{
      background: #1e293b;
      border-bottom: 1px solid #334155;
      padding: 1.5rem 2rem;
    }}
    header h1 {{
      margin: 0 0 0.75rem;
      font-size: 1.5rem;
      font-weight: 700;
      color: #f1f5f9;
    }}
    .stats {{
      display: flex;
      gap: 2rem;
      flex-wrap: wrap;
    }}
    .stat {{
      display: flex;
      flex-direction: column;
      gap: 0.1rem;
    }}
    .stat-label {{
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #64748b;
    }}
    .stat-value {{
      font-size: 1.1rem;
      font-weight: 600;
      color: #f1f5f9;
    }}
    main {{
      max-width: 900px;
      margin: 2rem auto;
      padding: 0 1.5rem;
    }}
    .card {{
      background: #1e293b;
      border-radius: 0.5rem;
      padding: 1.25rem 1.5rem;
      margin-bottom: 1rem;
      border-left: 4px solid #3b82f6;
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
      flex-wrap: wrap;
    }}
    .rank {{
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      color: #0f172a;
      white-space: nowrap;
    }}
    .ticker {{
      font-size: 1.15rem;
      font-weight: 800;
      color: #f1f5f9;
      letter-spacing: 0.03em;
    }}
    .name {{
      font-size: 0.9rem;
      color: #94a3b8;
      flex: 1;
    }}
    .score-label {{
      font-size: 1rem;
      font-weight: 700;
      margin-left: auto;
    }}
    .score-bar-bg {{
      height: 6px;
      background: #334155;
      border-radius: 999px;
      margin-bottom: 0.75rem;
      overflow: hidden;
    }}
    .score-bar-fill {{
      height: 100%;
      border-radius: 999px;
      transition: width 0.3s;
    }}
    .signals {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-bottom: 0.75rem;
    }}
    .pill {{
      font-size: 0.75rem;
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      color: #e2e8f0;
      white-space: nowrap;
    }}
    .llm-eval {{
      margin: 0;
      font-size: 0.88rem;
      color: #cbd5e1;
      line-height: 1.6;
      padding-top: 0.5rem;
      border-top: 1px solid #334155;
    }}
    .llm-eval p, .llm-eval li {{ font-size: 0.88rem; color: #cbd5e1; line-height: 1.6; margin: 0.3rem 0; }}
    .llm-eval strong {{ color: #f1f5f9; }}
    .llm-eval ul, .llm-eval ol {{ padding-left: 1.2rem; margin: 0.3rem 0; }}
    .muted {{ color: #475569 !important; font-style: italic; }}
    .empty {{
      background: #1e293b;
      border-radius: 0.5rem;
      padding: 2rem;
      text-align: center;
      color: #64748b;
    }}
    footer {{
      text-align: center;
      padding: 2rem 1.5rem;
      font-size: 0.78rem;
      color: #475569;
      border-top: 1px solid #1e293b;
      margin-top: 2rem;
    }}
    @media (max-width: 600px) {{
      .stats {{ gap: 1rem; }}
      .score-label {{ margin-left: 0; }}
    }}
  </style>
  {_NAV_LINK}
</head>
<body>
  {_site_nav("scans")}
  <header>
    <h1>Market Scan — {html.escape(date_str)}</h1>
    <div class="stats">
      <div class="stat"><span class="stat-label">Tickers Scanned</span><span class="stat-value">{tickers_scanned}</span></div>
      <div class="stat"><span class="stat-label">Discoveries Found</span><span class="stat-value">{discoveries_found}</span></div>
      <div class="stat"><span class="stat-label">Scan Duration</span><span class="stat-value">{html.escape(duration_str)}</span></div>
      <div class="stat"><span class="stat-label">Scanned At</span><span class="stat-value">{html.escape(str(scanned_at))}</span></div>
    </div>
  </header>
  <main>
    {cards_html}
  </main>
  <footer>
    System-generated using quantitative signals and an AI language model.
    Not financial advice. Always do your own research before making any investment decision.
  </footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Opportunity score card helpers
# ---------------------------------------------------------------------------

_OPP_TICKER_RE = re.compile(
    r'^\*\*([A-Z][A-Z0-9.]+)\*\*\s+(\d+)/15\s+\[[\+\-]+\]\s*[—–-]+\s*(.+)',
    re.MULTILINE,
)
_MAX_OPP_SCORE = 15


def _parse_opp_entries(text: str) -> tuple[str, list[dict]]:
    """Parse the opportunities section into (header_line, list_of_entries)."""
    lines = text.strip().splitlines()
    header = ""
    entries: list[dict] = []
    current: dict | None = None
    eval_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        m = _OPP_TICKER_RE.match(stripped)
        if m:
            # Flush previous entry
            if current is not None:
                current["llm_eval"] = "\n".join(eval_lines).strip()
                entries.append(current)
            signals = [s.strip() for s in m.group(3).split("|") if s.strip()]
            current = {"ticker": m.group(1), "score": int(m.group(2)), "signals": signals}
            eval_lines = []
        elif current is not None:
            # LLM eval content — strip leading "> " prefix if present
            if stripped.startswith("> "):
                eval_lines.append(stripped[2:])
            elif stripped.startswith(">"):
                eval_lines.append(stripped[1:])
            else:
                eval_lines.append(stripped)
        elif stripped and not header:
            header = stripped

    if current is not None:
        current["llm_eval"] = "\n".join(eval_lines).strip()
        entries.append(current)

    return header, entries


def _opp_card_html(entry: dict) -> str:
    ticker  = html.escape(entry["ticker"])
    score   = entry["score"]
    signals = entry["signals"]
    llm     = entry.get("llm_eval", "").strip()
    color   = _score_color(score)
    pct     = round(min(max(score, 0), _MAX_OPP_SCORE) / _MAX_OPP_SCORE * 100)
    pills = "".join(
        f'<span class="opp-pill" style="background:{color}20;color:{color};'
        f'border:1px solid {color}40;">{html.escape(s)}</span>'
        for s in signals
    ) if signals else f'<span class="opp-pill" style="color:#475569;">No signals</span>'

    eval_html = ""
    if llm:
        rendered = md.markdown(llm, extensions=["nl2br", "sane_lists"])
        eval_html = f'<div class="opp-eval">{rendered}</div>'
    else:
        eval_html = '<div class="opp-eval opp-eval-muted">Below evaluation threshold.</div>'

    return (
        f'<div class="opp-card" data-score="{score}" style="border-left-color:{color};">'
        f'<div class="opp-hdr">'
        f'<span class="opp-tkr">{ticker}</span>'
        f'<div class="opp-score-col">'
        f'<span class="opp-score-num" style="color:{color};">{score}<span class="opp-denom">/15</span></span>'
        f'<div class="opp-bar-bg"><div class="opp-bar-fill" style="width:{pct}%;background:{color};"></div></div>'
        f'</div>'
        f'</div>'
        f'<div class="opp-signals">{pills}</div>'
        f'{eval_html}'
        f'</div>'
    )


def _is_opportunity_section(text: str) -> bool:
    return bool(re.match(r'Watchlist opportunity scores', text.strip(), re.IGNORECASE))


def _opportunity_section_to_html(text: str) -> str:
    header, entries = _parse_opp_entries(text)
    if not entries:
        from utils.site_publisher import _section_to_html
        return _section_to_html(text)
    header_html = (
        f'<p class="opp-header">{html.escape(header)}</p>' if header else ""
    )
    cards = "".join(_opp_card_html(e) for e in entries)
    return f'<div class="opp-section">{header_html}{cards}</div>'


# ---------------------------------------------------------------------------
# Company brief accordion helpers
# ---------------------------------------------------------------------------

# Matches  **AAPL** — Apple Inc.  at the start of a section
_COMPANY_HDR_RE = re.compile(
    r'^\*\*([A-Z][A-Z0-9.]{0,9})\*\*\s*[—–\-]+\s*(.+)',
    re.MULTILINE,
)

# Splits the LLM body into named subsections
_SUBSEC_SPLIT_RE = re.compile(
    r'^(PRICE\s+CHECK|PRICE\s+ACTION|NEWS\s+IMPACT'
    r'|KEY\s+RISKS?|MONITOR|VERDICT'
    r'|FUNDAMENTAL\s+SIGNAL|THESIS\s+CHECK)\s*:',
    re.IGNORECASE | re.MULTILINE,
)

# Subsections that are expanded by default
_OPEN_SUBSECTIONS = {
    "PRICE CHECK", "PRICE ACTION", "NEWS IMPACT",
    "VERDICT", "THESIS CHECK", "FUNDAMENTAL SIGNAL",
}

_SUBSEC_DISPLAY = {
    "PRICE CHECK":        "Price Check",
    "PRICE ACTION":       "Price Action",
    "NEWS IMPACT":        "News Impact",
    "KEY RISK":           "Key Risk",
    "KEY RISKS":          "Key Risks",
    "MONITOR":            "Monitor",
    "VERDICT":            "Verdict",
    "FUNDAMENTAL SIGNAL": "Fundamental Signal",
    "THESIS CHECK":       "Thesis Check",
}


def _verdict_badge(text: str) -> str:
    """Return an HTML badge for the verdict/thesis keyword in *text*."""
    t = text.strip().upper()
    if t.startswith("CONSIDER ENTRY"):
        return '<span class="vbadge v-entry">CONSIDER ENTRY</span>'
    if t.startswith("WATCH CLOSELY"):
        return '<span class="vbadge v-watch">WATCH CLOSELY</span>'
    if t.startswith("WATCH"):
        return '<span class="vbadge v-watch">WATCH</span>'
    if t.startswith("HOLD"):
        return '<span class="vbadge v-hold">HOLD</span>'
    if t.startswith("ACT"):
        return '<span class="vbadge v-act">ACT</span>'
    # Thesis status
    if t.startswith("INTACT"):
        return '<span class="vbadge v-hold">INTACT</span>'
    if t.startswith("CHALLENGED"):
        return '<span class="vbadge v-watch">CHALLENGED</span>'
    if t.startswith("BROKEN"):
        return '<span class="vbadge v-act">BROKEN</span>'
    label = html.escape(text.split("—")[0].strip()[:20])
    return f'<span class="vbadge v-neutral">{label}</span>'


def _monitor_badge(text: str) -> str:
    t = text.strip().upper()
    if t.startswith("YES"):
        return '<span class="mbadge m-yes">MONITOR ✓</span>'
    if t.startswith("NO"):
        return '<span class="mbadge m-no">SKIP</span>'
    return ""


def _is_company_section(text: str) -> bool:
    """Return True if *text* is a company brief with known subsections."""
    stripped = text.strip()
    if not _COMPANY_HDR_RE.match(stripped):
        return False
    return bool(_SUBSEC_SPLIT_RE.search(stripped))


def _company_card_html(text: str) -> str:
    """Convert a raw company brief string into an accordion card."""
    stripped = text.strip()
    lines = stripped.split("\n", 1)
    header_line = lines[0]
    body = lines[1].strip() if len(lines) > 1 else ""

    m = _COMPANY_HDR_RE.match(header_line)
    ticker = html.escape(m.group(1)) if m else "???"
    co_name = html.escape(m.group(2).strip()) if m else html.escape(header_line)

    # Split body into subsections
    parts = _SUBSEC_SPLIT_RE.split(body)
    # parts: [pre, name1, body1, name2, body2, ...]
    subsections: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        raw_name = re.sub(r"\s+", " ", parts[i].strip()).upper()
        sub_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        subsections.append((raw_name, sub_body))

    # Extract badges from VERDICT / THESIS CHECK / MONITOR
    verdict_badge = ""
    monitor_badge = ""
    for name, sub_body in subsections:
        if name == "VERDICT" and not verdict_badge:
            verdict_badge = _verdict_badge(sub_body)
        elif name == "THESIS CHECK" and not verdict_badge:
            verdict_badge = _verdict_badge(sub_body)
        elif name == "MONITOR" and not monitor_badge:
            monitor_badge = _monitor_badge(sub_body)

    badges_html = verdict_badge + (" " + monitor_badge if monitor_badge else "")

    # Build accordion items
    accordions = ""
    for name, sub_body in subsections:
        label = _SUBSEC_DISPLAY.get(name, name.title())
        open_attr = " open" if name in _OPEN_SUBSECTIONS else ""
        # Render body as markdown
        body_html = md.markdown(sub_body, extensions=["nl2br", "sane_lists"])
        accordions += (
            f'<details class="acc-item"{open_attr}>'
            f'<summary class="acc-sum">{label}</summary>'
            f'<div class="acc-body">{body_html}</div>'
            f'</details>'
        )

    return (
        f'<div class="co-card">'
        f'<div class="co-hdr">'
        f'<div class="co-hdr-l">'
        f'<span class="tkr">{ticker}</span>'
        f'<span class="co-name">{co_name}</span>'
        f'</div>'
        f'<div class="co-hdr-r">{badges_html}</div>'
        f'</div>'
        f'{accordions}'
        f'</div>'
    )


def _briefing_sections_to_html(sections: list[str]) -> str:
    """Convert briefing sections to HTML, rendering company briefs as accordion cards
    and opportunity scores as visual score cards."""
    from utils.site_publisher import _section_to_html
    parts = []
    for s in sections:
        stripped = s.strip()
        if not stripped:
            continue
        if _is_opportunity_section(stripped):
            parts.append(_opportunity_section_to_html(stripped))
        elif _is_company_section(stripped):
            parts.append(_company_card_html(stripped))
        else:
            parts.append(_section_to_html(stripped))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Paper portfolio helpers
# ---------------------------------------------------------------------------

_STARTING_CASH = 10_000.0


def _nav_chart_svg(daily_values: list[dict]) -> str:
    """Generate an inline SVG line chart of portfolio NAV over time."""
    if len(daily_values) < 2:
        return ""
    values = [d["portfolio_value"] for d in daily_values]
    min_v = min(min(values), _STARTING_CASH) * 0.98
    max_v = max(max(values), _STARTING_CASH) * 1.02
    span = max_v - min_v or 1.0
    W, H, PAD = 1000, 200, 12

    def pt(i: int, v: float) -> tuple[float, float]:
        x = PAD + (i / (len(values) - 1)) * (W - 2 * PAD)
        y = H - PAD - ((v - min_v) / span) * (H - 2 * PAD)
        return x, y

    pts = [pt(i, v) for i, v in enumerate(values)]
    line = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    _, by = pt(0, _STARTING_CASH)
    fill_pts = pts + [(pts[-1][0], H - PAD), (pts[0][0], H - PAD)]
    fill = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in fill_pts) + " Z"
    color = "#22c55e" if values[-1] >= _STARTING_CASH else "#ef4444"

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"'
        f' style="width:100%;height:130px;display:block;">'
        f'<defs><linearGradient id="ng" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.25"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<path d="{fill}" fill="url(#ng)"/>'
        f'<line x1="{PAD}" y1="{by:.1f}" x2="{W-PAD}" y2="{by:.1f}"'
        f' stroke="#475569" stroke-width="1.5" stroke-dasharray="5,5"/>'
        f'<path d="{line}" fill="none" stroke="{color}" stroke-width="2.5"'
        f' stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def _build_portfolio_tab(portfolio_data: dict) -> str:
    """Build the inner HTML for the Portfolio tab."""
    import json as _json

    state       = portfolio_data.get("state", {})
    positions   = portfolio_data.get("positions", [])    # list of paper_daily_positions rows
    cash        = state.get("cash", _STARTING_CASH)
    cash_pct    = portfolio_data.get("cash_pct", 100.0)
    daily_vals  = portfolio_data.get("daily_values", [])
    trades      = portfolio_data.get("recent_trades", [])
    entry_prices = portfolio_data.get("entry_prices", {})
    inception   = html.escape(state.get("inception_at", "—"))

    nav = daily_vals[-1]["portfolio_value"] if daily_vals else cash
    ret_pct = (nav / _STARTING_CASH - 1) * 100
    ret_color = "#22c55e" if ret_pct >= 0 else "#ef4444"
    invested = nav - cash

    chart_svg = _nav_chart_svg(daily_vals)

    # --- Holdings table ---
    pos_rows = ""
    for p in sorted(positions, key=lambda x: -x.get("position_value", 0)):
        ticker = p["ticker"]
        price = p.get("price", 0.0)
        shares = p.get("shares", 0.0)
        val = p.get("position_value", 0.0)
        wt = p.get("weight_pct", 0.0)
        avg_cost = entry_prices.get(ticker, price)
        pnl_pct = (price / avg_cost - 1) * 100 if avg_cost > 0 else 0.0
        pc = "#22c55e" if pnl_pct >= 0 else "#ef4444"
        pos_rows += (
            f"<tr><td class='tc'>{html.escape(ticker)}</td>"
            f"<td>{shares:.4f}</td><td>${price:.2f}</td>"
            f"<td>${val:,.2f}</td><td>{wt:.1f}%</td>"
            f"<td style='color:{pc}'>{pnl_pct:+.1f}%</td></tr>"
        )
    pos_rows += (
        f"<tr class='cash-row'><td class='tc'>CASH</td><td>—</td><td>—</td>"
        f"<td>${cash:,.2f}</td><td>{cash_pct:.1f}%</td><td>—</td></tr>"
    )

    # --- Trade log ---
    trade_rows = ""
    for t in reversed(trades[-40:]):
        action = t.get("action", "")
        ac = "#22c55e" if action == "BUY" else "#ef4444"
        try:
            reasons = _json.loads(t.get("reason") or "[]")
            reason_str = ", ".join(str(r) for r in reasons[:2])
        except Exception:
            reason_str = str(t.get("reason", ""))
        trade_rows += (
            f"<tr><td>{html.escape(str(t.get('traded_at',''))[:10])}</td>"
            f"<td><span style='color:{ac};font-weight:700'>{html.escape(action)}</span></td>"
            f"<td class='tc'>{html.escape(t.get('ticker',''))}</td>"
            f"<td>{t.get('shares',0):.4f}</td>"
            f"<td>${t.get('price',0):.2f}</td>"
            f"<td>${t.get('total_value',0):,.2f}</td>"
            f"<td class='rc'>{html.escape(reason_str)}</td></tr>"
        )
    if not trade_rows:
        trade_rows = "<tr><td colspan='7' style='color:#475569;text-align:center'>No trades yet.</td></tr>"

    return f"""
<div class="port-summary">
  <div class="ps"><span class="pl">NAV</span><span class="pv">${nav:,.2f}</span></div>
  <div class="ps"><span class="pl">Total Return</span><span class="pv" style="color:{ret_color}">{ret_pct:+.1f}%</span></div>
  <div class="ps"><span class="pl">Invested</span><span class="pv">${invested:,.2f}</span></div>
  <div class="ps"><span class="pl">Cash</span><span class="pv">${cash:,.2f} <span style="color:#64748b;font-size:.85em">({cash_pct:.0f}%)</span></span></div>
  <div class="ps"><span class="pl">Since</span><span class="pv">{inception}</span></div>
</div>

<div class="chart-wrap">
  <div class="chart-label">Portfolio value vs $10,000 start</div>
  {chart_svg}
</div>

<h3 class="sub-hd">Holdings</h3>
<div class="tbl-wrap"><table class="dt">
  <thead><tr><th>Ticker</th><th>Shares</th><th>Price</th><th>Value</th><th>Weight</th><th>P&amp;L</th></tr></thead>
  <tbody>{pos_rows}</tbody>
</table></div>

<h3 class="sub-hd">Trade Log</h3>
<div class="tbl-wrap"><table class="dt">
  <thead><tr><th>Date</th><th>Action</th><th>Ticker</th><th>Shares</th><th>Price</th><th>Total</th><th>Reason</th></tr></thead>
  <tbody>{trade_rows}</tbody>
</table></div>
"""


def build_briefing_html(sections: list[str], title: str, subtitle: str = "", active_tab: str = "briefings") -> str:
    """Return a complete, self-contained HTML page for a daily or portfolio briefing."""
    body_content = _briefing_sections_to_html(sections)
    subtitle_html = f'<p class="subtitle">{html.escape(subtitle)}</p>' if subtitle else ""
    nav_html = _site_nav(active_tab)
    main_body = body_content

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      line-height: 1.65;
    }}
    header {{
      background: #1e293b;
      border-bottom: 1px solid #334155;
      padding: 1.5rem 2rem;
    }}
    header h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; font-weight: 700; color: #f1f5f9; }}
    .subtitle {{ margin: 0; font-size: 0.85rem; color: #64748b; }}
    /* Tabs */
    main {{
      max-width: 900px;
      margin: 2rem auto;
      padding: 0 1.5rem;
    }}
    /* Briefing sections */
    h2.section-header {{
      font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; color: #60a5fa;
      border-bottom: 1px solid #1e3a5f; padding-bottom: 0.4rem; margin: 2rem 0 1rem;
    }}
    .section {{
      background: #1e293b; border-radius: 0.5rem;
      padding: 1.25rem 1.5rem; margin-bottom: 1rem; font-size: 0.92rem;
    }}
    .section p {{ margin: 0.5rem 0; }}
    .section ul, .section ol {{ margin: 0.5rem 0; padding-left: 1.5rem; }}
    .section li {{ margin: 0.25rem 0; }}
    .section code {{
      background: #0f172a; padding: 0.1em 0.35em; border-radius: 3px;
      font-size: 0.85em; color: #93c5fd;
    }}
    .lbl-fact {{
      display: inline-block; background: #1e3a5f; color: #93c5fd;
      font-size: 0.75rem; font-weight: 700; padding: 0.1rem 0.45rem;
      border-radius: 3px; text-transform: uppercase; letter-spacing: 0.04em; margin-right: 0.25rem;
    }}
    .lbl-interp {{
      display: inline-block; background: #1a3a2a; color: #4ade80;
      font-size: 0.75rem; font-weight: 700; padding: 0.1rem 0.45rem;
      border-radius: 3px; text-transform: uppercase; letter-spacing: 0.04em; margin-right: 0.25rem;
    }}
    p.callout {{
      background: #1e293b; border-left: 3px solid #f59e0b;
      padding: 0.6rem 1rem; border-radius: 0 0.35rem 0.35rem 0; color: #fde68a; margin: 0.75rem 0;
    }}
    .item-num {{ font-weight: 800; color: #60a5fa; margin-right: 0.25rem; }}
    .item-title {{ font-weight: 700; color: #f1f5f9; }}
    .swot-block {{ border-radius: 0.35rem; padding: 0.75rem 1rem; margin: 0.5rem 0; }}
    .swot-block ul {{ margin: 0.4rem 0 0; padding-left: 1.25rem; }}
    .swot-block li {{ margin: 0.2rem 0; font-size: 0.88rem; }}
    .swot-cat {{ font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; }}
    .swot-s {{ background: #052e16; color: #bbf7d0; }} .swot-s .swot-cat {{ color: #4ade80; }}
    .swot-w {{ background: #450a0a; color: #fecaca; }} .swot-w .swot-cat {{ color: #f87171; }}
    .swot-o {{ background: #0c1a3a; color: #bfdbfe; }} .swot-o .swot-cat {{ color: #60a5fa; }}
    .swot-t {{ background: #2d1b00; color: #fde68a; }} .swot-t .swot-cat {{ color: #fbbf24; }}
    /* Opportunity score cards */
    .opp-section {{ margin-bottom: 0.5rem; }}
    .opp-header {{
      font-size: 0.78rem; color: #64748b; margin: 0 0 0.75rem;
      text-transform: uppercase; letter-spacing: 0.05em;
    }}
    .opp-card {{
      background: #1e293b; border-radius: 0.5rem;
      border-left: 3px solid #3b82f6; margin-bottom: 0.6rem; overflow: hidden;
      padding: 0.85rem 1.1rem 0;
    }}
    .opp-hdr {{
      display: flex; align-items: center;
      justify-content: space-between; gap: 1rem; margin-bottom: 0.6rem;
    }}
    .opp-tkr {{
      font-size: 1.05rem; font-weight: 800; letter-spacing: 0.04em; color: #f1f5f9;
    }}
    .opp-score-col {{
      display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; min-width: 130px;
    }}
    .opp-score-num {{
      font-size: 1.1rem; font-weight: 800; line-height: 1;
    }}
    .opp-denom {{ font-size: 0.7rem; font-weight: 600; color: #64748b; }}
    .opp-bar-bg {{
      width: 100%; height: 5px; background: #334155;
      border-radius: 999px; overflow: hidden;
    }}
    .opp-bar-fill {{ height: 100%; border-radius: 999px; }}
    .opp-signals {{
      display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.75rem;
    }}
    .opp-pill {{
      font-size: 0.72rem; font-weight: 600; padding: 0.18rem 0.6rem;
      border-radius: 999px; white-space: nowrap;
    }}
    .opp-eval {{
      font-size: 0.875rem; color: #cbd5e1; line-height: 1.65;
      padding: 0.6rem 0 0.85rem; border-top: 1px solid #2a3a50;
    }}
    .opp-eval p {{ margin: 0.4rem 0; }}
    .opp-eval ol, .opp-eval ul {{ margin: 0.4rem 0; padding-left: 1.4rem; }}
    .opp-eval li {{ margin: 0.3rem 0; }}
    .opp-eval strong {{ color: #f1f5f9; }}
    .opp-eval-muted {{ color: #475569; font-style: italic; }}
    /* Company accordion cards */
    .co-card {{
      background: #1e293b; border-radius: 0.5rem;
      border-left: 3px solid #3b82f6; margin-bottom: 0.85rem; overflow: hidden;
    }}
    .co-hdr {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.8rem 1.1rem; border-bottom: 1px solid #334155; flex-wrap: wrap; gap: 0.5rem;
    }}
    .co-hdr-l {{ display: flex; align-items: center; gap: 0.55rem; }}
    .tkr {{
      font-size: 0.9rem; font-weight: 800; letter-spacing: 0.04em; color: #f1f5f9;
      background: #0f172a; padding: 0.15rem 0.55rem; border-radius: 4px;
    }}
    .co-name {{ font-size: 0.875rem; color: #94a3b8; }}
    .co-hdr-r {{ display: flex; gap: 0.35rem; flex-wrap: wrap; align-items: center; }}
    .vbadge, .mbadge {{
      font-size: 0.68rem; font-weight: 700; padding: 0.18rem 0.55rem;
      border-radius: 999px; text-transform: uppercase; letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    .v-hold   {{ background: #052e16; color: #4ade80; }}
    .v-watch  {{ background: #2d1b00; color: #fbbf24; }}
    .v-entry  {{ background: #0c1a3a; color: #60a5fa; }}
    .v-act    {{ background: #450a0a; color: #f87171; }}
    .v-neutral{{ background: #1e293b; color: #94a3b8; border: 1px solid #334155; }}
    .m-yes    {{ background: #0c1a3a; color: #93c5fd; }}
    .m-no     {{ background: #1e293b; color: #64748b; border: 1px solid #334155; }}
    details.acc-item {{ border-top: 1px solid #2a3a50; }}
    details.acc-item:first-of-type {{ border-top: none; }}
    summary.acc-sum {{
      list-style: none; cursor: pointer; user-select: none;
      padding: 0.6rem 1.1rem; display: flex; align-items: center; gap: 0.45rem;
      font-size: 0.74rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.06em; color: #64748b;
    }}
    summary.acc-sum::-webkit-details-marker {{ display: none; }}
    summary.acc-sum::before {{
      content: "▶"; font-size: 0.5rem; color: #3b82f6;
      transition: transform 0.12s; flex-shrink: 0;
    }}
    details[open] > summary.acc-sum::before {{ transform: rotate(90deg); }}
    summary.acc-sum:hover {{ color: #cbd5e1; background: #263244; }}
    .acc-body {{
      padding: 0.6rem 1.1rem 0.9rem; font-size: 0.9rem;
      color: #cbd5e1; line-height: 1.65;
    }}
    .acc-body p {{ margin: 0.45rem 0; }}
    .acc-body ul {{ margin: 0.45rem 0; padding-left: 1.4rem; }}
    .acc-body li {{ margin: 0.3rem 0; }}
    .acc-body strong {{ color: #f1f5f9; }}
    /* Footer */
    footer {{
      text-align: center; padding: 2rem 1.5rem; font-size: 0.78rem;
      color: #475569; border-top: 1px solid #1e293b; margin-top: 2rem;
    }}
    @media (max-width: 600px) {{
      header {{ padding: 1rem; }}
      main {{ padding: 0 1rem; }}
      .section {{ padding: 1rem; }}
    }}
  </style>
  {_NAV_LINK}
</head>
<body>
  {nav_html}
  <header>
    <h1>{html.escape(title)}</h1>
    {subtitle_html}
  </header>
  <main>
    {main_body}
  </main>
  <footer>
    System-generated using market data and an AI language model.
    Not financial advice. Always do your own research before making any investment decision.
  </footer>
</body>
</html>
"""


def build_portfolio_page_html(portfolio_data: dict, updated_at: str = "") -> str:
    """Return a complete, self-contained HTML page for the paper-trading portfolio dashboard."""
    inner = _build_portfolio_tab(portfolio_data)
    updated_html = (
        f'<p class="subtitle">Updated {html.escape(updated_at)}</p>'
        if updated_at else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Paper Portfolio</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a; color: #e2e8f0; min-height: 100vh; line-height: 1.6;
    }}
    header {{
      background: #1e293b; border-bottom: 1px solid #334155; padding: 1.5rem 2rem;
    }}
    header h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; font-weight: 700; color: #f1f5f9; }}
    .subtitle {{ margin: 0; font-size: 0.85rem; color: #64748b; }}
    main {{ max-width: 900px; margin: 2rem auto; padding: 0 1.5rem; }}
    /* Summary row */
    .port-summary {{
      display: flex; flex-wrap: wrap; gap: 1rem;
      background: #1e293b; border-radius: 0.5rem; padding: 1.25rem 1.5rem; margin-bottom: 1.25rem;
    }}
    .ps {{ display: flex; flex-direction: column; gap: 0.15rem; min-width: 110px; }}
    .pl {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }}
    .pv {{ font-size: 1.15rem; font-weight: 700; color: #f1f5f9; }}
    /* NAV chart */
    .chart-wrap {{
      background: #1e293b; border-radius: 0.5rem;
      padding: 1rem 1.5rem 0.75rem; margin-bottom: 1.25rem;
    }}
    .chart-label {{ font-size: 0.75rem; color: #64748b; margin-bottom: 0.5rem; }}
    /* Section headings */
    .sub-hd {{
      font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; color: #60a5fa; margin: 1.75rem 0 0.6rem;
    }}
    /* Tables */
    .tbl-wrap {{ overflow-x: auto; margin-bottom: 1rem; }}
    .dt {{
      width: 100%; border-collapse: collapse; font-size: 0.875rem;
      background: #1e293b; border-radius: 0.5rem; overflow: hidden;
    }}
    .dt thead {{ background: #0f172a; }}
    .dt th {{
      text-align: left; padding: 0.6rem 0.85rem; font-size: 0.72rem;
      text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; white-space: nowrap;
    }}
    .dt td {{ padding: 0.55rem 0.85rem; border-top: 1px solid #334155; vertical-align: middle; }}
    .dt tbody tr:hover {{ background: #263244; }}
    .tc {{ font-weight: 700; color: #f1f5f9; letter-spacing: 0.03em; }}
    .rc {{ color: #94a3b8; font-size: 0.8rem; max-width: 220px; }}
    .cash-row td {{ color: #64748b; font-style: italic; }}
    footer {{
      text-align: center; padding: 2rem 1.5rem; font-size: 0.78rem;
      color: #475569; border-top: 1px solid #1e293b; margin-top: 2rem;
    }}
    @media (max-width: 600px) {{
      header {{ padding: 1rem; }}
      main {{ padding: 0 1rem; }}
      .port-summary {{ gap: 0.75rem; }}
    }}
  </style>
  {_NAV_LINK}
</head>
<body>
  {_site_nav("portfolio")}
  <header>
    <h1>Paper Portfolio</h1>
    {updated_html}
  </header>
  <main>{inner}</main>
  <footer>
    Simulated paper trading — not real money. Not financial advice.
  </footer>
</body>
</html>
"""
